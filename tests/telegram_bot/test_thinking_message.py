import asyncio
from unittest.mock import AsyncMock, patch

from telegram_bot.handler_utils import ThinkingMessage


def _make_message():
    msg = AsyncMock()
    status = AsyncMock()
    msg.answer = AsyncMock(return_value=status)
    return msg, status


class TestThinkingMessageSendsInitial:

    def test_sends_initial_message(self):
        msg, status = _make_message()

        async def run():
            async with ThinkingMessage(msg, "Думаю...") as thinking:
                msg.answer.assert_called_once_with("Думаю...")
                assert thinking._status_msg is status

        asyncio.run(run())


class TestThinkingMessageUpdate:

    def test_update_edits_status(self):
        msg, status = _make_message()

        async def run():
            async with ThinkingMessage(msg) as thinking:
                await thinking.update("Обрабатываю...")
                status.edit_text.assert_called_once_with("Обрабатываю...")

        asyncio.run(run())


class TestThinkingMessageFinish:

    def test_finish_edits_in_place(self):
        msg, status = _make_message()

        async def run():
            async with ThinkingMessage(msg) as thinking:
                result = await thinking.finish("Готово!", parse_mode="HTML")
                status.edit_text.assert_called_once_with("Готово!", parse_mode="HTML")
                assert result is status

        asyncio.run(run())


class TestThinkingMessageFinishLong:

    def test_finish_long_deletes_and_sends(self):
        msg, status = _make_message()

        async def run():
            with patch("telegram_bot.handler_utils._send_html", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = AsyncMock()
                async with ThinkingMessage(msg) as thinking:
                    await thinking.finish_long("Long reply text")
                    status.delete.assert_called_once()
                    mock_send.assert_called_once_with(msg, "Long reply text")

        asyncio.run(run())

    def test_finish_long_passes_kwargs(self):
        msg, status = _make_message()

        async def run():
            with patch("telegram_bot.handler_utils._send_html", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = AsyncMock()
                async with ThinkingMessage(msg) as thinking:
                    await thinking.finish_long("text", reply_to_message_id=42, reply_markup="kb")
                    mock_send.assert_called_once_with(msg, "text", reply_to_message_id=42, reply_markup="kb")

        asyncio.run(run())


class TestThinkingMessageExitNoop:

    def test_aexit_noop_on_exception(self):
        msg, status = _make_message()

        async def run():
            try:
                async with ThinkingMessage(msg) as thinking:
                    raise ValueError("boom")
            except ValueError:
                pass

        asyncio.run(run())
