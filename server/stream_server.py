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
FASTSTART_DIR = BASE_DIR / "cache" / "faststart"
TRANSCODE_DIR = BASE_DIR / "transcoded"
DB_PATH = BASE_DIR / "tg_stream.db"
CINEMA_ICON_PATH = BASE_DIR / "cinema-icon.png"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
FASTSTART_DIR.mkdir(parents=True, exist_ok=True)
TRANSCODE_DIR.mkdir(parents=True, exist_ok=True)

def get_faststart_path(chat_id: int, msg_id: int):
    clean_id = str(abs(chat_id))
    if clean_id.startswith("100") and len(clean_id) > 10:
        clean_id = clean_id[3:]
    candidates = [
        FASTSTART_DIR / f"{clean_id}_{msg_id}.mp4",
        FASTSTART_DIR / f"{chat_id}_{msg_id}.mp4",
        FASTSTART_DIR / f"{abs(chat_id)}_{msg_id}.mp4",
    ]
    for c in candidates:
        if c.exists() and not c.name.endswith(".tmp") and c.stat().st_size > 1024 * 1024:
            return c
    return None


MAX_CACHE_BYTES = 20 * 1024 * 1024 * 1024  # 20 GB LRU cache
SEGMENT_DURATION = 6.0  # 6-second HLS segments

client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# Concurrency locks
segment_locks = {}
segment_locks_guard = asyncio.Lock()
FFMPEG_SEMAPHORE = asyncio.Semaphore(1)  # Strictly max 1 FFmpeg process at a time to prevent flood wait
STREAM_RANGE_CACHE = {}  # In-memory range cache (moov atoms, headers)
MAX_RANGE_CACHE_ITEMS = 120

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

    # Parse TGDrive metadata or clean plain text in caption if present
    if getattr(msg, "message", None):
        try:
            meta = json.loads(msg.message)
            if isinstance(meta, dict) and "name" in meta:
                file_name = meta["name"]
                if "size" in meta and meta["size"] > 0:
                    file_size = meta["size"]
                if "mime" in meta and meta["mime"]:
                    mime_type = meta["mime"]
        except Exception:
            clean_msg = msg.message.strip()
            if clean_msg and not clean_msg.startswith("{"):
                file_name = clean_msg

    # Ensure valid mime_type for common video extensions
    fn_lower = file_name.lower()
    if mime_type == "application/octet-stream" or not mime_type:
        if fn_lower.endswith(('.mp4', '.m4v')):
            mime_type = "video/mp4"
        elif fn_lower.endswith('.mkv'):
            mime_type = "video/x-matroska"
        elif fn_lower.endswith('.webm'):
            mime_type = "video/webm"
        elif fn_lower.endswith('.mov'):
            mime_type = "video/quicktime"
        elif fn_lower.endswith('.mp3'):
            mime_type = "audio/mpeg"
        elif fn_lower.endswith('.m4a'):
            mime_type = "audio/mp4"

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

async def resolve_media_target(chat_id: int, msg_id: int):
    real_cid, msg = await fetch_tg_message(chat_id, msg_id)
    if not msg or not msg.media:
        return real_cid, None

    info = get_file_info(msg)
    if not info:
        return real_cid, None

    # Check if this message is part of a multi-part file group
    meta = None
    if getattr(msg, "message", None):
        try:
            m_parsed = json.loads(msg.message)
            if isinstance(m_parsed, dict) and m_parsed.get("fileGroupId") and m_parsed.get("totalParts", 1) > 1:
                meta = m_parsed
        except Exception:
            pass

    if not meta:
        return real_cid, {
            "is_multipart": False,
            "info": info,
            "parts": [{
                "partIndex": 0,
                "msg": msg,
                "start_byte": 0,
                "end_byte": info["size"] - 1,
                "size": info["size"]
            }]
        }

    group_id = meta["fileGroupId"]
    total_parts = meta.get("totalParts", 1)
    current_part_idx = meta.get("partIndex", 0)
    current_part_size = meta.get("partSize", msg.file.size if msg.file else 0)

    part_msgs = {current_part_idx: (msg, current_part_size)}

    # Scan adjacent messages in channel to gather all parts
    search_range = range(max(1, msg_id - total_parts - 5), msg_id + total_parts + 6)
    candidate_ids = [mid for mid in search_range if mid != msg_id]
    if candidate_ids:
        try:
            candidates = await client.get_messages(real_cid, ids=candidate_ids)
            for c in candidates:
                if c and c.media and getattr(c, "message", None):
                    try:
                        c_meta = json.loads(c.message)
                        if isinstance(c_meta, dict) and c_meta.get("fileGroupId") == group_id:
                            p_idx = c_meta.get("partIndex", 0)
                            p_size = c_meta.get("partSize", c.file.size if c.file else 0)
                            part_msgs[p_idx] = (c, p_size)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error scanning sibling parts for {group_id}: {e}")

    # Build contiguous byte offsets
    parts_list = []
    current_byte = 0
    for p_idx in sorted(part_msgs.keys()):
        p_msg, p_sz = part_msgs[p_idx]
        parts_list.append({
            "partIndex": p_idx,
            "msg": p_msg,
            "start_byte": current_byte,
            "end_byte": current_byte + p_sz - 1,
            "size": p_sz
        })
        current_byte += p_sz

    if current_byte > 0:
        info["size"] = current_byte

    return real_cid, {
        "is_multipart": True,
        "group_id": group_id,
        "total_parts": total_parts,
        "info": info,
        "parts": parts_list
    }

async def get_or_probe_file_info(chat_id: int, msg_id: int):
    cached = get_db_video(chat_id, msg_id)
    if not cached and chat_id > 0:
        cached = get_db_video(-int(f"100{chat_id}"), msg_id)

    # Re-probe if cached is missing or marked with octet-stream or incomplete .part1
    if cached and cached.get("duration", 0) > 0 and cached.get("mime", "") != "application/octet-stream" and not cached.get("name", "").endswith(".part1"):
        return cached

    real_cid, target = await resolve_media_target(chat_id, msg_id)
    if not target:
        return None

    info = target["info"]

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

# ─── CINEMA PORTAL & MOVIE DASHBOARD ──────────────────────────────────────────

KNOWN_MOVIES_METADATA = {
    "ธี่หยด": {
        "title": "ธี่หยด สมิงเขาขวาง",
        "original_title": "Death Whisperer 2 (2024)",
        "overview": "3 ปีหลังจากการเสียชีวิตของแย้ม 'ยักษ์' ยังคงออกตามล่าวิญญาณชุดดำอย่างไม่ลดละ จนกระทั่งพบเบาะแสว่ามีผีชุดดำสิงสู่ในดงโขมดป่าลึก ยักษ์จึงต้องร่วมมือกับจ่าปันเพื่อปิดบัญชีแค้นก่อนที่ความตายจะพรากคนที่เขารักไปอีกครั้ง",
        "poster_url": "https://image.tmdb.org/t/p/w500/A0fHnpVX8vYQCmvETllWJQ30Mi6.jpg",
        "backdrop_url": "https://images.unsplash.com/photo-1518709268805-4e9042af9f23?q=80&w=1920&auto=format&fit=crop",
        "release_date": "2024",
        "vote_average": 8.5,
        "category": "ภาพยนตร์ไทย"
    },
    "mood booster": {
        "title": "Mood Booster — Ultra 4K Concert",
        "original_title": "Mood Booster",
        "overview": "รวมมิวสิควิดีโอและคอนเสิร์ตเสียงคมชัดระดับพรีเมียมจาก Telegram Cloud Storage",
        "poster_url": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=500&auto=format&fit=crop&q=60",
        "backdrop_url": "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=1920&auto=format&fit=crop&q=80",
        "release_date": "2024",
        "vote_average": 7.8,
        "category": "คอนเสิร์ต"
    },
    "big_buck_bunny": {
        "title": "Big Buck Bunny 4K Remaster",
        "original_title": "Big Buck Bunny",
        "overview": "แอนิเมชันความละเอียดสูงสำหรับทดสอบระบบภาพ HDR และเสียงรอบทิศทาง",
        "poster_url": "https://images.unsplash.com/photo-1574375927938-d5a98e8ffe85?w=500&auto=format&fit=crop&q=60",
        "backdrop_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=1920&auto=format&fit=crop&q=80",
        "release_date": "2023",
        "vote_average": 7.5,
        "category": "แอนิเมชัน"
    }
}

