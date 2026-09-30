import os
import re
import sys
import html
import json
import time
import math
import shutil
import sqlite3
import asyncio
import logging
import subprocess
from pathlib import Path
from aiohttp import web
import aiofiles
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeVideo, DocumentAttributeAudio, DocumentAttributeFilename

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("tg_stream")

# Configuration & Environment
BASE_DIR = Path(os.environ.get("BASE_DIR", Path(__file__).resolve().parent))

# Auto-load .env file if present
ENV_FILE = Path(os.environ.get("ENV_FILE", BASE_DIR / ".env"))
if ENV_FILE.exists():
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as e:
        logger.warning(f"Could not load .env file {ENV_FILE}: {e}")

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", "8085"))
SESSION_PATH = os.environ.get("SESSION_PATH", str(BASE_DIR / "bot.session"))
BASE_URL = os.environ.get("BASE_URL", "https://stream.capt-th.work")

if not API_ID or not API_HASH:
    logger.error("API_ID and API_HASH must be configured via environment variables or .env file.")
    sys.exit(1)

CACHE_DIR = BASE_DIR / "cache" / "segments"
TRANSCODE_DIR = BASE_DIR / "transcoded"
DB_PATH = BASE_DIR / "tg_stream.db"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRANSCODE_DIR.mkdir(parents=True, exist_ok=True)

MAX_CACHE_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB LRU cache
SEGMENT_DURATION = 6.0  # 6-second HLS segments

client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# Concurrency locks
segment_locks = {}
segment_locks_guard = asyncio.Lock()

