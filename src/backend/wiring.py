"""Composition root — wires up all dependencies."""

from dataclasses import dataclass
from typing import Any

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
from backend.infrastructure.memory.retriever import KnowledgeRetriever
from backend.infrastructure.memory.memory_service import MemoryService
from backend.infrastructure.memory.user_lookup import SupportUserLookup
from backend.commands.draft_support import TechSupportHandler
from backend.commands.budget.compute import ComputeBudget
from backend.commands.invoice.batch import GenerateBatchInvoices
from backend.commands.invoice.generate import GenerateInvoice
from backend.commands.bank.parse_statement import ParseBankStatement


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


def create_query_gateways() -> dict[str, QueryGateway]:
    """Create query gateways for available external DBs."""
    from backend.config import (
        REPUBLIC_SSH_HOST, REPUBLIC_SSH_USER, REPUBLIC_SSH_KEY_PATH,
        REPUBLIC_RO_DB_HOST, REPUBLIC_RO_DB_PORT, REPUBLIC_RO_DB_NAME,
        REPUBLIC_RO_DB_USER, REPUBLIC_RO_DB_PASS,
        REDEFINE_SSH_HOST, REDEFINE_SSH_USER, REDEFINE_SSH_KEY_PATH,
        REDEFINE_RO_DB_HOST, REDEFINE_RO_DB_PORT, REDEFINE_RO_DB_NAME,
        REDEFINE_RO_DB_USER, REDEFINE_RO_DB_PASS,
    )
    gateways = {}

    republic_gw = QueryGateway(
        ssh_host=REPUBLIC_SSH_HOST, ssh_user=REPUBLIC_SSH_USER,
        ssh_key_path=REPUBLIC_SSH_KEY_PATH,
        db_host=REPUBLIC_RO_DB_HOST, db_port=REPUBLIC_RO_DB_PORT,
        db_name=REPUBLIC_RO_DB_NAME, db_user=REPUBLIC_RO_DB_USER,
        db_pass=REPUBLIC_RO_DB_PASS, name="republic",
    )
    if republic_gw.available:
        gateways["republic_db"] = republic_gw

    redefine_gw = QueryGateway(
        ssh_host=REDEFINE_SSH_HOST, ssh_user=REDEFINE_SSH_USER,
        ssh_key_path=REDEFINE_SSH_KEY_PATH,
        db_host=REDEFINE_RO_DB_HOST, db_port=REDEFINE_RO_DB_PORT,
        db_name=REDEFINE_RO_DB_NAME, db_user=REDEFINE_RO_DB_USER,
        db_pass=REDEFINE_RO_DB_PASS, name="redefine",
    )
    if redefine_gw.available:
        gateways["redefine_db"] = redefine_gw

    return gateways


@dataclass
class BrainComponents:
    brain: Any
    inbox: Any
    memory: Any
    db: Any
    retriever: Any
    classify_teaching: Any = None


def create_brain() -> BrainComponents:
    """Wire up Brain with all tools. Returns shared components."""
    from backend.brain import Brain
    from backend.brain.authorizer import Authorizer
    from backend.brain.dynamic import (
        ClassifyTeaching, EditorialAssess,
        InboxClassify, SummarizeArticle, TechSupport,
    )
    from backend.brain.dynamic.query_db import QueryDB
    from backend.brain.router import Router
    from backend.brain.tool import register_tool
    from backend.brain.tools import (
        make_teach_tool, make_search_tool, make_support_tool,
        make_code_tool, make_health_tool, make_invoice_tool,
        make_budget_tool, make_ingest_tool, make_query_db_tools,
    )
    from backend.brain.controllers.conversation import conversation_handler
    from backend.commands.process_inbox import InboxWorkflow

    # Infrastructure
    db = create_db()
    gemini = GeminiGateway()
    embed = EmbeddingGateway()
    retriever = KnowledgeRetriever(db=db, embed=embed)
    memory = MemoryService(db=db, embed=embed, retriever=retriever)

    # Query gateways (SSH-tunneled external DBs)
    query_gateways = create_query_gateways()

    # GenAI instances (still needed by some tools)
    classify_teaching = ClassifyTeaching(gemini, db, embed)
    tech_support = TechSupport(gemini, retriever, db)
    inbox_classify = InboxClassify(gemini, retriever)
    editorial_assess = EditorialAssess(gemini, retriever)
    summarize_article = SummarizeArticle(gemini, retriever)

    # QueryDB instances for external DBs + our own DB
    # Each uses its own schema_domain so Gemini sees only relevant schema
    from backend.infrastructure.gateways.query_gateway import LocalQueryGateway
    from backend.config import DATABASE_URL
    query_db_map: dict = {}
    for name, gw in query_gateways.items():
        # republic_db → republic, redefine_db → redefine
        domain = name.removesuffix("_db")
        query_db_map[name] = QueryDB(gemini, gw, db, schema_domain=f"{domain}_db")
    own_db_gw = LocalQueryGateway(DATABASE_URL, name="agent")
    if own_db_gw.available:
        query_db_map["agent_db"] = QueryDB(gemini, own_db_gw, db, schema_domain="agent_db")

    # Register all tools
    register_tool(make_teach_tool(classify_teaching, memory))
    register_tool(make_search_tool(retriever))
    register_tool(make_support_tool(tech_support))
    from backend.commands.run_code import _set_retriever
    _set_retriever(retriever)
    register_tool(make_code_tool())
    register_tool(make_health_tool())

    gen_invoice = GenerateInvoice(docs_gw=DocsGateway(), drive_gw=DriveGateway())
    register_tool(make_invoice_tool(gen_invoice))

    compute_budget = ComputeBudget(republic_gw=RepublicGateway(), redefine_gw=RedefineGateway())
    register_tool(make_budget_tool(compute_budget))

    register_tool(make_ingest_tool(summarize_article, memory))

    for tool in make_query_db_tools(query_db_map):
        register_tool(tool)

    # Conversation handler (ReAct loop)
    conv_handler = conversation_handler(gemini, db, retriever)

    # Inbox workflow
    republic = RepublicGateway()
    redefine = RedefineGateway()
    email_gw = EmailGateway()
    user_lookup = SupportUserLookup(republic_gw=republic, redefine_gw=redefine)
    tech_support_handler = TechSupportHandler(gemini=gemini, user_lookup=user_lookup, db=db, retriever=retriever)
    inbox_workflow = InboxWorkflow(
        tech_support=tech_support_handler, email_gw=email_gw, db=db,
        classifier=inbox_classify, assessor=editorial_assess,
    )

    authorizer = Authorizer(db)
    router = Router(gemini)
    return BrainComponents(
        brain=Brain(authorizer, router, conversation_fn=conv_handler),
        inbox=inbox_workflow,
        memory=memory,
        db=db,
        retriever=retriever,
        classify_teaching=classify_teaching,
    )
