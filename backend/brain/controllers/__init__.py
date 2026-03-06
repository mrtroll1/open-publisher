"""Named controller classes for all brain routes."""

from backend.brain.controllers.bank import BankController
from backend.brain.controllers.budget import BudgetController
from backend.brain.controllers.code import CodeController
from backend.brain.controllers.contractor import ContractorController
from backend.brain.controllers.conversation import ConversationController
from backend.brain.controllers.health import HealthController
from backend.brain.controllers.inbox import InboxController
from backend.brain.controllers.ingest import IngestController
from backend.brain.controllers.invoice import InvoiceController
from backend.brain.controllers.query import QueryController
from backend.brain.controllers.search import SearchController
from backend.brain.controllers.support import SupportController
from backend.brain.controllers.teach import TeachController

__all__ = [
    "BankController",
    "BudgetController",
    "CodeController",
    "ContractorController",
    "ConversationController",
    "HealthController",
    "InboxController",
    "IngestController",
    "InvoiceController",
    "QueryController",
    "SearchController",
    "SupportController",
    "TeachController",
]
