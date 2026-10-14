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
    msg11 = await client.get_messages(channel_id, ids=11)
    if msg11:
        print('Msg 11:', repr(msg11.message))
    msg12 = await client.get_messages(channel_id, ids=12)
    if msg12:
        print('Msg 12:', repr(msg12.message[:100]))
    await client.disconnect()

if __name__ == '__main__':
    asyncio.run(run())
