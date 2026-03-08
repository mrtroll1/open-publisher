"""One-time script to generate a Telethon StringSession.

Run locally:  python -m telegram_bot.gen_session

It will ask for your phone number and a confirmation code.
Copy the printed session string into TELEGRAM_SESSION in bot.env.
"""

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

from telegram_bot.config import TELEGRAM_API_HASH, TELEGRAM_API_ID


async def main():
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return

    client = TelegramClient(StringSession(), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()
    client.session.save()
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
