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


@dataclass
class _QuerySource:
    gateway: QueryGateway
    schema_template: str

    @property
    def available(self) -> bool:
        return self.gateway.available


def create_query_tools() -> dict[str, _QuerySource]:
    """Create query source configs for available external DBs."""
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
        tools["republic_db"] = _QuerySource(republic_gw, "db-query/republic-schema.md")

    redefine_gw = QueryGateway(
        ssh_host=REDEFINE_SSH_HOST, ssh_user=REDEFINE_SSH_USER,
        ssh_key_path=REDEFINE_SSH_KEY_PATH,
        db_host=REDEFINE_RO_DB_HOST, db_port=REDEFINE_RO_DB_PORT,
        db_name=REDEFINE_RO_DB_NAME, db_user=REDEFINE_RO_DB_USER,
        db_pass=REDEFINE_RO_DB_PASS, name="redefine",
    )
    if redefine_gw.available:
        tools["redefine_db"] = _QuerySource(redefine_gw, "db-query/redefine-schema.md")

    return tools


@dataclass
class BrainComponents:
    brain: Any
    inbox: Any
    memory: Any
    db: Any
    retriever: Any


def create_brain() -> BrainComponents:
    """Wire up Brain with all controllers and routes. Returns shared components."""
    from backend.brain import Brain
    from backend.brain.authorizer import Authorizer
    from backend.brain.dynamic import (
        ClassifyTeaching, ConversationReply, EditorialAssess,
        InboxClassify, SummarizeArticle, TechSupport, ToolRouting,
    )
    from backend.brain.dynamic.query_db import QueryDB
    from backend.brain.router import Router
    from backend.brain.routes import ROUTE_DEFINITIONS, ROUTES, Route, register_route
    from backend.brain.controllers import (
        BudgetController, CodeController, ConversationController,
        HealthController, InboxController, IngestController,
        InvoiceController, SearchController,
        SupportController, TeachController,
    )
    from backend.commands.process_inbox import InboxWorkflow

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

    # ConversationReply needs QueryDB (BaseGenAI), not raw query source
    query_db_map: dict = {}
    for name, qs in query_tools.items():
        query_db_map[name] = QueryDB(gemini, qs.gateway, qs.schema_template)

    conversation_reply = ConversationReply(gemini, retriever, tool_routing, query_db_map)
    classify_teaching = ClassifyTeaching(gemini, db, embed)
    tech_support = TechSupport(gemini, retriever, db)
    inbox_classify = InboxClassify(gemini, retriever)
    editorial_assess = EditorialAssess(gemini, retriever)
    summarize_article = SummarizeArticle(gemini, retriever)

    # Controllers
    conv_ctrl = ConversationController(conversation_reply, db, retriever)
    support_ctrl = SupportController(tech_support)
    from backend.commands.run_code import _set_retriever
    _set_retriever(retriever)
    code_ctrl = CodeController()
    health_ctrl = HealthController()
    teach_ctrl = TeachController(classify_teaching, memory)
    search_ctrl = SearchController(retriever)
    ingest_ctrl = IngestController(summarize_article, memory)

    # Invoice controller
    gen_invoice = GenerateInvoice(docs_gw=DocsGateway(), drive_gw=DriveGateway())
    invoice_ctrl = InvoiceController(gen_invoice)

    # Budget controller
    compute_budget = ComputeBudget(republic_gw=RepublicGateway(), redefine_gw=RedefineGateway())
    budget_ctrl = BudgetController(compute_budget)

    # Inbox controller
    republic = RepublicGateway()
    redefine = RedefineGateway()
    email_gw = EmailGateway()
    user_lookup = SupportUserLookup(republic_gw=republic, redefine_gw=redefine)
    tech_support_handler = TechSupportHandler(gemini=gemini, user_lookup=user_lookup, db=db, retriever=retriever)
    inbox_workflow = InboxWorkflow(
        tech_support=tech_support_handler, email_gw=email_gw, db=db,
        classifier=inbox_classify, assessor=editorial_assess,
    )
    inbox_ctrl = InboxController(inbox_classify, inbox_workflow)

    # Build controller map
    ctrl_map = {
        "conversation": conv_ctrl,
        "support": support_ctrl,
        "code": code_ctrl,
        "health": health_ctrl,
        "teach": teach_ctrl,
        "search": search_ctrl,
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
    return BrainComponents(
        brain=Brain(authorizer, router),
        inbox=inbox_workflow,
        memory=memory,
        db=db,
        retriever=retriever,
    )


