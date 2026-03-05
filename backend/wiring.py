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


def create_brain():
    """Wire up Brain with all controllers and routes."""
    from backend.brain import Brain
    from backend.brain.authorizer import Authorizer
    from backend.brain.dynamic import (
        ClassifyTeaching, ConversationReply,
        InboxClassify, SummarizeArticle, TechSupport, ToolRouting,
    )
    from backend.brain.dynamic.query_db import QueryDB
    from backend.brain.router import Router
    from backend.brain.routes import ROUTE_DEFINITIONS, ROUTES, Route, register_route
    from backend.commands.budget import create_budget_controller
    from backend.commands.code import create_code_controller
    from backend.commands.conversation import create_conversation_controller
    from backend.commands.health import create_health_controller
    from backend.commands.support import create_support_controller
    from backend.commands.inbox import InboxWorkflow, create_inbox_controller
    from backend.commands.ingest import create_ingest_controller
    from backend.commands.invoice import create_invoice_controller
    from backend.commands.query import create_query_controller
    from backend.commands.search import create_search_controller
    from backend.commands.teach import create_teach_controller

    # Infrastructure
    db = create_db()
    gemini = GeminiGateway()
    embed = EmbeddingGateway()
    retriever = KnowledgeRetriever(db=db, embed=embed)
    memory = MemoryService(db=db, embed=embed, retriever=retriever)

    # Query tools (reuse existing factory)
    query_tools = create_query_tools()

    # Dynamic (GenAI) instances
    tool_routing = ToolRouting(gemini, available_tools=["rag"] + list(query_tools.keys()))

    # ConversationReply needs QueryDB (BaseGenAI), not QueryTool
    query_db_map: dict = {}
    for name, qt in query_tools.items():
        query_db_map[name] = QueryDB(gemini, qt._gateway, qt._schema_template)

    conversation_reply = ConversationReply(gemini, retriever, tool_routing, query_db_map)
    classify_teaching = ClassifyTeaching(gemini, db, embed)
    tech_support = TechSupport(gemini, retriever, db)
    inbox_classify = InboxClassify(gemini, retriever)
    summarize_article = SummarizeArticle(gemini, retriever)

    # Controllers
    conv_ctrl = create_conversation_controller(conversation_reply)
    support_ctrl = create_support_controller(tech_support)
    code_ctrl = create_code_controller()
    health_ctrl = create_health_controller()
    teach_ctrl = create_teach_controller(classify_teaching, memory)
    search_ctrl = create_search_controller(retriever)
    ingest_ctrl = create_ingest_controller(summarize_article, memory)

    # Query controller — use first available QueryDB, or stub
    query_ctrl = _create_query_ctrl(gemini, query_tools)

    # Invoice controller
    gen_invoice = GenerateInvoice(docs_gw=DocsGateway(), drive_gw=DriveGateway())
    invoice_ctrl = create_invoice_controller(gen_invoice)

    # Budget controller
    compute_budget = ComputeBudget(republic_gw=RepublicGateway(), redefine_gw=RedefineGateway())
    budget_ctrl = create_budget_controller(compute_budget)

    # Inbox controller
    inbox_workflow = InboxWorkflow(db=db, email_gw=EmailGateway())
    inbox_ctrl = create_inbox_controller(inbox_classify, inbox_workflow)

    # Build controller map
    ctrl_map = {
        "conversation": conv_ctrl,
        "support": support_ctrl,
        "code": code_ctrl,
        "health": health_ctrl,
        "teach": teach_ctrl,
        "search": search_ctrl,
        "query": query_ctrl,
        "invoice": invoice_ctrl,
        "budget": budget_ctrl,
        "ingest": ingest_ctrl,
        "inbox": inbox_ctrl,
    }

    # Register routes
    ROUTES.clear()
    for defn in ROUTE_DEFINITIONS:
        controller = ctrl_map.get(defn["name"])
        if controller is None:
            continue
        register_route(Route(
            name=defn["name"],
            controller=controller,
            description=defn["description"],
            examples=defn.get("examples", []),
            permissions=defn.get("permissions", {"admin"}),
            slash_command=defn.get("slash_command"),
        ))

    authorizer = Authorizer(db)
    router = Router(gemini)
    return Brain(authorizer, router)


def _create_query_ctrl(gemini, query_tools):
    """Create query controller from available query gateways, or stub."""
    from backend.brain.base_controller import BaseController, PassThroughPreparer, StubUseCase
    from backend.brain.dynamic.query_db import QueryDB
    from backend.commands.query import create_query_controller

    # Reuse gateway from first available QueryTool
    for qt in query_tools.values():
        if qt.available:
            query_db = QueryDB(gemini, qt._gateway, qt._schema_template)
            return create_query_controller(query_db)

    return BaseController(PassThroughPreparer(), StubUseCase("Query DB not available"))
