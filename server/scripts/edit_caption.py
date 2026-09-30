import os
import sys
import asyncio
from pathlib import Path
from telethon import TelegramClient

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_PATH = os.environ.get("SESSION_PATH", str(Path(__file__).resolve().parent.parent / "bot.session"))

async def main():
    if not API_ID or not API_HASH:
        print("Please configure API_ID and API_HASH in server/.env")
        return

    if len(sys.argv) < 3:
        print("Usage: python edit_caption.py <channel_id> <message_id> [new_text]")
        return

    channel_id = int(sys.argv[1])
    msg_id = int(sys.argv[2])
    new_text = sys.argv[3] if len(sys.argv) > 3 else "Updated caption"

    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()
    try:
        msg = await client.get_messages(channel_id, ids=msg_id)
        print("Original caption:", repr(msg.message))
        res = await client.edit_message(channel_id, msg_id, text=new_text)
        print("Edit success!")
    except Exception as e:
        print("Edit error:", type(e), e)
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
