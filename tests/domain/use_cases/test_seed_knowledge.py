"""Tests for seed_knowledge — chunking helpers and the seed_knowledge() entry point."""

from unittest.mock import MagicMock, patch, call


# ===================================================================
#  _chunk_tech_support
# ===================================================================

class TestChunkTechSupport:

    def _chunk(self, text):
        from backend.domain.use_cases.seed_knowledge import _chunk_tech_support
        return _chunk_tech_support(text)

    def test_core_section_before_first_bullet(self):
        text = "General rule line 1\nGeneral rule line 2\n- Bullet one"
        chunks = self._chunk(text)
        assert chunks[0] == ("core", "Техподдержка: общие правила", "General rule line 1\nGeneral rule line 2")

    def test_domain_bullets(self):
        text = "- First bullet\n- Second bullet"
        chunks = self._chunk(text)
        assert len(chunks) == 2
        assert chunks[0][0] == "domain"
        assert chunks[1][0] == "domain"

    def test_multiline_bullet(self):
        text = "- Main bullet\n  sub-line 1\n  sub-line 2\n- Next bullet"
        chunks = self._chunk(text)
        assert len(chunks) == 2
        assert chunks[0] == ("domain", "Main bullet", "- Main bullet\n  sub-line 1\n  sub-line 2")
        assert chunks[1] == ("domain", "Next bullet", "- Next bullet")

    def test_empty_input(self):
        # Empty string splits into [""] — no bullet found, so core_lines=[""] and
        # faq_start stays 0, producing a core chunk and an empty domain chunk.
        chunks = self._chunk("")
        assert chunks[0][0] == "core"
        assert chunks[0][2] == ""

    def test_no_core_section(self):
        text = "- Bullet only"
        chunks = self._chunk(text)
        assert len(chunks) == 1
        assert chunks[0][0] == "domain"

    def test_title_extraction(self):
        text = "- Как отменить подписку: объясни пользователю шаги"
        chunks = self._chunk(text)
        assert chunks[0][1] == "Как отменить подписку: объясни пользователю шаги"

    def test_core_plus_multiple_bullets(self):
        text = "Core instruction\n- Bullet A\n- Bullet B\n  detail\n- Bullet C"
        chunks = self._chunk(text)
        assert chunks[0][0] == "core"
        assert len(chunks) == 4  # 1 core + 3 domain


# ===================================================================
#  _chunk_payment_validation
# ===================================================================

class TestChunkPaymentValidation:

    def _chunk(self, text):
        from backend.domain.use_cases.seed_knowledge import _chunk_payment_validation
        return _chunk_payment_validation(text)

    def test_general_rules_section(self):
        text = "### Сбор платёжных данных\nОбщие правила"
        chunks = self._chunk(text)
        assert chunks[0][0] == "Сбор данных: общие правила"

    def test_samozanyatyy_section(self):
        text = "### Поля для самозанятый\nПоле 1"
        chunks = self._chunk(text)
        assert chunks[0][0] == "Поля: самозанятый"

    def test_ip_section(self):
        text = "### Поля для ИП\nПоле ИНН"
        chunks = self._chunk(text)
        assert chunks[0][0] == "Поля: ИП"

    def test_global_section(self):
        text = "### Fields for global users\nPassport"
        chunks = self._chunk(text)
        assert chunks[0][0] == "Поля: global"

    def test_unknown_heading(self):
        text = "### Другой раздел\nСодержание"
        chunks = self._chunk(text)
        assert chunks[0][0] == "Другой раздел"

    def test_empty_input(self):
        assert self._chunk("") == []

    def test_multiple_sections(self):
        text = "### Сбор платёжных данных\nОбщие\n### Поля для ИП\nИНН\n### Some global thing\nPassport"
        chunks = self._chunk(text)
        assert len(chunks) == 3
        assert chunks[0][0] == "Сбор данных: общие правила"
        assert chunks[1][0] == "Поля: ИП"
        assert chunks[2][0] == "Поля: global"

    def test_content_includes_full_section(self):
        text = "### Сбор платёжных данных\nLine 1\nLine 2"
        chunks = self._chunk(text)
        assert "Line 1" in chunks[0][1]
        assert "Line 2" in chunks[0][1]


