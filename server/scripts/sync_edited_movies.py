import os
import asyncio
import sqlite3
import json
from telethon import TelegramClient
from telethon.tl.types import DocumentAttributeFilename, DocumentAttributeVideo, DocumentAttributeAudio

env = {}
with open('/home/ubuntu/tg-filestream/.env', 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

API_ID = int(env.get('API_ID', 0))
API_HASH = env.get('API_HASH', '')
BOT_TOKEN = env.get('BOT_TOKEN', '')
DB_PATH = '/home/ubuntu/tg-filestream/tg_stream.db'

def get_file_name_from_msg(msg):
    file_name = "video.mp4"
    if msg.document and msg.document.attributes:
        for attr in msg.document.attributes:
            if isinstance(attr, DocumentAttributeFilename) and attr.file_name:
                file_name = attr.file_name
    if getattr(msg, "message", None):
        try:
            meta = json.loads(msg.message)
            if isinstance(meta, dict) and "name" in meta:
                file_name = meta["name"]
        except Exception:
            clean_msg = msg.message.strip()
            if clean_msg and not clean_msg.startswith("{"):
                file_name = clean_msg
    return file_name

async def run():
    client = TelegramClient('/home/ubuntu/tg-filestream/bot.session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, msg_id, file_name FROM videos")
    rows = cur.fetchall()
    print("Current db rows:", rows)

    for chat_id, msg_id, old_name in rows:
        try:
            msg = await client.get_messages(chat_id, ids=msg_id)
            if msg:
                new_name = get_file_name_from_msg(msg)
                print(f"Message {chat_id}/{msg_id}: '{old_name}' -> '{new_name}' (caption: {repr(msg.message)})")
                cur.execute("UPDATE videos SET file_name = ? WHERE chat_id = ? AND msg_id = ?", (new_name, chat_id, msg_id))
        except Exception as e:
            print(f"Error checking {chat_id}/{msg_id}:", e)

    conn.commit()
    conn.close()
    await client.disconnect()
    print("Database sync complete!")

if __name__ == '__main__':
    asyncio.run(run())
