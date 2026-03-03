"""Composition root — wires up all dependencies."""

from backend.infrastructure.gateways.airtable_gateway import AirtableGateway
from backend.infrastructure.gateways.db_gateway import DbGateway
from backend.infrastructure.gateways.docs_gateway import DocsGateway
from backend.infrastructure.gateways.drive_gateway import DriveGateway
from backend.infrastructure.gateways.email_gateway import EmailGateway
from backend.infrastructure.gateways.embedding_gateway import EmbeddingGateway
from backend.infrastructure.gateways.gemini_gateway import GeminiGateway
from backend.infrastructure.gateways.redefine_gateway import RedefineGateway
from backend.infrastructure.gateways.republic_gateway import RepublicGateway
from backend.domain.services.inbox_service import InboxService
from backend.domain.services.knowledge_retriever import KnowledgeRetriever
from backend.domain.services.support_user_lookup import SupportUserLookup
from backend.domain.services.tech_support_handler import TechSupportHandler
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


def create_parse_bank_statement() -> ParseBankStatement:
    return ParseBankStatement(airtable_gw=AirtableGateway())
