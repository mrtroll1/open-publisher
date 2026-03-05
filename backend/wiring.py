"""Composition root — wires up all dependencies."""

from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
from backend.infrastructure.repositories.postgres import DbGateway
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.query_gateway import QueryGateway
from backend.infrastructure.gateways.redefine_gateway import RedefineGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.domain.services.inbox_service import InboxService
from backend.domain.services.knowledge_retriever import KnowledgeRetriever
from backend.domain.services.memory_service import MemoryService
from backend.domain.services.query_tool import QueryTool
from backend.domain.services.support_user_lookup import SupportUserLookup
from backend.domain.services.tech_support_handler import TechSupportHandler
from backend.domain.services.tool_router import ToolRouter
from backend.domain.use_cases.compute_budget import ComputeBudget
from backend.domain.use_cases.generate_batch_invoices import GenerateBatchInvoices
from backend.domain.use_cases.generate_invoice import GenerateInvoice
from backend.domain.use_cases.parse_bank_statement import ParseBankStatement


def create_db() -> DbGateway:
    db = DbGateway()
    db.init_schema()
    return db


def create_inbox_service() -> InboxService:
    db = create_db()
    gemini = GeminiGateway()
    email_gw = EmailGateway()
    republic = RepublicGateway()
    redefine = RedefineGateway()
    user_lookup = SupportUserLookup(republic_gw=republic, redefine_gw=redefine)
    tech_support = TechSupportHandler(gemini=gemini, user_lookup=user_lookup, db=db)
    return InboxService(tech_support=tech_support, gemini=gemini, email_gw=email_gw, db=db)


def create_knowledge_retriever() -> KnowledgeRetriever:
    db = create_db()
    embed = EmbeddingGateway()
    return KnowledgeRetriever(db=db, embed=embed)


def create_compute_budget() -> ComputeBudget:
    return ComputeBudget(republic_gw=RepublicGateway(), redefine_gw=RedefineGateway())


def create_generate_batch_invoices() -> GenerateBatchInvoices:
    gen = GenerateInvoice(docs_gw=DocsGateway(), drive_gw=DriveGateway())
    return GenerateBatchInvoices(republic_gw=RepublicGateway(), gen_invoice=gen)


def create_memory_service() -> MemoryService:
    db = create_db()
    embed = EmbeddingGateway()
    retriever = KnowledgeRetriever(db=db, embed=embed)
    return MemoryService(db=db, embed=embed, retriever=retriever)


def create_parse_bank_statement() -> ParseBankStatement:
    return ParseBankStatement(airtable_gw=AirtableGateway())


def create_query_tools() -> dict[str, QueryTool]:
    """Create QueryTool instances for available external DBs."""
    from common.config import (
        REPUBLIC_SSH_HOST, REPUBLIC_SSH_USER, REPUBLIC_SSH_KEY_PATH,
        REPUBLIC_RO_DB_HOST, REPUBLIC_RO_DB_PORT, REPUBLIC_RO_DB_NAME,
        REPUBLIC_RO_DB_USER, REPUBLIC_RO_DB_PASS,
        REDEFINE_SSH_HOST, REDEFINE_SSH_USER, REDEFINE_SSH_KEY_PATH,
        REDEFINE_RO_DB_HOST, REDEFINE_RO_DB_PORT, REDEFINE_RO_DB_NAME,
        REDEFINE_RO_DB_USER, REDEFINE_RO_DB_PASS,
    )
    tools = {}

    republic_gw = QueryGateway(
        ssh_host=REPUBLIC_SSH_HOST, ssh_user=REPUBLIC_SSH_USER,
        ssh_key_path=REPUBLIC_SSH_KEY_PATH,
        db_host=REPUBLIC_RO_DB_HOST, db_port=REPUBLIC_RO_DB_PORT,
        db_name=REPUBLIC_RO_DB_NAME, db_user=REPUBLIC_RO_DB_USER,
        db_pass=REPUBLIC_RO_DB_PASS, name="republic",
    )
    if republic_gw.available:
        tools["republic_db"] = QueryTool(republic_gw, "db-query/republic-schema.md")

    redefine_gw = QueryGateway(
        ssh_host=REDEFINE_SSH_HOST, ssh_user=REDEFINE_SSH_USER,
        ssh_key_path=REDEFINE_SSH_KEY_PATH,
        db_host=REDEFINE_RO_DB_HOST, db_port=REDEFINE_RO_DB_PORT,
        db_name=REDEFINE_RO_DB_NAME, db_user=REDEFINE_RO_DB_USER,
        db_pass=REDEFINE_RO_DB_PASS, name="redefine",
    )
    if redefine_gw.available:
        tools["redefine_db"] = QueryTool(redefine_gw, "db-query/redefine-schema.md")

    return tools


def create_tool_router(query_tools: dict[str, QueryTool] | None = None) -> ToolRouter:
    """Create ToolRouter with available tools."""
    if query_tools is None:
        query_tools = create_query_tools()
    available = ["rag"] + list(query_tools.keys())
    return ToolRouter(available_tools=available)
