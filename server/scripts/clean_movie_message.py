import os
import asyncio
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

async def run():
    client = TelegramClient('/home/ubuntu/tg-filestream/bot.session', API_ID, API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    channel_id = -1004381915212
    
    # 1. Edit caption of message 11 to just the clean file name
    clean_name = "ธี่หยด สมิงเขาขวาง.mp4"
    try:
        await client.edit_message(channel_id, 11, text=clean_name)
        print("Successfully edited message 11 caption to:", clean_name)
    except Exception as e:
        print("Error editing message 11:", e)
        
    # 2. Delete message 12 (the cluttered reply message)
    try:
        await client.delete_messages(channel_id, [12])
        print("Successfully deleted message 12 (cluttered bot reply)")
    except Exception as e:
        print("Error deleting message 12:", e)
        
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(run())