# ===================================================================
#  seed_knowledge
# ===================================================================

# Fixed fake file contents for deterministic chunk counts
_FAKE_TECH_SUPPORT = "Core rules\n- Bullet 1\n- Bullet 2\n  detail\n- Bullet 3"
_FAKE_PAYMENT_VALIDATION = "### Сбор платёжных данных\nОбщие правила\n### Поля для ИП\nИНН"


def _fake_read(filename):
    return {
        "base.md": "Base content",
        "tech-support.md": _FAKE_TECH_SUPPORT,
        "email-inbox.md": "Email content",
        "support-triage.md": "Triage content",
        "payment-data-validation.md": _FAKE_PAYMENT_VALIDATION,
        "claude-code-context.md": "Code context",
    }[filename]


@patch("backend.domain.use_cases.seed_knowledge.EmbeddingGateway")
@patch("backend.domain.use_cases.seed_knowledge.DbGateway")
@patch("backend.domain.use_cases.seed_knowledge._read", side_effect=_fake_read)
class TestSeedKnowledge:

    def _run(self, mock_read, MockDb, MockEmbed):
        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()
        return MockDb.return_value, MockEmbed.return_value

    def test_happy_path_saves_entries(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 20  # enough for any count

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        assert mock_db.save_knowledge_entry.call_count > 0
        # Every call must have source="seed"
        for c in mock_db.save_knowledge_entry.call_args_list:
            assert c[1]["source"] == "seed"

    def test_idempotent_skips_when_entries_exist(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = [{"id": "existing"}]

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        mock_db.save_knowledge_entry.assert_not_called()
        MockEmbed.return_value.embed_texts.assert_not_called()

    def test_entry_count(self, mock_read, MockDb, MockEmbed):
        """Total entries = base(1) + tech_support(1 core + 3 bullets) + email(1) + triage(1) + payment(2 sections) + code(1) = 10."""
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 10

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        assert mock_db.save_knowledge_entry.call_count == 10

    def test_all_entries_have_source_seed(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 10

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        for c in mock_db.save_knowledge_entry.call_args_list:
            assert c[1]["source"] == "seed"

    def test_batch_embedding_called_with_all_texts(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 10

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        mock_embed.embed_texts.assert_called_once()
        texts = mock_embed.embed_texts.call_args[0][0]
        assert len(texts) == 10
        # Spot-check known content
        assert "Base content" in texts
        assert "Email content" in texts
        assert "Code context" in texts

    def test_correct_scopes(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 10

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        calls = mock_db.save_knowledge_entry.call_args_list
        scopes = [c[1]["scope"] for c in calls]
        assert scopes[0] == "identity"          # base.md
        assert all(s == "tech_support" for s in scopes[1:5])  # tech-support chunks
        assert scopes[5] == "email_inbox"        # email-inbox.md
        assert scopes[6] == "support_triage"     # support-triage.md
        assert all(s == "contractor" for s in scopes[7:9])  # payment-data-validation chunks
        assert scopes[9] == "code"               # claude-code-context.md

    def test_init_schema_called(self, mock_read, MockDb, MockEmbed):
        mock_db = MockDb.return_value
        mock_db.list_knowledge.return_value = []
        mock_db.save_knowledge_entry.return_value = "uuid"
        mock_embed = MockEmbed.return_value
        mock_embed.embed_texts.return_value = [[0.1]] * 10

        from backend.domain.use_cases.seed_knowledge import seed_knowledge
        seed_knowledge()

        mock_db.init_schema.assert_called_once()
