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
        instance.execute.assert_any_call(100)
        instance.execute.assert_any_call(200)
        instance.execute.assert_any_call(300)


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
        instance.execute.assert_called_once_with(500)


# ===================================================================
#  run_scheduled_pipelines — no environments at all
# ===================================================================

class TestRunPipelinesNoEnvironments:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_no_environments_does_nothing(self, mock_cls):
        """When there are zero environments, execute() is never called."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = []

        instance = MagicMock()
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        instance.execute.assert_not_called()
        db.get_bindings_for_environment.assert_not_called()


# ===================================================================
#  run_scheduled_pipelines — extraction raises exception (logs and continues)
# ===================================================================

class TestRunPipelinesExtractionException:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_extraction_exception_logged_and_continues(self, mock_cls):
        """If execute() raises for one chat, remaining chats still get processed."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [
            {"name": "env1"},
        ]
        db.get_bindings_for_environment.return_value = [100, 200, 300]

        instance = MagicMock()
        instance.execute.side_effect = [
            [],                          # chat 100 ok
            Exception("LLM timeout"),    # chat 200 fails
            [],                          # chat 300 ok
        ]
        mock_cls.return_value = instance

        # Should not raise — exception is caught and logged
        run_scheduled_pipelines(memory, db)

        # All 3 chats attempted despite the middle one failing
        assert instance.execute.call_count == 3
        instance.execute.assert_any_call(100)
        instance.execute.assert_any_call(200)
        instance.execute.assert_any_call(300)

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_multiple_exceptions_all_logged(self, mock_cls):
        """Even if every chat fails, the pipeline completes without crashing."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [{"name": "env1"}]
        db.get_bindings_for_environment.return_value = [100, 200]

        instance = MagicMock()
        instance.execute.side_effect = [
            RuntimeError("err1"),
            ValueError("err2"),
        ]
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        assert instance.execute.call_count == 2


# ===================================================================
#  run_scheduled_pipelines — multiple environments with multiple bindings
# ===================================================================

class TestRunPipelinesMultipleEnvsMultipleBindings:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_multiple_envs_multiple_bindings(self, mock_cls):
        """3 environments with varying binding counts — verify exact call list."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [
            {"name": "editorial"},
            {"name": "tech"},
            {"name": "finance"},
        ]
        db.get_bindings_for_environment.side_effect = [
            [10, 20, 30],  # editorial: 3 chats
            [],             # tech: 0 chats
            [40, 50],       # finance: 2 chats
        ]

        instance = MagicMock()
        instance.execute.return_value = ["some-id"]
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        assert instance.execute.call_count == 5
        expected_calls = [
            call(10), call(20), call(30), call(40), call(50),
        ]
        instance.execute.assert_has_calls(expected_calls, any_order=False)

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_extractor_receives_memory_and_db(self, mock_cls):
        """Verify ExtractConversationKnowledge is constructed with memory and db."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = []

        run_scheduled_pipelines(memory, db)

        mock_cls.assert_called_once_with(memory, db)


# ===================================================================
#  run_scheduled_pipelines — all envs have empty bindings
# ===================================================================

class TestRunPipelinesAllEnvsEmptyBindings:

    @patch("backend.domain.use_cases.run_knowledge_pipelines.ExtractConversationKnowledge")
    def test_all_envs_empty_bindings(self, mock_cls):
        """Multiple environments but all have zero bindings — no extraction."""
        memory = MagicMock()
        db = MagicMock()
        db.list_environments.return_value = [
            {"name": "env_a"},
            {"name": "env_b"},
            {"name": "env_c"},
        ]
        db.get_bindings_for_environment.return_value = []

        instance = MagicMock()
        mock_cls.return_value = instance

        run_scheduled_pipelines(memory, db)

        instance.execute.assert_not_called()
        assert db.get_bindings_for_environment.call_count == 3
