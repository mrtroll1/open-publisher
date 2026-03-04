from unittest.mock import MagicMock, patch, call

from backend.domain.use_cases.run_knowledge_pipelines import run_scheduled_pipelines


# ===================================================================
#  run_scheduled_pipelines — extracts for all environments
# ===================================================================

class TestRunPipelinesExtractsForAllEnvironments:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_run_pipelines_extracts_for_all_environments(self, mock_cls):
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [
            {"name": "editorial"},
            {"name": "tech"},
        ]
        db.get_bindings_for_environment.side_effect = [
            [100, 200],  # editorial has 2 chats
            [300],       # tech has 1 chat
        ]

        instance = MagicMock()
        instance.execute.return_value = []
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        assert instance.execute.call_count == 3
        instance.execute.assert_any_call(100, since_hours=24)
        instance.execute.assert_any_call(200, since_hours=24)
        instance.execute.assert_any_call(300, since_hours=24)


# ===================================================================
#  run_scheduled_pipelines — skips envs without bindings
# ===================================================================

class TestRunPipelinesSkipsEnvsWithoutBindings:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_run_pipelines_skips_envs_without_bindings(self, mock_cls):
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [
            {"name": "empty_env"},
            {"name": "active_env"},
        ]
        db.get_bindings_for_environment.side_effect = [
            [],     # empty_env has no chats
            [500],  # active_env has 1 chat
        ]

        instance = MagicMock()
        instance.execute.return_value = []
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        assert instance.execute.call_count == 1
        instance.execute.assert_called_once_with(500, since_hours=24)
