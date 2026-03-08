"""Composition root — wires up all dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from backend.brain import Brain
from backend.brain.authorizer import Authorizer
from backend.brain.controllers.conversation import conversation_handler
from backend.brain.dynamic import (
    AssessEditorial,
    ClassifyInbox,
    ClassifyTeaching,
    SummarizeArticle,
    TechSupport,
)
from backend.brain.dynamic.query_db import QueryDB
from backend.brain.router import Router
from backend.brain.tool import register_tool
from backend.brain.tools import (
    make_budget_tool,
    make_cloudflare_tool,
    make_code_tool,
    make_health_tool,
    make_ingest_tool,
    make_invoice_tool,
    make_query_db_tools,
    make_search_tool,
    make_support_tool,
    make_teach_tool,
    make_yandex_metrica_tool,
)
from backend.commands.bank.parse_statement import ParseBankStatement
from backend.commands.budget.compute import ComputeBudget
from backend.commands.draft_support import TechSupportHandler
from backend.commands.invoice.batch import GenerateBatchInvoices
from backend.commands.invoice.generate import GenerateInvoice
from backend.commands.process_inbox import InboxWorkflow
from backend.commands.run_code import _set_retriever
from backend.config import (
    DATABASE_URL,
    REDEFINE_RO_DB_HOST,
    REDEFINE_RO_DB_NAME,
    REDEFINE_RO_DB_PASS,
    REDEFINE_RO_DB_PORT,
    REDEFINE_RO_DB_USER,
    REDEFINE_SSH_HOST,
    REDEFINE_SSH_KEY_PATH,
    REDEFINE_SSH_USER,
    REPUBLIC_RO_DB_HOST,
    REPUBLIC_RO_DB_NAME,
    REPUBLIC_RO_DB_PASS,
    REPUBLIC_RO_DB_PORT,
    REPUBLIC_RO_DB_USER,
    REPUBLIC_SSH_HOST,
    REPUBLIC_SSH_KEY_PATH,
    REPUBLIC_SSH_USER,
)
from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
from backend.infrastructure.gateways.cloudflare_gateway import CloudflareGateway
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.query_gateway import LocalQueryGateway, QueryGateway
from backend.infrastructure.gateways.redefine_gateway import RedefineGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.infrastructure.gateways.yandex_metrica_gateway import YandexMetricaGateway
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.memory.user_lookup import SupportUserLookup
from backend.infrastructure.repositories.postgres import DbGateway


def create_db() -> DbGateway:
    db = DbGateway()
    db.init_schema()
    return db



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


def _try_add_gateway(  # noqa: PLR0913
    gateways: dict[str, QueryGateway], name: str,
    ssh_host: str, ssh_user: str, ssh_key_path: str,
    db_host: str, db_port: int, db_name: str, db_user: str, db_pass: str,
) -> None:
    gw = QueryGateway(
        ssh_host=ssh_host, ssh_user=ssh_user, ssh_key_path=ssh_key_path,
        db_host=db_host, db_port=db_port, db_name=db_name,
        db_user=db_user, db_pass=db_pass, name=name,
    )
    if gw.available:
        gateways[f"{name}_db"] = gw


def create_query_gateways() -> dict[str, QueryGateway]:
    """Create query gateways for available external DBs."""
    gateways: dict[str, QueryGateway] = {}
    _try_add_gateway(
        gateways, "republic",
        REPUBLIC_SSH_HOST, REPUBLIC_SSH_USER, REPUBLIC_SSH_KEY_PATH,
        REPUBLIC_RO_DB_HOST, REPUBLIC_RO_DB_PORT, REPUBLIC_RO_DB_NAME,
        REPUBLIC_RO_DB_USER, REPUBLIC_RO_DB_PASS,
    )
    _try_add_gateway(
        gateways, "redefine",
        REDEFINE_SSH_HOST, REDEFINE_SSH_USER, REDEFINE_SSH_KEY_PATH,
        REDEFINE_RO_DB_HOST, REDEFINE_RO_DB_PORT, REDEFINE_RO_DB_NAME,
        REDEFINE_RO_DB_USER, REDEFINE_RO_DB_PASS,
    )
    return gateways


@dataclass
class BrainComponents:
    brain: Brain
    inbox: InboxWorkflow
    memory: MemoryService
    db: DbGateway
    retriever: KnowledgeRetriever


def _create_infrastructure() -> tuple[DbGateway, GeminiGateway, EmbeddingGateway, KnowledgeRetriever, MemoryService]:
    db = create_db()
    gemini = GeminiGateway()
    embed = EmbeddingGateway()
    retriever = KnowledgeRetriever(db=db, embed=embed)
    memory = MemoryService(db=db, embed=embed, retriever=retriever)
    return db, gemini, embed, retriever, memory


def _create_genai_instances(gemini, db, embed, retriever) -> dict:
    return {
        "classify_teaching": ClassifyTeaching(gemini, db, embed),
        "tech_support": TechSupport(gemini, retriever, db),
        "inbox_classify": ClassifyInbox(gemini, retriever),
        "editorial_assess": AssessEditorial(gemini, retriever),
        "summarize_article": SummarizeArticle(gemini, retriever),
    }


def _create_query_db_map(gemini, query_gateways, db) -> dict:
    query_db_map: dict = {}
    for name, gw in query_gateways.items():
        domain = name.removesuffix("_db")
        query_db_map[name] = QueryDB(gemini, gw, db, schema_domain=f"{domain}_db")
    own_db_gw = LocalQueryGateway(DATABASE_URL, name="agent")
    if own_db_gw.available:
        query_db_map["agent_db"] = QueryDB(gemini, own_db_gw, db, schema_domain="agent_db")
    return query_db_map


def _register_tools(genai, memory, retriever, query_db_map, gemini) -> None:
    _register_core_tools(genai, memory, retriever, gemini)
    _register_domain_tools(genai, memory, query_db_map)
    _register_optional_analytics()


def _register_core_tools(genai, memory, retriever, gemini) -> None:
    register_tool(make_teach_tool(genai["classify_teaching"], memory, gemini))
    register_tool(make_search_tool(retriever))
    register_tool(make_support_tool(genai["tech_support"]))
    _set_retriever(retriever)
    register_tool(make_code_tool())
    register_tool(make_health_tool())


def _register_domain_tools(genai, memory, query_db_map) -> None:
    gen_invoice = GenerateInvoice(docs_gw=DocsGateway(), drive_gw=DriveGateway())
    register_tool(make_invoice_tool(gen_invoice))
    compute_budget = ComputeBudget(republic_gw=RepublicGateway(), redefine_gw=RedefineGateway())
    register_tool(make_budget_tool(compute_budget))
    register_tool(make_ingest_tool(genai["summarize_article"], memory))
    for tool in make_query_db_tools(query_db_map):
        register_tool(tool)


def _register_optional_analytics() -> None:
    ym_gw = YandexMetricaGateway()
    if ym_gw.available:
        register_tool(make_yandex_metrica_tool(ym_gw))
    cf_gw = CloudflareGateway()
    if cf_gw.available:
        register_tool(make_cloudflare_tool(cf_gw))


def _create_inbox_workflow(gemini, db, retriever, genai) -> InboxWorkflow:
    republic = RepublicGateway()
    redefine = RedefineGateway()
    email_gw = EmailGateway()
    user_lookup = SupportUserLookup(republic_gw=republic, redefine_gw=redefine)
    tech_support_handler = TechSupportHandler(
        gemini=gemini, user_lookup=user_lookup, db=db, retriever=retriever,
    )
    return InboxWorkflow(
        tech_support=tech_support_handler, email_gw=email_gw, db=db,
        classifier=genai["inbox_classify"], assessor=genai["editorial_assess"],
    )


def create_brain() -> BrainComponents:
    """Wire up Brain with all tools. Returns shared components."""
    db, gemini, embed, retriever, memory = _create_infrastructure()
    query_gateways = create_query_gateways()
    genai = _create_genai_instances(gemini, db, embed, retriever)
    query_db_map = _create_query_db_map(gemini, query_gateways, db)
    _register_tools(genai, memory, retriever, query_db_map, gemini)
    conv_handler = conversation_handler(gemini, db, retriever)
    inbox_workflow = _create_inbox_workflow(gemini, db, retriever, genai)
    authorizer = Authorizer(db)
    router = Router(gemini)
    return BrainComponents(
        brain=Brain(authorizer, router, conversation_fn=conv_handler),
        inbox=inbox_workflow,
        memory=memory,
        db=db,
        retriever=retriever,
    )
