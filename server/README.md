# 🎥 Telegram FileStream Engine & Video Player (`server/`)

Direct streaming server and web video player bridging Telegram channels and MTProto file downloads to HTTP/HLS streaming with adaptive playback and P2P WebRTC mesh distribution.

---

## ⚡ Architecture & Features

- **Direct MTProto Streaming:** Streams video, audio, and large files directly from Telegram storage using Telethon without downloading the entire file first.
- **HTTP Range Requests:** Supports seeking in video/audio players (`206 Partial Content`).
- **HLS Dynamic Transcoding:** On-demand and pre-transcoding into multi-bitrate HLS streams (1080p, 720p, 480p, and Fast Direct Stream) using FFmpeg.
- **Embedded Web Video Player:**
  - Modern dark-themed video player with custom UI.
  - Multi-rendition quality selector.
  - P2P WebRTC Swarm integration (`p2p-media-loader-hlsjs`) to minimize server bandwidth when multiple viewers watch simultaneously.
  - Picture-in-Picture, speed controls, keyboard shortcuts, volume memory.
- **LRU Cache Engine:** Fast disk cache with LRU eviction policy (up to 20 GB) for instant segment replay and lower latency.
- **Cloudflare Tunnel Integration:** Reverse proxied via Cloudflare Tunnel at `https://stream.capt-th.work`.

---

## 📡 Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/watch/{chat_id}/{msg_id}` | HTML5 Web Video Player page |
| `GET` | `/stream/{chat_id}/{msg_id}` | Direct file streaming with HTTP Range support |
| `GET` | `/dl/{chat_id}/{msg_id}` | Direct file download with filename attachment header |
| `GET` | `/hls/{chat_id}/{msg_id}/master.m3u8` | HLS Master Playlist (adaptive bitrate selection) |
| `GET` | `/hls/{chat_id}/{msg_id}/{quality}/index.m3u8` | HLS Media Segment Playlist |
| `GET` | `/hls/{chat_id}/{msg_id}/{quality}/{seg_num}` | HLS TS/fMP4 video segment |
| `GET` | `/api/status/{chat_id}/{msg_id}` | File metadata, dimensions, transcoding status |
| `POST` | `/api/transcode/{chat_id}/{msg_id}` | Trigger background multi-bitrate transcoding |
| `GET` | `/health` | Server health check |

---

## ⚙️ Configuration (`.env`)

Copy `.env.example` to `.env` in this directory:

```env
API_ID=12345678
API_HASH=your_api_hash_here
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
PORT=8085
BASE_URL=https://stream.capt-th.work
SESSION_PATH=/home/ubuntu/tg-filestream/bot.session
```

> **Security Note:** Never commit `.env`, `*.session`, or `*.db` files to git.

---

## 🚀 Running on OCI (Production)

Service is managed by systemd:

```bash
# Check status
systemctl status tg-filestream.service

# Restart service
sudo systemctl restart tg-filestream.service

# View live logs
journalctl -u tg-filestream.service -f
```
