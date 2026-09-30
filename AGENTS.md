# 🤖 AGENTS.md — TGDrive & Telegram FileStream Guidelines

> **Purpose:** Machine-readable architecture rules, directory maps, and operational directives for AI coding agents working on `tg-drive`.

---

## 🗺️ System Overview & Architecture

`tg-drive` is a dual-subsystem repository providing Telegram Cloud Storage and High-Performance Media Streaming:

```text
[Browser / User]
       │
       ├──► [Frontend WebUI] (Cloudflare Pages: https://tgdrive-d7y.pages.dev)
       │      • Stack: React 19, TypeScript, GramJS, Vite, Tailwind CSS / DaisyUI
       │      • Role: Browser-direct Telegram cloud storage management
       │
       └──► [FileStream & Video Player] (OCI Cloud: https://stream.capt-th.work)
              • Stack: Python 3, Telethon, aiohttp, FFmpeg, HLS.js, P2P WebRTC Swarm
              • Port: 8085 (reverse-proxied via Cloudflare Tunnel)
              • Role: Video streaming (/watch, /stream), HLS adaptive streaming, P2P mesh
```

---

## 🏛️ Directory & Source Code Map

```text
tg-drive/
├── src/                        # Frontend Application (React 19 + TypeScript + GramJS)
│   ├── components/             # UI Components (Drive, FileList, Player, UploadModal, etc.)
│   ├── context/                # Telegram Client & Auth State (GramJS IndexedDB sessions)
│   └── App.tsx                 # Root layout & routing
├── public/                     # Static assets (Favicons, manifest, icons)
├── server/                     # Production Streaming Server (Deployed on OCI)
│   ├── stream_server.py        # Core aiohttp + Telethon streaming engine & embedded player
│   ├── requirements.txt        # Python dependencies (telethon, aiohttp, cryptg, etc.)
│   ├── .env.example            # Environment variables template
│   ├── tg-filestream.service   # Systemd service unit for OCI
│   └── README.md               # Backend API and operational documentation
├── AGENTS.md                   # This instruction file
└── README.md                   # Project overview & documentation
```

---

## 🚨 Critical Architectural Rules

1. **🔒 Security & Credentials Isolation:**
   - **NEVER** hardcode or commit `API_ID`, `API_HASH`, or Telegram `BOT_TOKEN`.
   - All credentials on the server are read strictly from environment variables or `/home/ubuntu/tg-filestream/.env`.
   - Never commit `*.session`, `*.db`, `cache/`, or `transcoded/` files.
2. **⚡ High-Performance Streaming:**
   - The streaming server runs directly on OCI (Port 8085) with an active Telethon MTProto client connection.
   - Video streaming supports HTTP 206 Partial Content (range requests) and adaptive HLS multi-bitrate transcoding.
   - P2P WebRTC Swarm (`p2p-media-loader`) is enabled in the embedded HTML5 player to offload bandwidth.
3. **🌐 Frontend Zero-Backend Direct MTProto:**
   - The frontend connects directly from the browser to Telegram servers via WebSockets using GramJS.
   - Client session data is persisted locally in IndexedDB; no credentials pass through any intermediate server.

---

## 🛠️ Standard Operating Procedures (SOPs)

### SOP-1: Updating Frontend
1. Make changes in `src/`.
2. Build and verify: `npm run build`.
3. Test locally: `npm run dev`.
4. Deploy to Cloudflare Pages: `npx wrangler pages deploy dist --project-name tgdrive`.

### SOP-2: Updating Server Backend
1. Edit files in `server/` (e.g. `server/stream_server.py`).
2. Deploy to OCI host `oci`:
   ```bash
   scp server/stream_server.py oci:/home/ubuntu/tg-filestream/stream_server.py
   ssh oci "sudo systemctl restart tg-filestream.service"
   ```
3. Verify service health:
   ```bash
   ssh oci "systemctl status tg-filestream.service --no-pager"
   curl -I https://stream.capt-th.work/health
   ```
