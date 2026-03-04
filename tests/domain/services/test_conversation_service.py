"""Tests for backend/domain/services/conversation_service.py."""

from unittest.mock import MagicMock, patch


# ===================================================================
#  format_reply_chain — pure logic
# ===================================================================

class TestFormatReplyChain:

    def _fmt(self, chain):
        from backend.domain.services.conversation_service import format_reply_chain
        return format_reply_chain(chain)

    def test_single_entry(self):
        chain = [{"role": "user", "content": "hello"}]
        assert self._fmt(chain) == "user: hello"

    def test_multiple_entries(self):
        chain = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
            {"role": "user", "content": "how are you?"},
        ]
        result = self._fmt(chain)
        assert result == "user: hi\nassistant: hello!\nuser: how are you?"

    def test_empty_chain(self):
        assert self._fmt([]) == ""

    def test_preserves_multiline_content(self):
        chain = [{"role": "user", "content": "line1\nline2"}]
        assert self._fmt(chain) == "user: line1\nline2"


# ===================================================================
#  build_conversation_context — mock DB
# ===================================================================

class TestBuildConversationContext:

    def _build(self, chat_id, reply_message_id, reply_text, db):
        from backend.domain.services.conversation_service import build_conversation_context
        return build_conversation_context(chat_id, reply_message_id, reply_text, db)

    def test_conv_found_in_db(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = {"id": "conv-1"}
        db.get_reply_chain.return_value = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ]

        history, parent_id = self._build(100, 42, "answer", db)

        assert parent_id == "conv-1"
        assert "user: question" in history
        assert "assistant: answer" in history
        db.get_reply_chain.assert_called_once_with("conv-1", depth=20)

    def test_conv_not_found_bootstraps_from_reply_text(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = None

        history, parent_id = self._build(100, 42, "some bot reply", db)

        assert parent_id is None
        assert history == "assistant: some bot reply"
        db.get_reply_chain.assert_not_called()

    def test_empty_reply_text_when_not_found(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = None

        history, parent_id = self._build(100, 42, "", db)

        assert parent_id is None
        assert history == "assistant: "

    def test_long_chain_truncated(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = {"id": "conv-long"}
        chain = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
                 for i in range(12)]
        db.get_reply_chain.return_value = chain

        history, parent_id = self._build(100, 42, "answer", db)

        assert parent_id == "conv-long"
        assert "[4 предыдущих сообщений опущено]" in history
        # Last 8 messages should be present
        assert "msg-4" in history
        assert "msg-11" in history
        # First 4 should be omitted
        assert "msg-0" not in history.split("\n", 1)[1]
        assert "msg-3" not in history.split("\n", 1)[1]

    def test_short_chain_not_truncated(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = {"id": "conv-short"}
        chain = [{"role": "user", "content": "hi"},
                 {"role": "assistant", "content": "hello"}]
        db.get_reply_chain.return_value = chain

        history, parent_id = self._build(100, 42, "hello", db)

        assert "опущено" not in history
        assert "user: hi" in history
        assert "assistant: hello" in history

    def test_truncation_preserves_recent_messages(self):
        db = MagicMock()
        db.get_conversation_by_message_id.return_value = {"id": "conv-trunc"}
        chain = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg_{i:03d}"}
                 for i in range(15)]
        db.get_reply_chain.return_value = chain

        history, parent_id = self._build(100, 42, "answer", db)

        assert "[7 предыдущих сообщений опущено]" in history
        # Last 8 preserved
        for i in range(7, 15):
            assert f"msg_{i:03d}" in history
        # First 7 absent from message body
        lines_after_header = history.split("\n", 1)[1]
        for i in range(7):
            assert f"msg_{i:03d}" not in lines_after_header


# ===================================================================
#  generate_nl_reply — mock GeminiGateway and KnowledgeRetriever
# ===================================================================

class TestGenerateNlReply:

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_calls_gemini_and_returns_reply(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("prompt-text", "model-1", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "Hello back!"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = "core knowledge"
        mock_retriever.retrieve.return_value = "relevant info"

        result = generate_nl_reply("hi", "user: hi", mock_retriever, gemini=mock_gemini)

        assert result == "Hello back!"
        mock_gemini.call.assert_called_once_with("prompt-text", "model-1")

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_truncates_long_answer(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        long_text = "A" * 5000
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": long_text}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        result = generate_nl_reply("msg", "hist", mock_retriever, gemini=mock_gemini)

        assert len(result) == 4000

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_no_reply_key_returns_str_of_result(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"other_key": "value"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        result = generate_nl_reply("msg", "hist", mock_retriever, gemini=mock_gemini)

        assert "other_key" in result

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_knowledge_context_combines_core_and_relevant(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = "CORE"
        mock_retriever.retrieve.return_value = "RELEVANT"

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini)

        call_args = mock_compose_mod.conversation_reply.call_args
        knowledge_context = call_args[0][2]
        assert "CORE" in knowledge_context
        assert "RELEVANT" in knowledge_context

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_empty_core_uses_relevant_only(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = "RELEVANT"

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini)

        call_args = mock_compose_mod.conversation_reply.call_args
        knowledge_context = call_args[0][2]
        assert knowledge_context == "RELEVANT"

    @patch("backend.domain.services.conversation_service.GeminiGateway")
    @patch("backend.domain.services.conversation_service.compose_request")
    def test_default_gemini_created_when_none(self, mock_compose_mod, MockGemini):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        MockGemini.return_value.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        generate_nl_reply("q", "h", mock_retriever, gemini=None)

        MockGemini.assert_called_once()

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_environment_passed_to_compose_request(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini, environment="test env")

        call_kwargs = mock_compose_mod.conversation_reply.call_args
        assert call_kwargs[1]["environment_context"] == "test env"

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_allowed_domains_uses_multi_domain_retrieval(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_multi_domain_context.return_value = "multi-core"
        mock_retriever.retrieve.return_value = "multi-relevant"

        generate_nl_reply(
            "q", "h", mock_retriever, gemini=mock_gemini,
            allowed_domains=["editorial", "tech_support"],
        )

        mock_retriever.get_multi_domain_context.assert_called_once_with(["editorial", "tech_support"])
        mock_retriever.retrieve.assert_called_once_with("q", domains=["editorial", "tech_support"])
        mock_retriever.get_core.assert_not_called()

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_no_allowed_domains_uses_default_retrieval(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = "core"
        mock_retriever.retrieve.return_value = "relevant"

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini)

        mock_retriever.get_core.assert_called_once()
        mock_retriever.retrieve.assert_called_once_with("q")
        mock_retriever.get_multi_domain_context.assert_not_called()

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_user_context_passed_to_compose_request(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini, user_context="## Иван\nАвтор")

        call_kwargs = mock_compose_mod.conversation_reply.call_args
        assert call_kwargs[1]["user_context"] == "## Иван\nАвтор"

    @patch("backend.domain.services.conversation_service.compose_request")
    def test_user_context_defaults_to_empty(self, mock_compose_mod):
        from backend.domain.services.conversation_service import generate_nl_reply

        mock_compose_mod.conversation_reply.return_value = ("p", "m", ["reply"])
        mock_gemini = MagicMock()
        mock_gemini.call.return_value = {"reply": "ok"}
        mock_retriever = MagicMock()
        mock_retriever.get_core.return_value = ""
        mock_retriever.retrieve.return_value = ""

        generate_nl_reply("q", "h", mock_retriever, gemini=mock_gemini)

        call_kwargs = mock_compose_mod.conversation_reply.call_args
        assert call_kwargs[1]["user_context"] == ""