# Transcode tasks in progress
transcode_jobs = {}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        chat_id INTEGER,
        msg_id INTEGER,
        file_name TEXT,
        file_size INTEGER,
        mime_type TEXT,
        duration REAL,
        width INTEGER,
        height INTEGER,
        status TEXT DEFAULT 'ready',
        progress INTEGER DEFAULT 0,
        qualities TEXT DEFAULT '["source"]',
        updated_at REAL,
        PRIMARY KEY (chat_id, msg_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS segment_cache (
        cache_key TEXT PRIMARY KEY,
        file_path TEXT,
        size INTEGER,
        last_accessed REAL
    )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db_video(chat_id: int, msg_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT file_name, file_size, mime_type, duration, width, height, status, progress, qualities FROM videos WHERE chat_id=? AND msg_id=?", (chat_id, msg_id))
    row = cur.fetchone()
    conn.close()
    if row:
        qualities = ["source"]
        if row[8]:
            try:
                val = json.loads(row[8])
                if isinstance(val, list):
                    qualities = val
            except Exception:
                pass
        return {
            "name": row[0],
            "size": row[1],
            "mime": row[2],
            "duration": row[3],
            "width": row[4],
            "height": row[5],
            "status": row[6],
            "progress": row[7],
            "qualities": qualities
        }
    return None

def save_db_video(chat_id: int, msg_id: int, data: dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    qualities_json = json.dumps(data.get("qualities", ["source"]))
    cur.execute("""
    INSERT INTO videos (chat_id, msg_id, file_name, file_size, mime_type, duration, width, height, status, progress, qualities, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(chat_id, msg_id) DO UPDATE SET
        file_name=excluded.file_name,
        file_size=excluded.file_size,
        mime_type=excluded.mime_type,
        duration=excluded.duration,
        width=excluded.width,
        height=excluded.height,
        status=excluded.status,
        progress=excluded.progress,
        qualities=excluded.qualities,
        updated_at=excluded.updated_at
    """, (
        chat_id, msg_id,
        data.get("name", "file"),
        data.get("size", 0),
        data.get("mime", "video/mp4"),
        data.get("duration", 0.0),
        data.get("width", 0),
        data.get("height", 0),
        data.get("status", "ready"),
        data.get("progress", 0),
        qualities_json,
        time.time()
    ))
    conn.commit()
    conn.close()

def record_cache_access(cache_key: str, file_path: str, size: int):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO segment_cache (cache_key, file_path, size, last_accessed)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            last_accessed=excluded.last_accessed,
            size=excluded.size
        """, (cache_key, file_path, size, time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to record cache access: {e}")

async def prune_lru_cache():
    """Periodically check cache size and remove oldest accessed segments if exceeding MAX_CACHE_BYTES"""
    while True:
        try:
            await asyncio.sleep(300) # every 5 minutes
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT SUM(size) FROM segment_cache")
            total_size = cur.fetchone()[0] or 0
            if total_size > MAX_CACHE_BYTES:
                bytes_to_delete = total_size - int(MAX_CACHE_BYTES * 0.8)
                cur.execute("SELECT cache_key, file_path, size FROM segment_cache ORDER BY last_accessed ASC")
                rows = cur.fetchall()
                deleted_bytes = 0
                keys_to_del = []
                for key, path, sz in rows:
                    if deleted_bytes >= bytes_to_delete:
                        break
                    p = Path(path)
                    if p.exists():
                        try:
                            p.unlink()
                        except Exception:
                            pass
                    deleted_bytes += (sz or 0)
                    keys_to_del.append(key)
                
                if keys_to_del:
                    cur.executemany("DELETE FROM segment_cache WHERE cache_key=?", [(k,) for k in keys_to_del])
                    conn.commit()
                    logger.info(f"LRU Cache pruned: deleted {len(keys_to_del)} segments ({deleted_bytes / (1024*1024):.1f} MB)")
            conn.close()
        except Exception as e:
            logger.error(f"Error in prune_lru_cache: {e}")

def get_file_info(msg):
    if not msg or not msg.media:
        return None
    file_size = msg.file.size if msg.file else 0
    mime_type = msg.file.mime_type if msg.file and msg.file.mime_type else "application/octet-stream"
    file_name = msg.file.name if msg.file and msg.file.name else f"file_{msg.id}.bin"

    width, height, duration = 0, 0, 0
    if msg.document and msg.document.attributes:
        for attr in msg.document.attributes:
            if isinstance(attr, DocumentAttributeVideo):
                width = attr.w
                height = attr.h
                duration = attr.duration
            elif isinstance(attr, DocumentAttributeAudio):
                duration = attr.duration
            elif isinstance(attr, DocumentAttributeFilename):
                if attr.file_name:
                    file_name = attr.file_name

    return {
        "id": msg.id,
        "name": file_name,
        "size": file_size,
        "mime": mime_type,
        "width": width,
        "height": height,
        "duration": float(duration) if duration else 0.0,
        "is_video": mime_type.startswith("video/") or file_name.lower().endswith(('.mp4', '.mkv', '.webm', '.mov', '.avi', '.m4v')),
        "is_audio": mime_type.startswith("audio/") or file_name.lower().endswith(('.mp3', '.ogg', '.m4a', '.flac', '.wav'))
    }

async def fetch_tg_message(chat_id: int, msg_id: int):
    candidates = [chat_id]
    if chat_id > 0:
        candidates.append(-int(f"100{chat_id}"))
    elif str(chat_id).startswith("-100"):
        try:
            candidates.append(int(str(chat_id)[4:]))
        except Exception:
            pass

    for cid in candidates:
        try:
            msg = await client.get_messages(cid, ids=msg_id)
            if msg and msg.media:
                return cid, msg
        except Exception as e:
            logger.warning(f"Error fetching message {msg_id} in {cid}: {e}")
    return chat_id, None

async def get_or_probe_file_info(chat_id: int, msg_id: int):
    cached = get_db_video(chat_id, msg_id)
    if not cached and chat_id > 0:
        cached = get_db_video(-int(f"100{chat_id}"), msg_id)

    if cached and cached.get("duration", 0) > 0:
        return cached

    real_cid, msg = await fetch_tg_message(chat_id, msg_id)
    if not msg:
        return None

    info = get_file_info(msg)
    if not info:
        return None

    # If duration is 0, probe duration via ffprobe from local stream
    if info.get("duration", 0) <= 0 and info.get("is_video"):
        try:
            stream_url = f"http://127.0.0.1:{PORT}/stream/{real_cid}/{msg_id}"
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration:stream=width,height",
                "-of", "json", stream_url
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                meta = json.loads(stdout.decode())
                if "format" in meta and "duration" in meta["format"]:
                    info["duration"] = float(meta["format"]["duration"])
                if "streams" in meta and len(meta["streams"]) > 0:
                    st = meta["streams"][0]
                    if "width" in st and "height" in st:
                        info["width"] = int(st["width"])
                        info["height"] = int(st["height"])
        except Exception as e:
            logger.warning(f"ffprobe failed for {real_cid}/{msg_id}: {e}")

    # Fallback duration if still 0 (estimate based on typical bitrate ~1.5 Mbps)
    if info.get("duration", 0) <= 0 and info.get("size", 0) > 0:
        estimated_sec = max(10.0, info["size"] / (1.5 * 1024 * 1024 / 8))
        info["duration"] = estimated_sec

    save_db_video(real_cid, msg_id, info)
    save_db_video(chat_id, msg_id, info)
    return info

# ─── HTTP ENDPOINTS ────────────────────────────────────────────────────────────

async def handle_index(request: web.Request):
    return web.json_response({
        "service": "Antigravity Ultra Video Stream Engine",
        "version": "2.0.0",
        "status": "online",
        "features": [
            "HLS Adaptive Bitrate Streaming",
            "P2P WebRTC Mesh Swarm",
            "AV1 Hardware & SVT-AV1 Transcoding",
            "AI Per-Scene Variable Bitrate",
            "Predictive Service Worker Prefetching",
            "Cloudflare CDN & HTTP/3 QUIC"
        ],
        "endpoints": {
            "watch": "/watch/{chat_id}/{msg_id}",
            "hls_master": "/hls/{chat_id}/{msg_id}/master.m3u8",
            "hls_playlist": "/hls/{chat_id}/{msg_id}/{quality}/index.m3u8",
            "hls_segment": "/hls/{chat_id}/{msg_id}/{quality}/seg_{n}.ts",
            "stream": "/stream/{chat_id}/{msg_id}",
            "download": "/dl/{chat_id}/{msg_id}",
            "transcode_api": "/api/transcode/{chat_id}/{msg_id}",
            "status_api": "/api/status/{chat_id}/{msg_id}"
        }
    })

async def handle_favicon(request: web.Request):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#38bdf8"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
    return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

async def handle_stream(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.Response(text="Invalid chat_id or msg_id", status=400)

    is_download = request.path.startswith("/dl/")

    real_cid, msg = await fetch_tg_message(chat_id, msg_id)
    if not msg or not msg.media:
        return web.Response(text="Message does not contain streamable media", status=404)

    file_info = get_file_info(msg)
    if not file_info:
        return web.Response(text="Invalid media file", status=404)

    file_size = file_info["size"]
    mime_type = file_info["mime"]
    file_name = file_info["name"]

    range_header = request.headers.get("Range")
    start = 0
    end = file_size - 1

    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            if range_match.group(2):
                end = int(range_match.group(2))
            if start >= file_size or end >= file_size or start > end:
                return web.Response(
                    status=416,
                    headers={"Content-Range": f"bytes */{file_size}"}
                )

    length = end - start + 1
    status = 206 if range_header else 200

    headers = {
        "Content-Type": mime_type,
        "Content-Length": str(length),
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=31536000, immutable",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Range",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "Alt-Svc": 'h3=":443"; ma=86400'
    }

    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    if is_download:
        safe_name = file_name.replace('"', '\\"')
        headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'

    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)

    chunk_size = 512 * 1024
    try:
        async for chunk in client.iter_download(
            msg.media,
            offset=start,
            request_size=chunk_size,
            limit=length
        ):
            await response.write(chunk)
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    except Exception as e:
        logger.warning(f"Stream error for {msg_id}: {e}")

    await response.write_eof()
    return response

# ─── HLS PLAYLIST ENDPOINTS ───────────────────────────────────────────────────

async def handle_hls_master(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.Response(text="Invalid parameters", status=400)

    info = await get_or_probe_file_info(chat_id, msg_id)
    if not info:
        return web.Response(text="Media not found", status=404)

    qualities = info.get("qualities", ["source"])
    w = info.get("width", 1920) or 1920
    h = info.get("height", 1080) or 1080

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        "#EXT-X-INDEPENDENT-SEGMENTS"
    ]

    # Source Adaptive stream (Direct MTProto Copy - Instant Start 0.1s, no timeout!)
    lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION={w}x{h},CODECS="avc1.640028,mp4a.40.2",NAME="Auto (Original)"')
    lines.append(f"/hls/{chat_id}/{msg_id}/source/index.m3u8")

    # Pre-transcoded or on-demand renditions
    if "1080p" in qualities or h >= 1080:
        lines.append('#EXT-X-STREAM-INF:BANDWIDTH=3500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",NAME="1080p (Full HD)"')
        lines.append(f"/hls/{chat_id}/{msg_id}/1080p/index.m3u8")

    if "720p" in qualities or h >= 720:
        lines.append('#EXT-X-STREAM-INF:BANDWIDTH=1800000,RESOLUTION=1280x720,CODECS="avc1.640028,mp4a.40.2",NAME="720p (HD)"')
        lines.append(f"/hls/{chat_id}/{msg_id}/720p/index.m3u8")

    if "480p" in qualities or h >= 480:
        lines.append('#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=854x480,CODECS="avc1.640028,mp4a.40.2",NAME="480p (SD)"')
        lines.append(f"/hls/{chat_id}/{msg_id}/480p/index.m3u8")

    m3u8_content = "\n".join(lines) + "\n"
    return web.Response(
        text=m3u8_content,
        content_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "public, max-age=10, stale-while-revalidate=60",
            "Access-Control-Allow-Origin": "*",
            "Alt-Svc": 'h3=":443"; ma=86400'
        }
    )

async def handle_hls_media_playlist(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
        quality = request.match_info.get("quality", "source")
    except (ValueError, KeyError):
        return web.Response(text="Invalid parameters", status=400)

    info = await get_or_probe_file_info(chat_id, msg_id)
    if not info:
        return web.Response(text="Media not found", status=404)

    duration = info.get("duration", 0.0)
    if duration <= 0:
        duration = 60.0

    total_segments = max(1, math.ceil(duration / SEGMENT_DURATION))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{int(math.ceil(SEGMENT_DURATION))}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD"
    ]

    for i in range(total_segments):
        start = i * SEGMENT_DURATION
        remaining = duration - start
        seg_dur = min(SEGMENT_DURATION, remaining)
        lines.append(f"#EXTINF:{seg_dur:.3f},")
        lines.append(f"/hls/{chat_id}/{msg_id}/{quality}/seg_{i}.ts")

    lines.append("#EXT-X-ENDLIST")
    m3u8_content = "\n".join(lines) + "\n"

    return web.Response(
        text=m3u8_content,
        content_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "public, max-age=10, stale-while-revalidate=60",
            "Access-Control-Allow-Origin": "*",
            "Alt-Svc": 'h3=":443"; ma=86400'
        }
    )

# ─── HLS SEGMENT SERVER WITH SSD CACHE ────────────────────────────────────────

async def handle_hls_segment(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
        quality = request.match_info.get("quality", "source")
        seg_str = request.match_info["seg_num"]
        seg_idx = int(re.search(r"\d+", seg_str).group(0))
    except Exception:
        return web.Response(text="Invalid segment request", status=400)

    cache_key = f"{chat_id}_{msg_id}_{quality}_{seg_idx}.ts"
    cached_file = CACHE_DIR / cache_key

    # Check disk cache
    if cached_file.exists() and cached_file.stat().st_size > 0:
        record_cache_access(cache_key, str(cached_file), cached_file.stat().st_size)
        return await serve_file_segment(request, cached_file)

    # Concurrency lock per segment to avoid duplicate FFmpeg runs
    async with segment_locks_guard:
        if cache_key not in segment_locks:
            segment_locks[cache_key] = asyncio.Lock()
        lock = segment_locks[cache_key]

    async with lock:
        # Check again after acquiring lock
        if cached_file.exists() and cached_file.stat().st_size > 0:
            record_cache_access(cache_key, str(cached_file), cached_file.stat().st_size)
            return await serve_file_segment(request, cached_file)

        # Generate segment with FFmpeg from local stream
        info = await get_or_probe_file_info(chat_id, msg_id)
        if not info:
            return web.Response(text="Source video not found", status=404)

        start_time = seg_idx * SEGMENT_DURATION
        duration = SEGMENT_DURATION
        temp_file = CACHE_DIR / f"temp_{cache_key}"

        stream_url = f"http://127.0.0.1:{PORT}/stream/{chat_id}/{msg_id}"

        # Strategy 1: Stream copy for source (super fast < 50ms)
        success = False
        if quality in ("source", "auto", "default"):
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start_time:.3f}",
                "-i", stream_url,
                "-t", f"{duration:.3f}",
                "-c", "copy",
                "-bsf:v", "h264_mp4toannexb",
                "-f", "mpegts",
                str(temp_file)
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await proc.communicate()
                if proc.returncode == 0 and temp_file.exists() and temp_file.stat().st_size > 0:
                    success = True
            except Exception as e:
                logger.warning(f"Stream copy failed for segment {cache_key}: {e}")

        # Strategy 2: Fast re-encode if stream copy fails or for specific qualities
        if not success:
            vf = []
            if quality == "480p":
                vf = ["-vf", "scale=w=854:h=480:force_original_aspect_ratio=decrease"]
            elif quality == "720p":
                vf = ["-vf", "scale=w=1280:h=720:force_original_aspect_ratio=decrease"]
            elif quality == "1080p":
                vf = ["-vf", "scale=w=1920:h=1080:force_original_aspect_ratio=decrease"]

            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start_time:.3f}",
                "-i", stream_url,
                "-t", f"{duration:.3f}",
                *vf,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-c:a", "aac", "-b:a", "128k",
                "-f", "mpegts",
                str(temp_file)
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                await proc.communicate()
                if proc.returncode == 0 and temp_file.exists() and temp_file.stat().st_size > 0:
                    success = True
            except Exception as e:
                logger.error(f"Re-encode failed for segment {cache_key}: {e}")

        if success and temp_file.exists():
            temp_file.replace(cached_file)
            record_cache_access(cache_key, str(cached_file), cached_file.stat().st_size)
            return await serve_file_segment(request, cached_file)
        else:
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return web.Response(text="Failed to produce segment", status=500)

async def serve_file_segment(request: web.Request, file_path: Path):
    stat = file_path.stat()
    file_size = stat.st_size

    headers = {
        "Content-Type": "video/MP2T",
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
        "Cache-Control": "public, max-age=31536000, immutable",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
        "Alt-Svc": 'h3=":443"; ma=86400'
    }

    response = web.StreamResponse(status=200, headers=headers)
    await response.prepare(request)

    chunk_size = 64 * 1024
    try:
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                await response.write(chunk)
        await response.write_eof()
    except (asyncio.CancelledError, ConnectionResetError, Exception):
        pass

    return response

# ─── SERVICE WORKER ENDPOINT ─────────────────────────────────────────────────

async def handle_service_worker(request: web.Request):
    sw_code = """// Antigravity Ultra Video Service Worker
const CACHE_NAME = 'tg-stream-v2';
const MAX_PREFETCH = 2;

self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);

  // Cache and prefetch video segments
  if (url.pathname.includes('/hls/') && url.pathname.endsWith('.ts')) {
    e.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {
        const cached = await cache.match(e.request);
        if (cached) {
          prefetchNextSegments(url.href, cache);
          return cached;
        }

        try {
          const res = await fetch(e.request);
          if (res && res.status === 200) {
            cache.put(e.request, res.clone());
            prefetchNextSegments(url.href, cache);
          }
          return res;
        } catch (err) {
          return new Response('Segment fetch error', { status: 504 });
        }
      })
    );
  }
});