def format_movie_duration(secs: float) -> str:
    if not secs or secs <= 0:
        return ""
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"

def format_movie_size(b: int) -> str:
    if not b:
        return "0 MB"
    if b >= 1024 * 1024 * 1024:
        return f"{b / (1024*1024*1024):.2f} GB"
    return f"{b / (1024*1024):.1f} MB"

def get_all_movies():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT chat_id, msg_id, file_name, file_size, duration
        FROM videos
        WHERE (mime_type LIKE 'video/%' OR file_name LIKE '%.mp4' OR file_name LIKE '%.mkv')
        ORDER BY updated_at DESC, duration DESC
    """)
    rows = cur.fetchall()
    conn.close()

    seen_names = set()
    movies = []

    for chat_id, msg_id, file_name, file_size, duration in rows:
        norm_key = file_name.lower().replace(".mp4", "").replace(".mkv", "").strip()
        if norm_key in seen_names or "test_" in norm_key or file_size < 5 * 1024 * 1024:
            continue
        seen_names.add(norm_key)

        meta = None
        for k, v in KNOWN_MOVIES_METADATA.items():
            if k in norm_key:
                meta = v
                break

        if not meta:
            clean_title = file_name.rsplit(".", 1)[0].replace("_", " ").replace(".", " ").title()
            meta = {
                "title": clean_title,
                "original_title": file_name,
                "overview": "ภาพยนตร์คุณภาพสูงจาก Telegram Cloud Storage พร้อมระบบสตรีมมิ่งความเร็วสูง",
                "poster_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&auto=format&fit=crop&q=60",
                "backdrop_url": "https://images.unsplash.com/photo-1518173946687-a4c8a383392e?w=1280&auto=format&fit=crop&q=80",
                "release_date": "2024",
                "vote_average": 7.5,
                "category": "ภาพยนตร์"
            }

        is_faststart = get_faststart_path(chat_id, msg_id) is not None

        # Clean display title based on actual file name (strip extension) as requested by user
        clean_file_title = file_name.rsplit(".", 1)[0].replace("_", " ").strip()
        display_title = clean_file_title if clean_file_title else meta["title"]

        movies.append({
            "id": f"{chat_id}_{msg_id}",
            "chat_id": chat_id,
            "msg_id": msg_id,
            "file_name": file_name,
            "title": display_title,
            "original_title": meta["original_title"],
            "overview": meta["overview"],
            "poster_url": meta["poster_url"],
            "backdrop_url": meta["backdrop_url"],
            "release_date": meta["release_date"],
            "vote_average": meta["vote_average"],
            "category": meta["category"],
            "duration": duration,
            "duration_formatted": format_movie_duration(duration),
            "file_size": file_size,
            "size_formatted": format_movie_size(file_size),
            "faststart_ready": is_faststart,
            "watch_url": f"/watch/{chat_id}/{msg_id}",
            "stream_url": f"/stream/{chat_id}/{msg_id}"
        })

    return movies

async def handle_api_movies(request: web.Request):
    movies = get_all_movies()
    return web.json_response(movies, headers={
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=60"
    })

CINEMA_PORTAL_HTML = '''<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GAPT-CINEMA — ศูนย์รวมภาพยนตร์ออนไลน์ Ultra Stream</title>
  <link rel="icon" type="image/png" href="/cinema-icon.png?v=2">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800;900&family=Noto+Sans+Thai:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #07090e;
      --surface: rgba(15, 23, 42, 0.75);
      --surface-border: rgba(255, 255, 255, 0.09);
      --primary: #e50914;
      --primary-hover: #f40612;
      --primary-glow: rgba(229, 9, 20, 0.5);
      --accent: #38bdf8;
      --gold: #f59e0b;
      --text: #f8fafc;
      --text-muted: #94a3b8;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', 'Noto Sans Thai', sans-serif;
      min-height: 100vh;
      overflow-x: hidden;
      background-image: 
        radial-gradient(ellipse at 15% 0%, rgba(229, 9, 20, 0.08), transparent 50%),
        radial-gradient(ellipse at 85% 15%, rgba(56, 189, 248, 0.06), transparent 50%);
    }

    /* Sticky Navigation Bar */
    header {
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(7, 9, 14, 0.88);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--surface-border);
      padding: 12px 36px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }
    .nav-left {
      display: flex;
      align-items: center;
      gap: 32px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      text-decoration: none;
      color: inherit;
      cursor: pointer;
    }
    .brand-icon {
      width: 42px; height: 42px;
      display: flex; align-items: center; justify-content: center;
      filter: drop-shadow(0 0 16px rgba(229, 9, 20, 0.6));
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .brand:hover .brand-icon {
      transform: scale(1.1) rotate(-3deg);
    }
    .brand-icon img {
      width: 36px;
      height: 36px;
      object-fit: contain;
      display: block;
    }
    .brand-name {
      font-size: 1.45rem;
      font-weight: 900;
      letter-spacing: 0.04em;
      background: linear-gradient(135deg, #ffffff 0%, #ff8b8e 40%, #e50914 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      filter: drop-shadow(0 0 16px rgba(229, 9, 20, 0.4));
      text-transform: uppercase;
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 18px;
    }
    .nav-link {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 0.9rem;
      font-weight: 600;
      transition: color 0.2s;
      cursor: pointer;
    }
    .nav-link:hover, .nav-link.active {
      color: #fff;
    }
    .nav-link.badge-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--surface-border);
      border-radius: 9999px;
      font-size: 0.8rem;
    }
    .nav-link.badge-link:hover {
      background: rgba(255, 255, 255, 0.12);
      border-color: rgba(255, 255, 255, 0.2);
    }

    .nav-right {
      display: flex;
      align-items: center;
      gap: 16px;
    }
    .search-container {
      position: relative;
      width: 260px;
    }
    .search-input {
      width: 100%;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--surface-border);
      border-radius: 9999px;
      padding: 9px 18px 9px 40px;
      color: #fff;
      font-size: 0.88rem;
      outline: none;
      transition: all 0.2s ease;
    }
    .search-input:focus {
      background: rgba(255, 255, 255, 0.1);
      border-color: var(--primary);
      box-shadow: 0 0 16px var(--primary-glow);
      width: 300px;
    }
    .search-icon {
      position: absolute;
      left: 14px; top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      pointer-events: none;
    }

    /* Featured Hero Banner (Netflix / OTT Immersive Style) */
    .hero-container {
      position: relative;
      width: 100%;
      min-height: 520px;
      height: 68vh;
      max-height: 720px;
      display: flex;
      align-items: flex-end;
      padding: 50px 48px;
      background-size: cover;
      background-position: center 25%;
      background-repeat: no-repeat;
      overflow: hidden;
      transition: background-image 0.5s ease-in-out;
    }
    .hero-mask {
      position: absolute;
      inset: 0;
      background: 
        linear-gradient(to right, rgba(7, 9, 14, 0.96) 20%, rgba(7, 9, 14, 0.72) 55%, rgba(7, 9, 14, 0.25) 100%),
        linear-gradient(to top, rgba(7, 9, 14, 1) 0%, rgba(7, 9, 14, 0.6) 25%, transparent 65%),
        linear-gradient(to bottom, rgba(7, 9, 14, 0.7) 0%, transparent 20%);
      pointer-events: none;
    }
    .hero-body {
      position: relative;
      z-index: 10;
      max-width: 720px;
    }
    .hero-tags {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-bottom: 16px;
    }
    .tag {
      padding: 4px 12px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .tag-imdb { background: rgba(245, 158, 11, 0.2); color: #facc15; border: 1px solid rgba(245, 158, 11, 0.5); }
    .tag-year { background: rgba(255, 255, 255, 0.12); color: #fff; border: 1px solid rgba(255, 255, 255, 0.2); }
    .tag-faststart { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.5); }
    .tag-quality { background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); }
    
    .hero-title {
      font-size: clamp(2.4rem, 5.2vw, 4rem);
      font-weight: 900;
      line-height: 1.1;
      margin-bottom: 16px;
      color: #ffffff;
      text-shadow: 0 4px 24px rgba(0, 0, 0, 0.9), 0 1px 4px rgba(0,0,0,0.8);
      letter-spacing: -0.01em;
    }
    .hero-overview {
      color: #e2e8f0;
      font-size: 1rem;
      line-height: 1.65;
      margin-bottom: 28px;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      overflow: hidden;
      text-shadow: 0 2px 12px rgba(0, 0, 0, 0.85);
      max-width: 640px;
    }
    .hero-actions {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }
    .btn-play-hero {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      background: linear-gradient(135deg, #e50914 0%, #b81d24 100%);
      color: #fff;
      padding: 14px 32px;
      border-radius: 9999px;
      font-size: 1.05rem;
      font-weight: 800;
      text-decoration: none;
      box-shadow: 0 4px 25px var(--primary-glow);
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      cursor: pointer;
      border: none;
    }
    .btn-play-hero:hover {
      transform: translateY(-2px) scale(1.03);
      box-shadow: 0 8px 35px rgba(229, 9, 20, 0.7);
      background: linear-gradient(135deg, #f40612 0%, #cc0000 100%);
    }
    .btn-secondary {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      color: #fff;
      padding: 14px 24px;
      border-radius: 9999px;
      font-size: 0.95rem;
      font-weight: 700;
      text-decoration: none;
      border: 1px solid rgba(255, 255, 255, 0.2);
      transition: all 0.2s ease;
      cursor: pointer;
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.22);
      transform: translateY(-1px);
    }

    /* Platform Slogan / Features Bar */
    .slogan-bar {
      background: rgba(15, 23, 42, 0.5);
      border-top: 1px solid var(--surface-border);
      border-bottom: 1px solid var(--surface-border);
      padding: 16px 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 16px;
    }
    .slogan-text {
      font-size: 0.95rem;
      font-weight: 700;
      color: #f1f5f9;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .slogan-highlight {
      color: #ef4444;
      font-weight: 800;
    }
    .feature-pills {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .pill {
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Main Content */
    main {
      padding: 40px 48px 70px;
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 28px;
      flex-wrap: wrap;
      gap: 16px;
    }
    .section-title {
      font-size: 1.5rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #fff;
    }
    .filter-tabs {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .tab-btn {
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--surface-border);
      color: var(--text-muted);
      padding: 8px 16px;
      border-radius: 9999px;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }
    .tab-btn.active, .tab-btn:hover {
      background: rgba(229, 9, 20, 0.15);
      border-color: var(--primary);
      color: #ff8b8e;
    }

    /* Movies Grid */
    .movies-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 26px;
    }
    .movie-card {
      background: var(--surface);
      border: 1px solid var(--surface-border);
      border-radius: 16px;
      overflow: hidden;
      cursor: pointer;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      display: flex;
      flex-direction: column;
      position: relative;
      text-decoration: none;
      color: inherit;
    }
    .movie-card:hover, .movie-card:focus {
      transform: translateY(-8px);
      border-color: var(--primary);
      box-shadow: 0 20px 40px -10px rgba(229, 9, 20, 0.35);
      outline: none;
    }
    .poster-wrap {
      position: relative;
      width: 100%;
      aspect-ratio: 2 / 3;
      background: #111827;
      overflow: hidden;
    }
    .poster-img {
      width: 100%; height: 100%;
      object-fit: cover;
      transition: transform 0.4s ease;
    }
    .movie-card:hover .poster-img {
      transform: scale(1.08);
    }
    .card-badge {
      position: absolute;
      top: 10px; left: 10px;
      padding: 4px 8px;
      border-radius: 6px;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(6px);
      font-size: 0.72rem;
      font-weight: 800;
      color: #facc15;
      display: flex; align-items: center; gap: 4px;
    }
    .faststart-pill {
      position: absolute;
      top: 10px; right: 10px;
      padding: 4px 8px;
      border-radius: 6px;
      background: rgba(16, 185, 129, 0.9);
      backdrop-filter: blur(6px);
      font-size: 0.68rem;
      font-weight: 800;
      color: #fff;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .play-overlay {
      position: absolute;
      inset: 0;
      background: rgba(0, 0, 0, 0.45);
      display: flex;
      align-items: center;
      justify-content: center;
      opacity: 0;
      transition: opacity 0.2s ease;
    }
    .movie-card:hover .play-overlay {
      opacity: 1;
    }
    .play-btn-circle {
      width: 58px; height: 58px;
      border-radius: 50%;
      background: linear-gradient(135deg, #e50914, #b81d24);
      box-shadow: 0 0 30px rgba(229, 9, 20, 0.8);
      display: flex; align-items: center; justify-content: center;
      transform: scale(0.85);
      transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .movie-card:hover .play-btn-circle {
      transform: scale(1);
    }
    .play-btn-circle svg {
      width: 26px; height: 26px;
      fill: #fff;
      margin-left: 3px;
    }
    .card-meta {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      flex: 1;
    }
    .card-title {
      font-size: 1rem;
      font-weight: 700;
      line-height: 1.35;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      color: #f8fafc;
    }
    .card-sub {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--text-muted);
      font-size: 0.8rem;
      margin-top: auto;
      font-weight: 500;
    }

    /* Toast Notification */
    #toast {
      position: fixed;
      bottom: 24px; right: 24px;
      background: rgba(16, 185, 129, 0.95);
      backdrop-filter: blur(8px);
      color: #fff;
      padding: 14px 24px;
      border-radius: 12px;
      font-weight: 700;
      font-size: 0.95rem;
      box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      z-index: 999;
    }
    #toast.show {
      transform: translateY(0);
      opacity: 1;
    }

    /* Responsive */
    @media (max-width: 900px) {
      header { padding: 12px 20px; }
      .nav-links { display: none; }
      .hero-container { padding: 36px 24px; min-height: 440px; height: auto; }
      .hero-title { font-size: 2.2rem; }
      .slogan-bar { padding: 14px 20px; }
      main { padding: 28px 20px 50px; }
    }
    @media (max-width: 600px) {
      .hero-container { min-height: 400px; padding: 24px 18px; }
      .hero-title { font-size: 1.75rem; }
      .hero-overview { font-size: 0.88rem; -webkit-line-clamp: 2; }
      .movies-grid { grid-template-columns: repeat(2, 1fr); gap: 14px; }
      .card-meta { padding: 10px; }
      .card-title { font-size: 0.88rem; }
      .search-container { width: 160px; }
      .search-input:focus { width: 200px; }
    }
  </style>
</head>
<body>
  <!-- Header Navigation -->
  <header>
    <div class="nav-left">
      <a href="/" class="brand">
        <div class="brand-icon">
          <img src="/cinema-icon.png?v=2" alt="GAPT-CINEMA">
        </div>
        <div class="brand-name">GAPT-CINEMA</div>
      </a>
      <nav class="nav-links">
        <a class="nav-link active" onclick="filterCategory('all', null)">หน้าหลัก</a>
        <a class="nav-link" onclick="filterCategory('thai', null)">ภาพยนตร์ไทย</a>
        <a class="nav-link" onclick="filterCategory('faststart', null)">⚡ Faststart พร้อมดู</a>
        <a href="https://drive.capt-th.work/" target="_blank" class="nav-link badge-link">
          <span>📁</span> TG-Drive Cloud
        </a>
      </nav>
    </div>
    <div class="nav-right">
      <div class="search-container">
        <span class="search-icon">🔍</span>
        <input type="text" id="searchInput" class="search-input" placeholder="ค้นหาภาพยนตร์..." autocomplete="off">
      </div>
    </div>
  </header>

  <!-- Featured Hero Banner (Netflix / OTT Immersive Style) -->
  <div class="hero-container" id="heroBanner" style="background-image: url('https://images.unsplash.com/photo-1518709268805-4e9042af9f23?q=80&w=1920&auto=format&fit=crop');">
    <div class="hero-mask"></div>
    <div class="hero-body">
      <div class="hero-tags">
        <span class="tag tag-imdb" id="heroRating">★ 8.5 IMDB</span>
        <span class="tag tag-year" id="heroYear">2024</span>
        <span class="tag tag-faststart">⚡ ULTRA STREAM</span>
        <span class="tag tag-quality" id="heroQuality">1080P FULL HD</span>
      </div>
      <h1 class="hero-title" id="heroTitle">ธี่หยด สมิงเขาขวาง</h1>
      <p class="hero-overview" id="heroOverview">
        3 ปีหลังจากการเสียชีวิตของแย้ม 'ยักษ์' ยังคงออกตามล่าวิญญาณชุดดำอย่างไม่ลดละ จนกระทั่งพบเบาะแสว่ามีผีชุดดำสิงสู่ในดงโขมดป่าลึก ยักษ์จึงต้องร่วมมือกับจ่าปันเพื่อปิดบัญชีแค้นก่อนที่ความตายจะพรากคนที่เขารักไปอีกครั้ง
      </p>
      <div class="hero-actions">
        <a id="heroPlayBtn" href="/watch/4381915212/11" class="btn-play-hero">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          ดูภาพยนตร์
        </a>
        <button onclick="copyCurrentHeroStream()" class="btn-secondary">
          <span>🔗</span> คัดลอกลิงก์สตรีม
        </button>
        <a href="https://drive.capt-th.work/" target="_blank" class="btn-secondary">
          <span>📁</span> เปิดใน TG-Drive
        </a>
      </div>
    </div>
  </div>

  <!-- Platform Slogan & Highlights -->
  <div class="slogan-bar">
    <div class="slogan-text">
      <span>🍿</span>
      <span>GAPT-CINEMA — ศูนย์รวมภาพยนตร์ออนไลน์ความเร็วสูง <span class="slogan-highlight">ไร้โฆษณากวนใจ 100%</span></span>
    </div>
    <div class="feature-pills">
      <span class="pill">🛡️ ไร้มัลแวร์</span>
      <span class="pill">•</span>
      <span class="pill">⚡ Ultra Stream Faststart</span>
      <span class="pill">•</span>
      <span class="pill">🔊 เสียงใสเต็ม Bitrate</span>
    </div>
  </div>

  <!-- Catalog Section -->
  <main>
    <div class="section-head">
      <h2 class="section-title">
        <span>🎬</span> รายการภาพยนตร์ทั้งหมด <span id="movieCount" style="color: #ff8b8e; font-size: 1rem; font-weight: 600;"></span>
      </h2>
      <div class="filter-tabs">
        <button class="tab-btn active" onclick="filterCategory('all', this)">ทั้งหมด</button>
        <button class="tab-btn" onclick="filterCategory('thai', this)">ภาพยนตร์ไทย</button>
        <button class="tab-btn" onclick="filterCategory('faststart', this)">⚡ Faststart พร้อมดู</button>
      </div>
    </div>

    <!-- Movie Cards Grid -->
    <div class="movies-grid" id="moviesGrid">
      <!-- Dynamic render via JS -->
    </div>
  </main>

  <div id="toast">คัดลอกลิงก์สตรีมสำเร็จ!</div>

  <script>
    var allMovies = __INITIAL_MOVIES_JSON__;
    var currentFilter = 'all';
    var currentHeroMovie = null;

    function renderMovies(movies) {
      var grid = document.getElementById('moviesGrid');
      document.getElementById('movieCount').innerText = '(' + movies.length + ' เรื่อง)';
      
      if (movies.length === 0) {
        grid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 60px 0; color: #64748b;">ไม่พบภาพยนตร์ที่ค้นหา</div>';
        return;
      }

      var html = '';
      movies.forEach(function(m) {
        var faststartBadge = m.faststart_ready ? '<span class="faststart-pill">⚡ Faststart</span>' : '';
        var dur = m.duration_formatted ? m.duration_formatted : (m.size_formatted || '');
        var rating = m.vote_average ? ('⭐ ' + m.vote_average.toFixed(1)) : 'HD';

        html += `
          <a href="${m.watch_url}" class="movie-card" tabindex="0">
            <div class="poster-wrap">
              <img src="${m.poster_url}" alt="${m.title}" class="poster-img" loading="lazy" onerror="this.src='https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=500&auto=format&fit=crop&q=60'">
              <span class="card-badge">${rating}</span>
              ${faststartBadge}
              <div class="play-overlay">
                <div class="play-btn-circle">
                  <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                </div>
              </div>
            </div>
            <div class="card-meta">
              <h3 class="card-title">${m.title}</h3>
              <div class="card-sub">
                <span>${m.release_date || '2024'}</span>
                <span>${dur}</span>
              </div>
            </div>
          </a>
        `;
      });
      grid.innerHTML = html;
    }

    function applyFilter() {
      var q = document.getElementById('searchInput').value.toLowerCase().trim();
      var filtered = allMovies.filter(function(m) {
        var matchQ = !q || m.title.toLowerCase().indexOf(q) !== -1 || m.original_title.toLowerCase().indexOf(q) !== -1;
        var matchCat = true;
        if (currentFilter === 'faststart') {
          matchCat = m.faststart_ready;
        } else if (currentFilter === 'thai') {
          matchCat = m.category === 'ภาพยนตร์ไทย';
        }
        return matchQ && matchCat;
      });
      renderMovies(filtered);
    }

    function filterCategory(cat, btn) {
      currentFilter = cat;
      document.querySelectorAll('.tab-btn').forEach(function(b) { b.classList.remove('active'); });
      if (btn) {
        btn.classList.add('active');
      } else {
        var allBtns = document.querySelectorAll('.tab-btn');
        if (cat === 'all' && allBtns[0]) allBtns[0].classList.add('active');
        if (cat === 'thai' && allBtns[1]) allBtns[1].classList.add('active');
        if (cat === 'faststart' && allBtns[2]) allBtns[2].classList.add('active');
      }
      applyFilter();
    }

    function copyCurrentHeroStream() {
      if (!currentHeroMovie || !currentHeroMovie.watch_url) return;
      var fullUrl = window.location.origin + currentHeroMovie.watch_url;
      navigator.clipboard.writeText(fullUrl).then(function() {
        var t = document.getElementById('toast');
        t.innerText = 'คัดลอกลิงก์สตรีมสำเร็จ! นำไปเปิดใน VLC หรือส่งต่อได้ทันที';
        t.className = 'show';
        setTimeout(function() { t.className = ''; }, 3000);
      });
    }

    document.getElementById('searchInput').addEventListener('input', applyFilter);

    // Initial render & sync hero banner with active movie
    if (allMovies && allMovies.length > 0) {
      var hero = allMovies[0];
      currentHeroMovie = hero;

      var ht = document.getElementById('heroTitle');
      if (ht) ht.innerText = hero.title;

      var ho = document.getElementById('heroOverview');
      if (ho && hero.overview) ho.innerText = hero.overview;

      var hb = document.getElementById('heroPlayBtn');
      if (hb && hero.watch_url) hb.href = hero.watch_url;

      var hr = document.getElementById('heroRating');
      if (hr && hero.vote_average) hr.innerText = '★ ' + hero.vote_average.toFixed(1) + ' IMDB';

      var hy = document.getElementById('heroYear');
      if (hy && hero.release_date) hy.innerText = hero.release_date;

      var hq = document.getElementById('heroQuality');
      if (hq) hq.innerText = (hero.duration_formatted ? hero.duration_formatted + ' • ' : '') + '1080P FULL HD';

      var hBanner = document.getElementById('heroBanner');
      if (hBanner && (hero.backdrop_url || hero.poster_url)) {
        hBanner.style.backgroundImage = 'url(' + (hero.backdrop_url || hero.poster_url) + ')';
      }
    }
    renderMovies(allMovies);
  </script>
</body>
</html>'''

async def handle_cinema_portal(request: web.Request):
    movies = get_all_movies()
    movies_json = json.dumps(movies, ensure_ascii=False)
    html_content = CINEMA_PORTAL_HTML.replace("__INITIAL_MOVIES_JSON__", movies_json)
    return web.Response(
        text=html_content,
        content_type="text/html",
        charset="utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )

# ─── HTTP ENDPOINTS ────────────────────────────────────────────────────────────

async def handle_index(request: web.Request):
    return web.json_response({
        "service": "GAPT-CINEMA Video Stream Engine",
        "version": "2.0.0",
        "status": "online",
        "features": [
            "HLS Adaptive Bitrate Streaming",
            "P2P WebRTC Mesh Swarm",
            "Multi-Part Automatic Re-assembly",
            "AV1 Hardware & SVT-AV1 Transcoding",
            "AI Per-Scene Variable Bitrate",
            "Predictive Service Worker Prefetching",
            "Cloudflare CDN & HTTP/3 QUIC"
        ],
        "endpoints": {
            "cinema_dashboard": "/",
            "movies_api": "/api/movies",
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


async def handle_cinema_icon(request: web.Request):
    if CINEMA_ICON_PATH.exists():
        return web.FileResponse(CINEMA_ICON_PATH, headers={"Cache-Control": "public, max-age=86400"})
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#38bdf8"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
    return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

async def handle_favicon(request: web.Request):
    if CINEMA_ICON_PATH.exists():
        return web.FileResponse(CINEMA_ICON_PATH, headers={"Cache-Control": "public, max-age=86400"})
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#38bdf8"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
    return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

async def handle_stream(request: web.Request):
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.Response(text="Invalid chat_id or msg_id", status=400)

    is_download = request.path.startswith("/dl/")

    real_cid, target = await resolve_media_target(chat_id, msg_id)
    if not target or not target["parts"]:
        return web.Response(text="Message does not contain streamable media", status=404)

    file_info = target["info"]
    file_size = file_info["size"]
    mime_type = file_info["mime"]
    file_name = file_info["name"]

    # If pre-remuxed True Faststart exists on local SSD, serve it with 0 latency & full Range support!
    faststart_path = get_faststart_path(chat_id, msg_id)
    if faststart_path:
        response = web.FileResponse(faststart_path)
        response.headers["Accept-Ranges"] = "bytes"
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Range"
        response.headers["Access-Control-Expose-Headers"] = "Content-Range, Content-Length, Accept-Ranges"
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["Alt-Svc"] = 'h3=":443"; ma=86400'
        if is_download:
            safe_name = file_name.replace('"', '\\"')
            response.headers["Content-Disposition"] = f'attachment; filename="{safe_name}"'
        return response

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

    range_cache_key = (real_cid, msg_id, start, end)
    if length <= 5 * 1024 * 1024 and range_cache_key in STREAM_RANGE_CACHE:
        cached_data = STREAM_RANGE_CACHE[range_cache_key]
        if len(cached_data) == length:
            response = web.StreamResponse(status=status, headers=headers)
            await response.prepare(request)
            await response.write(cached_data)
            await response.write_eof()
            return response

    response = web.StreamResponse(status=status, headers=headers)
    await response.prepare(request)

    chunk_size = 512 * 1024
    should_cache = (length <= 5 * 1024 * 1024)
    collected_chunks = [] if should_cache else None

    try:
        for part in target["parts"]:
            p_start = part["start_byte"]
            p_end = part["end_byte"]
            overlap_start = max(start, p_start)
            overlap_end = min(end, p_end)
            if overlap_start <= overlap_end:
                sub_offset = overlap_start - p_start
                sub_length = overlap_end - overlap_start + 1
                bytes_remaining = sub_length

                async for chunk in client.iter_download(
                    part["msg"].media,
                    offset=sub_offset,
                    request_size=chunk_size
                ):
                    if len(chunk) > bytes_remaining:
                        chunk = chunk[:bytes_remaining]

                    if should_cache:
                        collected_chunks.append(chunk)

                    await response.write(chunk)
                    bytes_remaining -= len(chunk)

                    if bytes_remaining <= 0:
                        break

        if should_cache and collected_chunks:
            full_data = b"".join(collected_chunks)
            if len(full_data) == length:
                if len(STREAM_RANGE_CACHE) > MAX_RANGE_CACHE_ITEMS:
                    STREAM_RANGE_CACHE.clear()
                STREAM_RANGE_CACHE[range_cache_key] = full_data
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

    # Only advertise other renditions if they have been pre-transcoded on disk!
    for q, b, res in [("1080p", 3500000, "1920x1080"), ("720p", 1800000, "1280x720"), ("480p", 800000, "854x480")]:
        transcoded_dir = TRANSCODE_DIR / f"{chat_id}_{msg_id}_{q}"
        if transcoded_dir.exists() and (transcoded_dir / "index.m3u8").exists():
            lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH={b},RESOLUTION={res},CODECS="avc1.640028,mp4a.40.2",NAME="{q}"')
            lines.append(f"/hls/{chat_id}/{msg_id}/{q}/index.m3u8")

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

# ─── HLS SEGMENT SERVER WITH CONTINUOUS GENERATOR ─────────────────────────────

# One long-running FFmpeg per video: reads stream linearly, outputs all segments
continuous_generators = {}  # key -> {"proc": Process, "task": Task}
continuous_gen_lock = asyncio.Lock()

async def ensure_continuous_generator(chat_id: int, msg_id: int, quality: str = "source"):
    """Start a continuous FFmpeg HLS segmenter if not already running.
    FFmpeg reads the stream ONCE (linearly, no seeking) and outputs segments
    continuously to disk — much faster than per-segment seek approach."""
    key = f"{chat_id}_{msg_id}_{quality}"

    async with continuous_gen_lock:
        # Already running?
        if key in continuous_generators:
            gen = continuous_generators[key]
            if gen["proc"].returncode is None:  # still running
                return
            # Process finished, remove stale entry
            continuous_generators.pop(key, None)

        stream_url = f"http://127.0.0.1:{PORT}/stream/{chat_id}/{msg_id}"

        # Build segment filename pattern to match cache_key format
        seg_pattern = str(CACHE_DIR / f"{chat_id}_{msg_id}_{quality}_%d.ts")

        vf = []
        codec_args = ["-c", "copy", "-bsf:v", "h264_mp4toannexb"]
        if quality == "480p":
            codec_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-vf", "scale=-2:480", "-c:a", "aac", "-b:a", "96k"]
        elif quality == "720p":
            codec_args = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "26", "-vf", "scale=-2:720", "-c:a", "aac", "-b:a", "128k"]

        cmd = [
            "ffmpeg", "-y",
            "-i", stream_url,
            *codec_args,
            "-f", "hls",
            "-hls_time", str(int(SEGMENT_DURATION)),
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_filename", seg_pattern,
            str(CACHE_DIR / f"{key}_playlist.m3u8")  # temp playlist (not served)
        ]

        logger.info(f"Starting continuous segment generator for {key}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE
        )

        async def monitor():
            try:
                _, stderr = await proc.communicate()
                rc = proc.returncode
                if rc != 0:
                    err_tail = (stderr or b"")[-500:].decode("utf-8", errors="replace")
                    logger.warning(f"Continuous generator {key} exited code {rc}: {err_tail}")
                else:
                    logger.info(f"Continuous generator {key} completed successfully")
            except Exception as e:
                logger.error(f"Continuous generator monitor error {key}: {e}")
            finally:
                async with continuous_gen_lock:
                    continuous_generators.pop(key, None)

        task = asyncio.create_task(monitor())
        continuous_generators[key] = {"proc": proc, "task": task}

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

    # Check disk cache — instant serve if already generated
    if cached_file.exists() and cached_file.stat().st_size > 0:
        record_cache_access(cache_key, str(cached_file), cached_file.stat().st_size)
        return await serve_file_segment(request, cached_file)

    # Ensure continuous generator is running for this video
    await ensure_continuous_generator(chat_id, msg_id, quality)

    # Wait for the segment file to appear (generated by background FFmpeg)
    max_wait = 45.0  # seconds
    poll_interval = 0.5
    waited = 0.0
    while waited < max_wait:
        if cached_file.exists() and cached_file.stat().st_size > 0:
            # Small extra wait to ensure FFmpeg has finished writing
            await asyncio.sleep(0.2)
            if cached_file.exists() and cached_file.stat().st_size > 0:
                record_cache_access(cache_key, str(cached_file), cached_file.stat().st_size)
                return await serve_file_segment(request, cached_file)
        await asyncio.sleep(poll_interval)
        waited += poll_interval

    logger.warning(f"Segment {cache_key} not ready after {max_wait}s wait")
    return web.Response(text="Segment generation timeout", status=504)

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
self.addEventListener('install', (e) => {
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  // Direct pass-through to let browser/Hls.js manage requests naturally
});
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
  
  <!-- Modern High-Compatibility HLS Engine -->
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
  
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

    /* Hide Chromium native overflow button */
    video::-webkit-media-controls-overflow-button,
    video::-webkit-media-controls-overflow-menu-list,
    video::-internal-media-controls-overflow-button {
      display: none !important;
      opacity: 0 !important;
      pointer-events: none !important;
    }

    /* Top-Right Settings / Action Wrap (YouTube / Netflix Style) */
    .custom-more-wrap {
      position: absolute;
      top: 16px;
      right: 16px;
      width: 40px;
      height: 40px;
      z-index: 2147483647;
      display: flex;
      align-items: center;
      justify-content: center;
      user-select: none;
      transition: opacity 0.35s ease, transform 0.2s ease;
    }
    /* Shift left on Mobile / iOS to avoid native top-right mute speaker button */
    @media (max-width: 900px), (hover: none) and (pointer: coarse) {
      .custom-more-wrap {
        top: 12px;
        right: 68px;
      }
      .more-menu {
        right: -52px;
      }
    }
    .custom-more-wrap.fade-out {
      opacity: 0;
      pointer-events: none;
    }
    .custom-more-btn {
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: rgba(18, 22, 30, 0.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.16);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      outline: none;
      transition: all 0.2s ease;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6);
    }
    .custom-more-btn:hover, .custom-more-wrap.active-menu .custom-more-btn {
      background: rgba(56, 189, 248, 0.25);
      border-color: #38bdf8;
      color: #38bdf8;
      transform: scale(1.08) rotate(30deg);
    }
    .custom-more-btn svg {
      width: 20px;
      height: 20px;
    }

    /* Popup Menus */
    .more-menu {
      display: none;
      position: absolute;
      top: calc(100% + 10px);
      right: 0;
      bottom: auto;
      max-height: calc(100vh - 80px);
      overflow-y: auto;
      background: rgba(22, 27, 38, 0.96);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 14px;
      padding: 6px;
      min-width: 235px;
      box-shadow: 0 16px 45px rgba(0, 0, 0, 0.85);
      flex-direction: column;
      gap: 2px;
      z-index: 2147483647;
    }
    .more-menu.show {
      display: flex;
      animation: menuPopDown 0.18s cubic-bezier(0.16, 1, 0.3, 1);
    }
    @keyframes menuPopDown {
      from { opacity: 0; transform: translateY(-8px) scale(0.96); }
      to { opacity: 1; transform: translateY(0); }
    }
    .menu-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border-radius: 9px;
      color: #f1f5f9;
      font-size: 0.88rem;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
    }
    .menu-item:hover {
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }
    .menu-item-left {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .item-icon {
      width: 18px;
      height: 18px;
      color: #94a3b8;
      flex-shrink: 0;
    }
    .menu-item:hover .item-icon {
      color: #38bdf8;
    }
    .menu-item-right {
      display: flex;
      align-items: center;
      gap: 6px;
      color: #94a3b8;
      font-size: 0.82rem;
    }
    .arrow { font-size: 1.15rem; line-height: 1; color: #64748b; }
    .badge-value { color: #38bdf8; font-weight: 700; }
    .menu-divider {
      height: 1px;
      background: rgba(255, 255, 255, 0.08);
      margin: 4px 6px;
    }
    .submenu-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      color: #94a3b8;
      font-size: 0.84rem;
      font-weight: 600;
      cursor: pointer;
      border-radius: 8px;
      transition: background 0.15s, color 0.15s;
    }
    .submenu-header:hover {
      color: #fff;
      background: rgba(255, 255, 255, 0.08);
    }
    .back-arrow { font-size: 1.3rem; line-height: 1; }
    .sub-item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 9px 12px;
      border-radius: 8px;
      color: #cbd5e1;
      font-size: 0.85rem;
      cursor: pointer;
      transition: background 0.15s, color 0.15s;
    }
    .sub-item:hover {
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }
    .sub-item.active {
      color: #38bdf8;
      font-weight: 700;
      background: rgba(56, 189, 248, 0.15);
    }
    .check-mark {
      width: 14px;
      font-size: 0.9rem;
      font-weight: bold;
      visibility: hidden;
    }
    .sub-item.active .check-mark {
      visibility: visible;
    }
  </style>
</head>
<body>
  <div id="player-container">
    <video id="video-player" src="__STREAM_URL__" playsinline controls controlslist="nodownload noplaybackrate noremoteplayback" disablepictureinpicture autoplay preload="auto"></video>

    <!-- Top-Right Settings & Options Wrap (YouTube / Netflix Style) -->
    <div class="custom-more-wrap" id="custom-more-wrap">
      <button class="custom-more-btn" id="custom-more-btn" type="button" title="การตั้งค่าและตัวเลือกเพิ่มเติม">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
      </button>

      <!-- Main More Menu -->
      <div class="more-menu" id="more-menu">
        <!-- 1. Quality (First Item) -->
        <div class="menu-item" id="btn-open-quality">
          <div class="menu-item-left">
            <svg class="item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <polygon points="23 7 16 12 23 17 23 7"></polygon>
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2"></rect>
            </svg>
            <span>ความละเอียด</span>
          </div>
          <div class="menu-item-right">
            <span class="badge-value" id="current-quality-val">AUTO</span>
            <span class="arrow">›</span>
          </div>
        </div>

        <div class="menu-divider"></div>

        <!-- 2. Playback Speed -->
        <div class="menu-item" id="btn-open-speed">
          <div class="menu-item-left">
            <svg class="item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"></circle>
              <polyline points="12 6 12 12 16 14"></polyline>
            </svg>
            <span>ความเร็วในการเล่น</span>
          </div>
          <div class="menu-item-right">
            <span class="badge-value" id="current-speed-val">ปกติ</span>
            <span class="arrow">›</span>
          </div>
        </div>

        <!-- 3. Picture in Picture -->
        <div class="menu-item" id="btn-pip">
          <div class="menu-item-left">
            <svg class="item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2"></rect>
              <rect x="12" y="11" width="8" height="7" rx="1"></rect>
            </svg>
            <span>การแสดงภาพซ้อนภาพ</span>
          </div>
        </div>

        <!-- 4. Direct Download -->
        <div class="menu-item" id="btn-download">
          <div class="menu-item-left">
            <svg class="item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>ดาวน์โหลด</span>
          </div>
        </div>
      </div>

      <!-- Submenu: Quality Selection -->
      <div class="more-menu submenu" id="submenu-quality">
        <div class="submenu-header" id="btn-back-quality">
          <span class="back-arrow">‹</span>
          <span>ความละเอียด</span>
        </div>
        <div class="menu-divider"></div>
        <div class="sub-item active" data-q="auto" data-label="AUTO">
          <span class="check-mark">✓</span><span>AUTO</span>
        </div>
        <div class="sub-item" data-q="direct" data-label="UHD">
          <span class="check-mark">✓</span><span>UHD</span>
        </div>
        <div class="sub-item" data-q="hls_1080" data-label="FHD">
          <span class="check-mark">✓</span><span>FHD</span>
        </div>
        <div class="sub-item" data-q="hls_720" data-label="HD">
          <span class="check-mark">✓</span><span>HD</span>
        </div>
        <div class="sub-item" data-q="hls_480" data-label="SD">
          <span class="check-mark">✓</span><span>SD</span>
        </div>
      </div>

      <!-- Submenu: Speed Selection -->
      <div class="more-menu submenu" id="submenu-speed">
        <div class="submenu-header" id="btn-back-speed">
          <span class="back-arrow">‹</span>
          <span>ความเร็วในการเล่น</span>
        </div>
        <div class="menu-divider"></div>
        <div class="sub-item" data-speed="0.5" data-slabel="0.5x"><span class="check-mark">✓</span><span>0.5x</span></div>
        <div class="sub-item" data-speed="0.75" data-slabel="0.75x"><span class="check-mark">✓</span><span>0.75x</span></div>
        <div class="sub-item active" data-speed="1" data-slabel="ปกติ"><span class="check-mark">✓</span><span>ปกติ</span></div>
        <div class="sub-item" data-speed="1.25" data-slabel="1.25x"><span class="check-mark">✓</span><span>1.25x</span></div>
        <div class="sub-item" data-speed="1.5" data-slabel="1.5x"><span class="check-mark">✓</span><span>1.5x</span></div>
        <div class="sub-item" data-speed="2" data-slabel="2x"><span class="check-mark">✓</span><span>2x</span></div>
      </div>
    </div>
  </div>

  <script>
    const hlsUrl = "__HLS_URL__";
    const streamFallbackUrl = "__STREAM_URL__";
    const dlUrl = "/dl/__CHAT_ID__/__MSG_ID__";
    const video = document.getElementById('video-player');
    const container = document.getElementById('player-container');
    const moreWrap = document.getElementById('custom-more-wrap');
    const moreBtn = document.getElementById('custom-more-btn');
    const moreMenu = document.getElementById('more-menu');
    const submenuQuality = document.getElementById('submenu-quality');
    const submenuSpeed = document.getElementById('submenu-speed');
    const curQualityVal = document.getElementById('current-quality-val');
    const curSpeedVal = document.getElementById('current-speed-val');

    let hlsInstance = null;

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    }

    function initPlayer() {
      const origRequestFullscreen = video.requestFullscreen || video.webkitRequestFullscreen;
      video.requestFullscreen = function() {
        if (container.requestFullscreen) return container.requestFullscreen();
        if (container.webkitRequestFullscreen) return container.webkitRequestFullscreen();
        if (origRequestFullscreen) return origRequestFullscreen.call(video);
      };
      if (video.webkitRequestFullscreen) video.webkitRequestFullscreen = video.requestFullscreen;
      playDirect();
    }

    function playDirect() {
      if (hlsInstance) {
        try { hlsInstance.destroy(); } catch (e) {}
        hlsInstance = null;
      }
      video.src = streamFallbackUrl;
      video.load();
      video.play().catch(() => {});
    }

    function playHls(targetUrl) {
      if (window.Hls && Hls.isSupported()) {
        if (hlsInstance) {
          try { hlsInstance.destroy(); } catch (e) {}
        }
        const hls = new Hls({
          maxBufferLength: 20,
          maxMaxBufferLength: 40,
          enableWorker: true,
          lowLatencyMode: false,
          backBufferLength: 20
        });
        hlsInstance = hls;
        hls.loadSource(targetUrl || hlsUrl);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.play().catch(() => {});
        });
        hls.on(Hls.Events.ERROR, (e, data) => {
          if (data.fatal) {
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
              hls.startLoad();
            } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              hls.recoverMediaError();
            } else {
              playDirect();
            }
          }
        });
      } else {
        playDirect();
      }
    }

    function closeAllMenus() {
      moreMenu.classList.remove('show');
      submenuQuality.classList.remove('show');
      submenuSpeed.classList.remove('show');
      moreWrap.classList.remove('active-menu');
    }

    function isAnyMenuOpen() {
      return moreMenu.classList.contains('show') || 
             submenuQuality.classList.contains('show') || 
             submenuSpeed.classList.contains('show');
    }

    moreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (isAnyMenuOpen()) {
        closeAllMenus();
      } else {
        moreMenu.classList.add('show');
        moreWrap.classList.add('active-menu');
        moreWrap.classList.remove('fade-out');
      }
    });

    document.getElementById('btn-open-quality').addEventListener('click', (e) => {
      e.stopPropagation();
      moreMenu.classList.remove('show');
      submenuQuality.classList.add('show');
    });

    document.getElementById('btn-back-quality').addEventListener('click', (e) => {
      e.stopPropagation();
      submenuQuality.classList.remove('show');
      moreMenu.classList.add('show');
    });

    document.querySelectorAll('#submenu-quality .sub-item').forEach((item) => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const mode = item.getAttribute('data-q');
        const label = item.getAttribute('data-label');
        curQualityVal.innerText = label;

        document.querySelectorAll('#submenu-quality .sub-item').forEach((i) => i.classList.remove('active'));
        item.classList.add('active');

        const t = video.currentTime;
        if (mode === 'auto' || mode === 'direct') {
          playDirect();
        } else if (mode === 'hls_720') {
          playHls('/hls/__CHAT_ID__/__MSG_ID__/720p/index.m3u8');
        } else if (mode === 'hls_480') {
          playHls('/hls/__CHAT_ID__/__MSG_ID__/480p/index.m3u8');
        } else {
          playHls(hlsUrl);
        }
        if (t > 0) video.currentTime = t;
        closeAllMenus();
      });
    });

    document.getElementById('btn-open-speed').addEventListener('click', (e) => {
      e.stopPropagation();
      moreMenu.classList.remove('show');
      submenuSpeed.classList.add('show');
    });

    document.getElementById('btn-back-speed').addEventListener('click', (e) => {
      e.stopPropagation();
      submenuSpeed.classList.remove('show');
      moreMenu.classList.add('show');
    });

    document.querySelectorAll('#submenu-speed .sub-item').forEach((item) => {
      item.addEventListener('click', (e) => {
        e.stopPropagation();
        const sp = parseFloat(item.getAttribute('data-speed'));
        const slabel = item.getAttribute('data-slabel');
        video.playbackRate = sp;
        curSpeedVal.innerText = slabel;

        document.querySelectorAll('#submenu-speed .sub-item').forEach((i) => i.classList.remove('active'));
        item.classList.add('active');
        closeAllMenus();
      });
    });

    document.getElementById('btn-pip').addEventListener('click', (e) => {
      e.stopPropagation();
      closeAllMenus();
      if (document.pictureInPictureElement) {
        document.exitPictureInPicture().catch(() => {});
      } else if (document.pictureInPictureEnabled && video) {
        video.requestPictureInPicture().catch(() => {});
      }
    });

    document.getElementById('btn-download').addEventListener('click', (e) => {
      e.stopPropagation();
      closeAllMenus();
      window.location.href = dlUrl;
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#custom-more-wrap')) {
        closeAllMenus();
      }
    });

    let idleTimer = null;
    function wakeControl() {
      moreWrap.classList.remove('fade-out');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (!isAnyMenuOpen() && !video.paused) {
          moreWrap.classList.add('fade-out');
        }
      }, 3500);
    }

    document.addEventListener('mousemove', wakeControl);
    document.addEventListener('touchstart', wakeControl);
    video.addEventListener('play', wakeControl);
    video.addEventListener('pause', () => {
      moreWrap.classList.remove('fade-out');
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

def _is_smart_tv(request: web.Request) -> bool:
    """Detect Smart TV browsers via User-Agent string."""
    ua = (request.headers.get("User-Agent", "") or "").lower()
    tv_keywords = [
        "webos",        # LG webOS
        "smarttv",      # Generic Smart TV
        "smart-tv",
        "tizen",        # Samsung Tizen
        "netcast",      # LG NetCast (older)
        "tv browser",
        "viera",        # Panasonic
        "bravia",       # Sony
        "firetv",       # Amazon Fire TV
        "roku",         # Roku
        "crkey",        # Chromecast
        "androidtv",    # Android TV
        "hbbtv",        # Hybrid broadcast broadband TV
        "lge",          # LG Electronics
    ]
    return any(kw in ua for kw in tv_keywords)

# TV player: HLS via hls.js (each .ts segment = no moov issues).
# Large play button for Magic Remote user-gesture trigger.
TV_PLAYER_HTML = '''<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__FILE_NAME__</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body {
      width: 100%; height: 100%;
      background: #000;
      overflow: hidden;
    }
    video {
      position: fixed;
      top: 0; left: 0;
      width: 100%; height: 100%;
      object-fit: contain;
      background: #000;
    }
    #play-btn {
      position: fixed;
      top: 0; left: 0;
      width: 100%; height: 100%;
      background: rgba(0,0,0,0.7);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 9999;
      border: none;
      outline: none;
      flex-direction: column;
      gap: 24px;
    }
    #play-btn:focus { outline: 4px solid #38bdf8; }
    #play-icon {
      width: 140px; height: 140px;
      background: rgba(56, 189, 248, 0.9);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 0 60px rgba(56, 189, 248, 0.5);
    }
    #play-icon svg { width: 60px; height: 60px; fill: #fff; margin-left: 8px; }
    #play-btn:hover #play-icon,
    #play-btn:focus #play-icon {
      background: rgba(56, 189, 248, 1);
      transform: scale(1.1);
      box-shadow: 0 0 80px rgba(56, 189, 248, 0.8);
    }
    #play-text {
      color: #94a3b8;
      font-family: sans-serif;
      font-size: 1.2rem;
    }
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <video id="v" controls preload="auto"></video>
  <button id="play-btn" autofocus>
    <div id="play-icon">
      <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
    </div>
    <div id="play-text">กดเพื่อเล่นวิดีโอ</div>
  </button>
  <script>
    var btn = document.getElementById('play-btn');
    var vid = document.getElementById('v');
    var hlsUrl = '__HLS_URL__';
    var directUrl = '__STREAM_URL__';
    var hasFaststart = __HAS_FASTSTART__;
    var started = false;

    function startPlay() {
      if (started) return;
      started = true;
      btn.className = 'hidden';

      // If Faststart is ready on local SSD, play direct MP4 for 100% native hardware acceleration!
      if (hasFaststart) {
        vid.src = directUrl;
        vid.play();
        return;
      }

      if (window.Hls && Hls.isSupported()) {
        var hls = new Hls({
          maxBufferLength: 30,
          maxMaxBufferLength: 60,
          enableWorker: false,
          lowLatencyMode: false
        });
        hls.loadSource(hlsUrl);
        hls.attachMedia(vid);
        hls.on(Hls.Events.MANIFEST_PARSED, function() {
          vid.play();
        });
        hls.on(Hls.Events.ERROR, function(e, data) {
          if (data.fatal) {
            vid.src = directUrl;
            vid.play();
          }
        });
      } else {
        vid.src = directUrl;
        vid.play();
      }
    }

    btn.onclick = startPlay;
    btn.addEventListener('keydown', function(e) {
      if (e.keyCode === 13 || e.keyCode === 32) {
        e.preventDefault();
        startPlay();
      }
    });
  </script>
</body>
</html>'''

async def handle_tv_stream(request: web.Request):
    """FFmpeg remux endpoint: moves moov atom to front for progressive TV playback."""
    try:
        chat_id = int(request.match_info["chat_id"])
        msg_id = int(request.match_info["msg_id"])
    except (ValueError, KeyError):
        return web.Response(text="Invalid parameters", status=400)

    stream_url = f"http://127.0.0.1:{PORT}/stream/{chat_id}/{msg_id}"

    # FFmpeg remux: read from local stream, output faststart MP4 to stdout
    cmd = [
        "ffmpeg", "-y",
        "-i", stream_url,
        "-c", "copy",                   # No re-encoding, just remux
        "-movflags", "+faststart+frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1"
    ]

    logger.info(f"TV-Stream: Starting FFmpeg faststart remux for {chat_id}/{msg_id}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
    except Exception as e:
        logger.error(f"TV-Stream: Failed to start FFmpeg: {e}")
        return web.Response(text="Stream unavailable", status=500)

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "none",
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    }

    response = web.StreamResponse(status=200, headers=headers)
    await response.prepare(request)

    try:
        while True:
            chunk = await proc.stdout.read(256 * 1024)  # 256KB chunks
            if not chunk:
                break
            await response.write(chunk)
    except (asyncio.CancelledError, ConnectionResetError):
        proc.kill()
    except Exception as e:
        logger.warning(f"TV-Stream: Error during remux streaming: {e}")
        proc.kill()
    finally:
        try:
            await proc.wait()
        except Exception:
            pass

    await response.write_eof()
    return response

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
    stream_url = f"/stream/{chat_id}/{msg_id}"
    tv_stream_url = f"/tv-stream/{chat_id}/{msg_id}"

    # Smart TV → serve HLS player with hls.js (each .ts segment has no moov issues)
    faststart_ready = get_faststart_path(chat_id, msg_id) is not None
    if _is_smart_tv(request):
        logger.info(f"Smart TV detected (UA: {request.headers.get('User-Agent', '')[:80]}), faststart={faststart_ready} for {chat_id}/{msg_id}")
        hls_master_url = f"/hls/{chat_id}/{msg_id}/master.m3u8"
        html_content = TV_PLAYER_HTML.replace("__FILE_NAME__", html.escape(file_name)) \
                                     .replace("__HLS_URL__", hls_master_url) \
                                     .replace("__STREAM_URL__", stream_url) \
                                     .replace("__HAS_FASTSTART__", "true" if faststart_ready else "false")
    else:
        # Desktop/Mobile → full-featured player with HLS + quality switcher
        hls_master_url = f"/hls/{chat_id}/{msg_id}/master.m3u8"
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

    # In channels/groups or when media already has a caption, do not send a duplicate reply message.
    # All details, player, and downloads are managed via TG-Drive (https://drive.capt-th.work/) & GAPT-CINEMA.
    has_caption = bool(getattr(event.message, "message", None) and event.message.message.strip())
    if event.is_channel or has_caption:
        logger.info(f"Indexed media {msg_id} in chat {chat_id} cleanly (no clutter reply).")
        return

    # In private DM without caption, reply with only the clean file name
    icon = "🎬" if is_video else "📁"
    text = f"{icon} <b>{html.escape(name)}</b>"
    try:
        await event.reply(text, parse_mode="html", link_preview=False)
    except Exception as e:
        logger.error(f"Failed to reply: {e}")

@client.on(events.MessageEdited)
async def on_message_edited(event):
    if not event.message or not event.message.media:
        return
    file_info = get_file_info(event.message)
    if not file_info:
        return
    chat_id = event.chat_id
    msg_id = event.message.id
    save_db_video(chat_id, msg_id, file_info)
    logger.info(f"Updated video in db from Telegram edit: {chat_id}/{msg_id} -> '{file_info['name']}'")

@client.on(events.MessageDeleted)
async def on_message_deleted(event):
    if not getattr(event, "deleted_ids", None):
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for did in event.deleted_ids:
            cur.execute("DELETE FROM videos WHERE msg_id = ?", (did,))
        conn.commit()
        conn.close()
        logger.info(f"Automatically pruned deleted Telegram messages from cinema db: {event.deleted_ids}")
    except Exception as e:
        logger.error(f"Error handling message deletion: {e}")

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
    app.router.add_get("/cinema-icon.png", handle_cinema_icon)
    app.router.add_get("/", handle_cinema_portal)
    app.router.add_get("/cinema", handle_cinema_portal)
    app.router.add_get("/api/movies", handle_api_movies)
    app.router.add_get("/health", handle_index)
    app.router.add_get("/sw.js", handle_service_worker)
    app.router.add_get("/watch/{chat_id}/{msg_id}", handle_watch)
    app.router.add_get("/stream/{chat_id}/{msg_id}", handle_stream)
    app.router.add_get("/tv-stream/{chat_id}/{msg_id}", handle_tv_stream)
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
