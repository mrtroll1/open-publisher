"""Inbox controller — email classification and routing."""

from __future__ import annotations

from backend.brain.base_controller import BaseController, PassThroughPreparer
from backend.brain.dynamic.inbox_classify import InboxClassify
from backend.commands.process_inbox import InboxProcessUseCase, InboxWorkflow


class InboxController(BaseController):
    def __init__(self, classifier: InboxClassify, workflow: InboxWorkflow):
        super().__init__(PassThroughPreparer(), InboxProcessUseCase(classifier, workflow))
