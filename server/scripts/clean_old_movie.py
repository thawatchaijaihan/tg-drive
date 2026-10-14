import os
import asyncio
import sqlite3
from telethon import TelegramClient

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

async def run():
    client = TelegramClient('/home/ubuntu/tg-filestream/bot.session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    channel_id = -1004381915212

    msg2 = await client.get_messages(channel_id, ids=2)
    print("Telegram msg 2 exists?", bool(msg2 and msg2.media))

    # Also delete msg 2 row from db if it was superseded by msg 11
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, msg_id, file_name, file_size FROM videos WHERE msg_id = 2")
    row2 = cur.fetchall()
    print("DB row for msg 2:", row2)

    # Clean up old msg 2 from DB
    cur.execute("DELETE FROM videos WHERE msg_id = 2")
    conn.commit()
    conn.close()
    print("Deleted old superseded msg 2 from database.")

    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(run())