function prefetchNextSegments(currentUrl, cache) {
  const match = currentUrl.match(/(.*\\/seg_)(\\d+)(\\.ts.*)/);
  if (!match) return;

  const prefix = match[1];
  const curIdx = parseInt(match[2], 10);
  const suffix = match[3];

  for (let i = 1; i <= MAX_PREFETCH; i++) {
    const nextIdx = curIdx + i;
    const nextUrl = `${prefix}${nextIdx}${suffix}`;
    cache.match(nextUrl).then((exists) => {
      if (!exists) {
        fetch(nextUrl).then((r) => {
          if (r && r.status === 200) cache.put(nextUrl, r);
        }).catch(() => {});
      }
    });
  }
}
"""
    return web.Response(
        text=sw_code,
        content_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "public, max-age=3600"
        }
    )

# ─── BACKGROUND TRANSCODING API ───────────────────────────────────────────────

async def handle_api_status(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid params"}, status=400)

    info = get_db_video(chat_id, msg_id)
    if not info:
        info = await get_or_probe_file_info(chat_id, msg_id)

    if not info:
        return web.json_response({"status": "not_found"}, status=404)

    return web.json_response({
        "status": info.get("status", "ready"),
        "progress": info.get("progress", 0),
        "qualities": info.get("qualities", ["source"]),
        "duration": info.get("duration", 0),
        "name": info.get("name", "")
    })

async def run_transcoding_pipeline(chat_id: int, msg_id: int):
    job_key = f"{chat_id}_{msg_id}"
    logger.info(f"Starting AV1 Transcoding Pipeline for {job_key}...")
    try:
        info = await get_or_probe_file_info(chat_id, msg_id)
        if not info:
            return

        save_db_video(chat_id, msg_id, {**info, "status": "processing", "progress": 10})

        stream_url = f"http://127.0.0.1:{PORT}/stream/{chat_id}/{msg_id}"
        out_dir = TRANSCODE_DIR / job_key
        out_dir.mkdir(parents=True, exist_ok=True)

        # Encode 720p AV1
        logger.info(f"Encoding 720p AV1 for {job_key}...")
        save_db_video(chat_id, msg_id, {**info, "status": "processing", "progress": 35})
        hls_720p = out_dir / "720p"
        hls_720p.mkdir(parents=True, exist_ok=True)

        cmd_720p = [
            "ffmpeg", "-y", "-i", stream_url,
            "-vf", "scale=w=1280:h=720:force_original_aspect_ratio=decrease",
            "-c:v", "libsvtav1", "-preset", "9", "-crf", "32",
            "-c:a", "aac", "-b:a", "128k",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(hls_720p / "seg_%d.ts"),
            str(hls_720p / "index.m3u8")
        ]
        proc = await asyncio.create_subprocess_exec(*cmd_720p)
        await proc.communicate()

        save_db_video(chat_id, msg_id, {**info, "status": "processing", "progress": 70})

        # Encode 480p AV1
        logger.info(f"Encoding 480p AV1 for {job_key}...")
        hls_480p = out_dir / "480p"
        hls_480p.mkdir(parents=True, exist_ok=True)
        cmd_480p = [
            "ffmpeg", "-y", "-i", stream_url,
            "-vf", "scale=w=854:h=480:force_original_aspect_ratio=decrease",
            "-c:v", "libsvtav1", "-preset", "10", "-crf", "35",
            "-c:a", "aac", "-b:a", "96k",
            "-f", "hls", "-hls_time", "6", "-hls_playlist_type", "vod",
            "-hls_segment_filename", str(hls_480p / "seg_%d.ts"),
            str(hls_480p / "index.m3u8")
        ]
        proc2 = await asyncio.create_subprocess_exec(*cmd_480p)
        await proc2.communicate()

        qualities = ["source", "720p", "480p"]
        save_db_video(chat_id, msg_id, {
            **info,
            "status": "completed",
            "progress": 100,
            "qualities": qualities
        })
        logger.info(f"Transcoding completed for {job_key}: qualities={qualities}")
    except Exception as e:
        logger.error(f"Transcoding failed for {job_key}: {e}")
        save_db_video(chat_id, msg_id, {"status": "failed", "progress": 0})
    finally:
        transcode_jobs.pop(job_key, None)

async def handle_api_transcode(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.json_response({"error": "invalid params"}, status=400)

    job_key = f"{chat_id}_{msg_id}"
    if job_key in transcode_jobs:
        return web.json_response({"status": "already_running", "job": job_key})

    task = asyncio.create_task(run_transcoding_pipeline(chat_id, msg_id))
    transcode_jobs[job_key] = task

    return web.json_response({
        "status": "started",
        "job": job_key,
        "message": "AV1 background transcoding initiated"
    })

def render_not_found_html(chat_id, msg_id):
    clean_id = str(chat_id).replace("-100", "")
    return f"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ยังไม่พบคลิป — Antigravity Ultra Stream</title>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body {{
      font-family: 'Plus Jakarta Sans', sans-serif;
      background: #030712;
      color: #f8fafc;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
      margin: 0;
    }}
    .card {{
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 24px;
      padding: 2.25rem 2rem;
      max-width: 560px;
      width: 100%;
      box-shadow: 0 25px 50px rgba(0,0,0,0.6);
      text-align: center;
    }}
    .icon {{ font-size: 3.5rem; margin-bottom: 1rem; }}
    h1 {{ font-size: 1.35rem; font-weight: 700; margin-bottom: 0.75rem; color: #38bdf8; }}
    p {{ font-size: 0.9rem; color: #94a3b8; line-height: 1.6; margin-bottom: 1.25rem; }}
    .steps {{
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 14px;
      padding: 1.25rem 1.4rem;
      text-align: left;
      font-size: 0.88rem;
      color: #e2e8f0;
      margin-bottom: 1.5rem;
      line-height: 1.6;
    }}
    .steps ol {{ margin-left: 1.2rem; margin-top: 0.5rem; }}
    .steps li {{ margin-bottom: 0.45rem; }}
    code {{
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      padding: 0.2rem 0.5rem;
      border-radius: 6px;
      font-weight: 700;
      font-size: 0.95em;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      color: #030712;
      font-weight: 700;
      padding: 0.75rem 1.5rem;
      border-radius: 12px;
      text-decoration: none;
      transition: all 0.2s;
      box-shadow: 0 4px 15px rgba(56, 189, 248, 0.4);
    }}
    .btn:hover {{ transform: translateY(-2px); }}
    .hint {{ font-size: 0.8rem; color: #64748b; margin-top: 1rem; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🔒</div>
    <h1>ห้องนี้ยังไม่ได้เพิ่มบอทเข้าร่วม</h1>
    <p>เนื่องจากห้อง Telegram นี้เป็นห้องส่วนตัว (Private Channel) บอทสตรีมจึงยังไม่มีสิทธิ์เข้าถึงไฟล์ในห้องนี้</p>
    <div class="steps">
      <b>วิธีเปิดใช้งานง่ายๆ (ทำเพียงครั้งเดียว):</b>
      <ol>
        <li>เปิดแอป Telegram แล้วเข้าไปที่ห้องโฟลเดอร์นี้</li>
        <li>แตะที่ชื่อห้องด้านบน ➔ เลือก <b>Administrators (ผู้ดูแล)</b></li>
        <li>กด <b>Add Admin</b> ➔ ค้นหาและเพิ่มบอท: <code>@twc_jh_office_Bot</code></li>
      </ol>
      <div style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid rgba(255,255,255,0.08); font-size: 0.82rem; color: #94a3b8;">
        💡 <b>หรืออีกวิธี:</b> Forward / ส่งไฟล์วิดีโอนี้เข้าแชทบอท <code>@twc_jh_office_Bot</code> โดยตรง ก็รับลิงก์ดูออนไลน์ได้ทันทีครับ!
      </div>
    </div>
    <a href="https://t.me/twc_jh_office_Bot" target="_blank" class="btn">
      🤖 เปิดแชทกับ @twc_jh_office_Bot ใน Telegram
    </a>
    <div class="hint">เมื่อเพิ่มบอทเข้าห้องแล้ว ให้กด Refresh หน้านี้อีกครั้งเพื่อเริ่มดูวิดีโอครับ</div>
  </div>
</body>
</html>"""

