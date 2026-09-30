import os
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_PATH = os.environ.get("SESSION_PATH", str(Path(__file__).resolve().parent.parent / "bot.session"))

async def main():
    if not API_ID or not API_HASH:
        print("Please configure API_ID and API_HASH in server/.env")
        return
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    print(f"SUCCESS: Logged in as @{me.username} (ID: {me.id})")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