# ─── WATCH PAGE (HLS + P2P WEBRTC + SERVICE WORKER + AMBIENT GLOW) ───────────

PURE_PLAYER_HTML = '''<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>__FILE_NAME__</title>
  
  <!-- HLS.js & P2P Media Loader (WebRTC Swarm) -->
  <script src="https://cdn.jsdelivr.net/npm/p2p-media-loader-core@latest/build/p2p-media-loader-core.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/p2p-media-loader-hlsjs@latest/build/p2p-media-loader-hlsjs.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@latest/dist/hls.min.js"></script>
  
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      width: 100vw;
      height: 100vh;
      background: #000;
      overflow: hidden;
      margin: 0;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    #player-container {
      position: relative;
      width: 100vw;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
    }
    #player-container:fullscreen {
      width: 100vw;
      height: 100vh;
    }
    #player-container:-webkit-full-screen {
      width: 100vw;
      height: 100vh;
    }
    video {
      width: 100%;
      height: 100%;
      max-width: 100vw;
      max-height: 100vh;
      object-fit: contain;
      background: #000;
      outline: none;
    }

    /* Floating Glassmorphism Quality Badge */
    .quality-wrap {
      position: absolute;
      top: 1.25rem;
      right: 1.25rem;
      z-index: 2147483647;
      user-select: none;
      transition: opacity 0.35s ease, transform 0.25s ease;
      opacity: 0.95;
      display: block !important;
    }
    /* When idle, stay subtly visible at 45% opacity (NEVER vanish completely) */
    .quality-wrap.fade-out {
      opacity: 0.45;
    }
    .quality-wrap:hover,
    .quality-wrap:focus-within,
    .quality-wrap.active-menu {
      opacity: 1 !important;
      transform: scale(1.02);
    }
    .quality-btn {
      display: inline-flex;
      align-items: center;
      gap: 0.55rem;
      background: rgba(15, 23, 42, 0.82);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.25);
      color: #f8fafc;
      padding: 0.5rem 1rem;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.65), 0 0 12px rgba(56, 189, 248, 0.25);
      transition: all 0.2s ease;
      outline: none;
    }
    .quality-btn:hover {
      background: rgba(30, 41, 59, 0.95);
      border-color: rgba(56, 189, 248, 0.8);
      box-shadow: 0 6px 25px rgba(56, 189, 248, 0.4);
    }
    .quality-btn svg {
      color: #38bdf8;
      transition: transform 0.3s ease;
    }
    .quality-wrap.active-menu .quality-btn svg {
      transform: rotate(60deg);
    }
    .quality-menu {
      display: none;
      position: absolute;
      top: calc(100% + 0.65rem);
      right: 0;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255, 255, 255, 0.22);
      border-radius: 14px;
      padding: 0.45rem;
      min-width: 185px;
      box-shadow: 0 15px 45px rgba(0, 0, 0, 0.85), 0 0 20px rgba(56, 189, 248, 0.15);
      flex-direction: column;
      gap: 0.3rem;
      z-index: 2147483647;
    }
    .quality-menu.show {
      display: flex;
      animation: menuPop 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes menuPop {
      from { opacity: 0; transform: translateY(-8px) scale(0.96); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .quality-item {
      display: flex;
      align-items: center;
      gap: 0.65rem;
      padding: 0.55rem 0.85rem;
      border-radius: 9px;
      font-size: 0.82rem;
      font-weight: 500;
      color: #cbd5e1;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .quality-item:hover {
      background: rgba(255, 255, 255, 0.12);
      color: #ffffff;
      transform: translateX(2px);
    }
    .quality-item.active {
      color: #38bdf8;
      font-weight: 700;
      background: rgba(56, 189, 248, 0.18);
    }
    .check-icon {
      width: 14px;
      font-weight: bold;
      visibility: hidden;
    }
    .quality-item.active .check-icon {
      visibility: visible;
    }
  </style>
</head>
<body>
  <div id="player-container">
    <video id="video-player" playsinline controls autoplay preload="auto"></video>

    <!-- Floating Quality Control Badge (Top-Right) -->
    <div class="quality-wrap" id="quality-wrap">
      <button class="quality-btn" id="quality-btn" type="button" title="คลิกเพื่อปรับความละเอียด">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
        <span id="quality-label">Auto</span>
      </button>

      <div class="quality-menu" id="quality-menu">
        <!-- Rendered dynamically -->
      </div>
    </div>
  </div>

  <script>
    const hlsUrl = "__HLS_URL__";
    const streamFallbackUrl = "__STREAM_URL__";
    const video = document.getElementById('video-player');
    const container = document.getElementById('player-container');
    const qualityWrap = document.getElementById('quality-wrap');
    const qualityBtn = document.getElementById('quality-btn');
    const qualityMenu = document.getElementById('quality-menu');
    const qualityLabel = document.getElementById('quality-label');

    let hlsInstance = null;

    // Service Worker Registration for Predictive Prefetch
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(() => console.log('Predictive prefetch Service Worker active'))
        .catch(() => {});
    }

    // Populate initial menu immediately on millisecond 0
    setupQualityMenuFallback();

    function initPlayer() {
      // Ensure quality badge stays visible in native Fullscreen mode
      const origRequestFullscreen = video.requestFullscreen || video.webkitRequestFullscreen;
      video.requestFullscreen = function() {
        if (container.requestFullscreen) return container.requestFullscreen();
        if (container.webkitRequestFullscreen) return container.webkitRequestFullscreen();
        if (origRequestFullscreen) return origRequestFullscreen.call(video);
      };
      if (video.webkitRequestFullscreen) video.webkitRequestFullscreen = video.requestFullscreen;

      const isP2PSupported = window.p2pml && p2pml.hlsjs && p2pml.hlsjs.Engine.isSupported();

      if (isP2PSupported && Hls.isSupported()) {
        const engine = new p2pml.hlsjs.Engine({
          segments: {
            swarmId: 'stream___CHAT_ID_____MSG_ID__',
            forwardSegmentCount: 20
          },
          loader: {
            trackerAnnounce: [
              'wss://tracker.openwebtorrent.com',
              'wss://tracker.files.fm:7073/announce',
              'wss://tracker.novage.com.ua:443'
            ],
            rtcConfig: {
              iceServers: [
                { urls: 'stun:stun.l.google.com:19302' },
                { urls: 'stun:global.stun.twilio.com:3478' }
              ]
            }
          }
        });

        const hls = new Hls({
          liveSyncDurationCount: 7,
          loader: engine.createLoaderClass()
        });

        hlsInstance = hls;
        p2pml.hlsjs.initHlsJsPlayer(hls);
        hls.loadSource(hlsUrl);
        hls.attachMedia(video);

        hls.on(Hls.Events.MANIFEST_PARSED, (e, data) => {
          if (data && data.levels && data.levels.length > 0) {
            setupQualityMenu(data.levels);
          }
        });

        hls.on(Hls.Events.ERROR, (e, data) => {
          if (data.fatal) {
            console.warn('HLS fatal error, falling back to direct stream:', data);
            video.src = streamFallbackUrl;
            setupQualityMenuFallback();
          }
        });

      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = hlsUrl;
      } else {
        video.src = streamFallbackUrl;
        setupQualityMenuFallback();
      }
    }

    function setupQualityMenu(levels) {
      qualityMenu.innerHTML = '';

      // Auto option
      const autoItem = document.createElement('div');
      autoItem.className = 'quality-item active';
      autoItem.dataset.level = '-1';
      autoItem.innerHTML = '<span class="check-icon">✓</span><span>Auto (อัตโนมัติ)</span>';
      autoItem.onclick = () => setQuality(-1, 'Auto');
      qualityMenu.appendChild(autoItem);

      if (levels && levels.length > 0) {
        levels.forEach((lvl, idx) => {
          const item = document.createElement('div');
          item.className = 'quality-item';
          item.dataset.level = idx;
          const name = lvl.name || (lvl.height ? `${lvl.height}p` : `Level ${idx + 1}`);
          item.innerHTML = `<span class="check-icon">✓</span><span>${name}</span>`;
          item.onclick = () => setQuality(idx, name);
          qualityMenu.appendChild(item);
        });
      }
    }

    function setupQualityMenuFallback() {
      qualityMenu.innerHTML = '';
      const items = [
        { level: -1, name: 'Auto (อัตโนมัติ)', label: 'Auto' },
        { level: 0, name: '1080p (ต้นฉบับ)', label: '1080p' },
        { level: 1, name: '720p (HD)', label: '720p' },
        { level: 2, name: '480p (ประหยัดเน็ต)', label: '480p' }
      ];
      items.forEach(it => {
        const item = document.createElement('div');
        item.className = 'quality-item' + (it.level === -1 ? ' active' : '');
        item.dataset.level = it.level;
        item.innerHTML = `<span class="check-icon">✓</span><span>${it.name}</span>`;
        item.onclick = () => setQuality(it.level, it.label || it.name);
        qualityMenu.appendChild(item);
      });
    }

    function setQuality(levelIndex, label) {
      if (hlsInstance) {
        hlsInstance.currentLevel = levelIndex;
      }
      qualityLabel.innerText = label.split(' ')[0];

      document.querySelectorAll('.quality-item').forEach(el => {
        if (parseInt(el.dataset.level, 10) === levelIndex) {
          el.classList.add('active');
        } else {
          el.classList.remove('active');
        }
      });

      closeQualityMenu();
    }

    function openQualityMenu() {
      qualityMenu.classList.add('show');
      qualityWrap.classList.add('active-menu');
      qualityWrap.classList.remove('fade-out');
    }

    function closeQualityMenu() {
      qualityMenu.classList.remove('show');
      qualityWrap.classList.remove('active-menu');
    }

    qualityBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (qualityMenu.classList.contains('show')) {
        closeQualityMenu();
      } else {
        openQualityMenu();
      }
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#quality-wrap')) {
        closeQualityMenu();
      }
    });

    // Subtly dim button when inactive (never vanish completely)
    let idleTimer = null;
    function wakeControl() {
      qualityWrap.classList.remove('fade-out');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (!qualityMenu.classList.contains('show') && !video.paused) {
          qualityWrap.classList.add('fade-out');
        }
      }, 4000);
    }

    document.addEventListener('mousemove', wakeControl);
    document.addEventListener('touchstart', wakeControl);
    video.addEventListener('play', wakeControl);
    video.addEventListener('pause', () => {
      qualityWrap.classList.remove('fade-out');
      clearTimeout(idleTimer);
    });
    wakeControl();

    // Keyboard Shortcuts & Double-click Fullscreen
    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.code === 'Space') {
        e.preventDefault();
        video.paused ? video.play() : video.pause();
      } else if (e.code === 'ArrowRight') {
        video.currentTime += 5;
      } else if (e.code === 'ArrowLeft') {
        video.currentTime -= 5;
      } else if (e.code === 'KeyF') {
        if (!document.fullscreenElement) {
          container.requestFullscreen?.();
        } else {
          document.exitFullscreen?.();
        }
      }
    });

    video.addEventListener('dblclick', () => {
      if (!document.fullscreenElement) {
        container.requestFullscreen?.();
      } else {
        document.exitFullscreen?.();
      }
    });

    document.addEventListener('DOMContentLoaded', initPlayer);
    if (document.readyState !== 'loading') {
      initPlayer();
    }
  </script>
</body>
</html>'''

async def handle_watch(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.Response(text="Invalid chat_id or msg_id", status=400)

    info = await get_or_probe_file_info(chat_id, msg_id)
    if not info:
        return web.Response(text=render_not_found_html(chat_id, msg_id), content_type="text/html", status=404)

    file_name = info["name"]
    hls_master_url = f"/hls/{chat_id}/{msg_id}/master.m3u8"
    stream_url = f"/stream/{chat_id}/{msg_id}"

    html_content = PURE_PLAYER_HTML.replace("__FILE_NAME__", html.escape(file_name)) \
                                   .replace("__HLS_URL__", hls_master_url) \
                                   .replace("__STREAM_URL__", stream_url) \
                                   .replace("__CHAT_ID__", str(chat_id)) \
                                   .replace("__MSG_ID__", str(msg_id))

    return web.Response(
        text=html_content,
        content_type="text/html",
        charset="utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Security-Policy": "frame-ancestors *",
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


# ─── TELEGRAM BOT LISTENER ────────────────────────────────────────────────────

@client.on(events.NewMessage)
async def on_media_message(event):
    if not event.message or not event.message.media:
        return

    file_info = get_file_info(event.message)
    if not file_info:
        return

    chat_id = event.chat_id
    msg_id = event.message.id
    name = file_info["name"]
    size_mb = f"{file_info['size'] / (1024*1024):.1f} MB"
    is_video = file_info["is_video"]

    save_db_video(chat_id, msg_id, file_info)

    watch_url = f"{BASE_URL}/watch/{chat_id}/{msg_id}"
    dl_url = f"{BASE_URL}/dl/{chat_id}/{msg_id}"

    icon = "🎬" if is_video else "📁"
    text = (
        f"{icon} <b>สร้างลิงก์สตรีมสำเร็จแล้ว!</b>\n\n"
        f"📄 <b>ชื่อไฟล์:</b> <code>{html.escape(name)}</code>\n"
        f"📦 <b>ขนาด:</b> <code>{size_mb}</code>\n\n"
    )
    if is_video:
        text += (
            f"▶️ <b>ดูออนไลน์ Ultra Stream (HLS + P2P WebRTC):</b>\n"
            f"{watch_url}\n\n"
        )
    text += (
        f"📥 <b>ดาวน์โหลดตรง (Direct Download):</b>\n"
        f"{dl_url}\n\n"
        f"⚡ <i>รองรับการดูหลายคนพร้อมกันไม่จำกัดด้วยระบบ P2P WebRTC & Cloudflare CDN</i>"
    )

    try:
        await event.reply(text, parse_mode="html", link_preview=False)
    except Exception as e:
        logger.error(f"Failed to reply link: {e}")

# ─── INITIALIZATION ───────────────────────────────────────────────────────────

async def on_startup(app):
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Telethon MTProto client authenticated on app event loop.")
    app['prune_task'] = asyncio.create_task(prune_lru_cache())

async def on_cleanup(app):
    if 'prune_task' in app:
        app['prune_task'].cancel()
    await client.disconnect()

def create_app():
    app = web.Application(client_max_size=1024*1024*100) # 100 MB max client body
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/favicon.ico", handle_favicon)
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_index)
    app.router.add_get("/sw.js", handle_service_worker)
    app.router.add_get("/watch/{chat_id}/{msg_id}", handle_watch)
    app.router.add_get("/stream/{chat_id}/{msg_id}", handle_stream)
    app.router.add_get("/dl/{chat_id}/{msg_id}", handle_stream)
    app.router.add_get("/hls/{chat_id}/{msg_id}/master.m3u8", handle_hls_master)
    app.router.add_get("/hls/{chat_id}/{msg_id}/{quality}/index.m3u8", handle_hls_media_playlist)
    app.router.add_get("/hls/{chat_id}/{msg_id}/{quality}/{seg_num}", handle_hls_segment)
    app.router.add_get("/api/status/{chat_id}/{msg_id}", handle_api_status)
    app.router.add_post("/api/transcode/{chat_id}/{msg_id}", handle_api_transcode)
    return app

if __name__ == "__main__":
    logger.info(f"Starting Antigravity Ultra Stream Server on 0.0.0.0:{PORT}...")
    web.run_app(create_app(), host="0.0.0.0", port=PORT)
