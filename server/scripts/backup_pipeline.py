import os
import re
import sys
import time
import shutil
import sqlite3
import logging
import requests
import subprocess
from pathlib import Path
from io import BytesIO
from PIL import Image

# ─── LOGGING & PATH CONFIGURATION ──────────────────────────────────────────────

BASE_DIR = Path("/home/ubuntu/drugtest-backup")
MEDIA_DIR = BASE_DIR / "media"
IMAGES_DIR = MEDIA_DIR / "images"
VIDEOS_DIR = MEDIA_DIR / "videos"
TEMP_DIR = BASE_DIR / "temp"
DB_DIR = BASE_DIR / "db"
DB_PATH = DB_DIR / "drugtest.db"
LOG_PATH = BASE_DIR / "pipeline.log"

# Ensure directories exist
for p in [IMAGES_DIR, VIDEOS_DIR, TEMP_DIR, DB_DIR]:
    p.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("drugtest_pipeline")

# Admin JWT token (generated with default-jwt-secret-key-713)
API_TOKEN = os.environ.get(
    "API_TOKEN",
    "eyJ0eXAiOiAiSldUIiwgImFsZyI6ICJIUzI1NiJ9.eyJpZCI6IDAsICJ1c2VybmFtZSI6ICJhZG1pbiIsICJyb2xlIjogImFkbWluIiwgInJhbmtfbmFtZSI6ICJcdTBlMWNcdTBlMzlcdTBlNDlcdTBlMTRcdTBlMzlcdTBlNDFcdTBlMjVcdTBlMjNcdTBlMzBcdTBlMWFcdTBlMWEiLCAiYWZmaWxpYXRpb24iOiAiXHUwZTJiXHUwZTIxXHUwZTM5XHUwZTQ4XHUwZTAxXHUwZTMyXHUwZTIzXHUwZTAyXHUwZTQ4XHUwZTMyXHUwZTI3IFx1MGUxYi43MSBcdTBlMWVcdTBlMzFcdTBlMTkuNzEzIiwgInBob25lIjogIiIsICJleHAiOiAxODIzNTgwMDMxfQ.A8tyeemcPvLhcIeOPb-i0roCbIM92TjNd0FMbHCWVVI"
)
API_URL = os.environ.get("API_URL", "https://api-office.capt-th.work/api/admin/drug-test/records")

# ─── CHRONOLOGICAL CALENDAR ORDER MAPPING ─────────────────────────────────────

MONTH_ORDER = {
    # 2567 (2024)
    "ต.ค.67": 202410,
    "ตุลาคม 2567": 202410,
    "พ.ย.67": 202411,
    "พฤศจิกายน 2567": 202411,
    "ธ.ค.67": 202412,
    "ธันวาคม 2567": 202412,

    # 2568 (2025)
    "ม.ค.68": 202501,
    "มกราคม 2568": 202501,
    "ก.พ.68": 202502,
    "กุมภาพันธ์ 2568": 202502,
    "มี.ค.68": 202503,
    "มีนาคม 2568": 202503,
    "เม.ย.68": 202504,
    "เมษายน 2568": 202504,
    "พ.ค.68": 202505,
    "พฤษภาคม 2568": 202505,
    "มิ.ย.68": 202506,
    "มิถุนายน 2568": 202506,
    "ก.ค.68": 202507,
    "กรกฎาคม 2568": 202507,
    "ส.ค.68": 202508,
    "สิงหาคม 2568": 202508,
    "ก.ย.68": 202509,
    "กันยายน 2568": 202509,
    "ต.ค.68": 202510,
    "ตุลาคม 2568": 202510,
    "พ.ย.68": 202511,
    "พฤศจิกายน 2568": 202511,
    "ธ.ค.68": 202512,
    "ธันวาคม 2568": 202512,

    # 2569 (2026)
    "ม.ค.69": 202601,
    "มกราคม 2569": 202601,
    "ก.พ.69": 202602,
    "กุมภาพันธ์ 2569": 202602,
    "มี.ค.69": 202603,
    "มีนาคม 2569": 202603,
    "เม.ย.69": 202604,
    "เมษายน 2569": 202604,
    "พ.ค.69": 202605,
    "พฤษภาคม 2569": 202605,
    "มิ.ย.69": 202606,
    "มิถุนายน 2569": 202606,
    "ก.ค.69": 202607,
    "กรกฎาคม 2569": 202607,
    "ส.ค.69": 202608,
    "สิงหาคม 2569": 202608,
    "ก.ย.69": 202609,
    "กันยายน 2569": 202609,
    "ต.ค.69": 202610,
    "ตุลาคม 2569": 202610,
}

MONTH_NORMALIZE = {
    # 2567 (2024)
    "ต.ค.67": "ตุลาคม 2567",
    "พ.ย.67": "พฤศจิกายน 2567",
    "ธ.ค.67": "ธันวาคม 2567",

    # 2568 (2025)
    "ม.ค.68": "มกราคม 2568",
    "ก.พ.68": "กุมภาพันธ์ 2568",
    "มี.ค.68": "มีนาคม 2568",
    "เม.ย.68": "เมษายน 2568",
    "พ.ค.68": "พฤษภาคม 2568",
    "มิ.ย.68": "มิถุนายน 2568",
    "ก.ค.68": "กรกฎาคม 2568",
    "ส.ค.68": "สิงหาคม 2568",
    "ก.ย.68": "กันยายน 2568",
    "ต.ค.68": "ตุลาคม 2568",
    "พ.ย.68": "พฤศจิกายน 2568",
    "ธ.ค.68": "ธันวาคม 2568",

    # 2569 (2026)
    "ม.ค.69": "มกราคม 2569",
    "ก.พ.69": "กุมภาพันธ์ 2569",
    "มี.ค.69": "มีนาคม 2569",
    "เม.ย.69": "เมษายน 2569",
    "พ.ค.69": "พฤษภาคม 2569",
    "มิ.ย.69": "มิถุนายน 2569",
    "ก.ค.69": "กรกฎาคม 2569",
    "ส.ค.69": "สิงหาคม 2569",
    "ก.ย.69": "กันยายน 2569",
    "ต.ค.69": "ตุลาคม 2569",
}

def get_sort_key(date_str: str, month_str: str) -> int:
    """Returns integer YYYYMMDD for strict calendar sorting (e.g. 20241016)"""
    month_val = MONTH_ORDER.get((month_str or "").strip(), 0)
    day = 1
    if date_str:
        parts = date_str.strip().split("/")
        if len(parts) == 3:
            try:
                day = int(parts[0])
                m_part = int(parts[1])
                y_part = int(parts[2])
                if y_part > 2500:
                    y_part -= 543
                if 1 <= m_part <= 12 and 1 <= day <= 31:
                    return y_part * 10000 + m_part * 100 + day
            except ValueError:
                pass
    if month_val > 0:
        return month_val * 100 + (day if 1 <= day <= 31 else 1)
    return 99999999

# ─── DATABASE INITIALIZATION ──────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        name TEXT,
        month TEXT,
        date TEXT,
        result TEXT,
        photo1_id TEXT,
        photo2_id TEXT,
        photo3_id TEXT,
        video_id TEXT,
        synced_at INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS media_files (
        file_id TEXT PRIMARY KEY,
        media_type TEXT,
        original_url TEXT,
        file_size_bytes INTEGER DEFAULT 0,
        width INTEGER DEFAULT 0,
        height INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        error_msg TEXT,
        processed_at INTEGER,
        sort_date INTEGER DEFAULT 99999999
    );
    """)

    # Ensure sort_date column exists for older tables
    try:
        cur.execute("ALTER TABLE media_files ADD COLUMN sort_date INTEGER DEFAULT 99999999;")
    except Exception:
        pass

    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_sort ON media_files(status, media_type, sort_date, retry_count);")
    conn.commit()
    conn.close()

def extract_file_id(url: str) -> str:
    if not url:
        return ""
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{25,}$', url.strip()):
        return url.strip()
    return ""

# ─── SYNC RECORDS FROM WORKER API ─────────────────────────────────────────────

def sync_records():
    logger.info(f"Syncing records from {API_URL}...")
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    try:
        resp = requests.get(API_URL, headers=headers, timeout=25)
        if resp.status_code != 200:
            logger.error(f"API error: status {resp.status_code}")
            return 0
        data = resp.json()
        records = data.get("records", [])
        logger.info(f"Fetched {len(records)} records from API.")

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        now = int(time.time())
        new_records = 0
        queued_files = 0

        for r in records:
            ts = r.get("timestamp", "")
            name = r.get("name", "")
            raw_month = (r.get("month", "") or "").strip()
            month = MONTH_NORMALIZE.get(raw_month, raw_month)
            date = r.get("date", "")
            result = r.get("result", "")

            sort_key = get_sort_key(date, month)

            p1_id = extract_file_id(r.get("photo1", ""))
            p2_id = extract_file_id(r.get("photo2", ""))
            p3_id = extract_file_id(r.get("photo3", ""))
            v_id = extract_file_id(r.get("video", ""))

            # Register photos (photo1 and photo2 are always photos)
            for p_id in [p1_id, p2_id]:
                if p_id:
                    cur.execute("""
                        INSERT OR IGNORE INTO media_files (file_id, media_type, original_url, status, sort_date)
                        VALUES (?, 'photo', ?, 'pending', ?)
                    """, (p_id, f"https://drive.google.com/open?id={p_id}", sort_key))
                    if cur.rowcount > 0:
                        queued_files += 1

            # Register video (v_id or p3_id is video evidence)
            actual_video_id = v_id if v_id else p3_id
            if actual_video_id:
                cur.execute("""
                    INSERT OR IGNORE INTO media_files (file_id, media_type, original_url, status, sort_date)
                    VALUES (?, 'video', ?, 'pending', ?)
                """, (actual_video_id, f"https://drive.google.com/open?id={actual_video_id}", sort_key))
                if cur.rowcount > 0:
                    queued_files += 1

            # Insert record if not exists
            cur.execute("""
                INSERT OR IGNORE INTO records (timestamp, name, month, date, result, photo1_id, photo2_id, photo3_id, video_id, synced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (ts, name, month, date, result, p1_id, p2_id, p3_id, actual_video_id, now))
            if cur.rowcount > 0:
                new_records += 1

        conn.commit()
        conn.close()
        logger.info(f"Sync complete. New records: {new_records}, Newly queued media: {queued_files}")
        return len(records)
    except Exception as e:
        logger.error(f"Sync failed: {e}", exc_info=True)
        return 0

# ─── MEDIA PROCESSING WORKERS ─────────────────────────────────────────────────

def process_single_photo(file_id: str) -> bool:
    out_file = IMAGES_DIR / f"{file_id}.webp"
    if out_file.exists() and out_file.stat().st_size > 1024:
        return True

    cdn_url = f"https://lh3.googleusercontent.com/d/{file_id}=s0"
    logger.info(f"Downloading photo {file_id} from {cdn_url}")
    
    resp = requests.get(cdn_url, timeout=20)
    if resp.status_code != 200:
        alt_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        resp = requests.get(alt_url, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"Download failed with status {resp.status_code}")

    img = Image.open(BytesIO(resp.content))
    orig_w, orig_h = img.size

    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    max_dim = 1200
    if max(orig_w, orig_h) > max_dim:
        if orig_w >= orig_h:
            new_w = max_dim
            new_h = int(orig_h * (max_dim / orig_w))
        else:
            new_h = max_dim
            new_w = int(orig_w * (max_dim / orig_h))
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    else:
        new_w, new_h = orig_w, orig_h

    img.save(out_file, "WEBP", quality=82, method=6)
    out_size = out_file.stat().st_size
    logger.info(f"Optimized photo {file_id}: {orig_w}x{orig_h} -> {new_w}x{new_h} WebP ({out_size/1024:.1f} KB)")
    return True

def process_single_video(file_id: str) -> bool:
    out_file = VIDEOS_DIR / f"{file_id}.mp4"
    if out_file.exists() and out_file.stat().st_size > 50000:
        return True

    temp_raw = TEMP_DIR / f"{file_id}.raw"
    session = requests.Session()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    
    logger.info(f"Downloading video {file_id} from Google Drive...")
    resp = session.get(url, stream=True, timeout=30)
    
    ct = resp.headers.get("Content-Type", "")
    if "download_warning" in ct or "text/html" in ct:
        html_text = resp.text
        m = re.search(r'confirm=([0-9A-Za-z_-]+)', html_text)
        if m:
            confirm_token = m.group(1)
            resp = session.get(f"{url}&confirm={confirm_token}", stream=True, timeout=30)

    if resp.status_code != 200:
        raise Exception(f"Video download failed: HTTP {resp.status_code}")

    with open(temp_raw, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)

    raw_size = temp_raw.stat().st_size
    logger.info(f"Downloaded raw video {file_id}: {raw_size/1024/1024:.2f} MB")

    cmd = [
        "nice", "-n", "19",
        "/usr/bin/ffmpeg", "-y",
        "-i", str(temp_raw),
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "slow",
        "-vf", "scale=min(720\\,iw):-2",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_file)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if temp_raw.exists():
        temp_raw.unlink()

    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="replace")[-400:]
        raise Exception(f"FFmpeg transcode failed: {err}")

    out_size = out_file.stat().st_size
    saved_pct = (1 - (out_size / raw_size)) * 100 if raw_size > 0 else 0
    logger.info(f"Transcoded video {file_id}: {raw_size/1024/1024:.2f}MB -> {out_size/1024/1024:.2f}MB ({saved_pct:.1f}% saved)")
    return True

# ─── MAIN BACKGROUND PIPELINE LOOP ─────────────────────────────────────────────

def run_pipeline():
    init_db()
    logger.info("Drug Test Background Backup Pipeline started (Chronological Calendar Sorting).")

    while True:
        try:
            # Sync records from API
            sync_records()

            # Process pending media files strictly in chronological calendar order
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            # Fetch balanced batch ordered by sort_date ASC (earliest date first)
            cur.execute("""
                SELECT file_id, media_type, retry_count FROM (
                    SELECT file_id, media_type, retry_count, sort_date, rowid FROM media_files
                    WHERE (status = 'pending' OR (status = 'failed' AND retry_count < 3)) AND media_type = 'video'
                    ORDER BY sort_date ASC, rowid ASC LIMIT 10
                )
                UNION ALL
                SELECT file_id, media_type, retry_count FROM (
                    SELECT file_id, media_type, retry_count, sort_date, rowid FROM media_files
                    WHERE (status = 'pending' OR (status = 'failed' AND retry_count < 3)) AND media_type = 'photo'
                    ORDER BY sort_date ASC, rowid ASC LIMIT 25
                )
            """)
            items = cur.fetchall()
            conn.close()

            if not items:
                logger.info("All media up to date! Sleeping 10 minutes before next sync...")
                time.sleep(600)
                continue

            logger.info(f"Found {len(items)} items pending processing in chronological order.")

            for file_id, media_type, retry_count in items:
                # Disk safeguard: ensure at least 5 GB free for Binance Bot safety
                total, used, free = shutil.disk_usage("/")
                free_gb = free / (1024**3)
                if free_gb < 5.0:
                    logger.warning(f"Disk space low ({free_gb:.1f} GB free). Pausing pipeline for 30 minutes!")
                    time.sleep(1800)
                    break

                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE media_files SET status = 'processing' WHERE file_id = ?", (file_id,))
                conn.commit()

                try:
                    if media_type == "photo":
                        process_single_photo(file_id)
                        out_size = (IMAGES_DIR / f"{file_id}.webp").stat().st_size
                    else:
                        process_single_video(file_id)
                        out_size = (VIDEOS_DIR / f"{file_id}.mp4").stat().st_size

                    cur.execute("""
                        UPDATE media_files
                        SET status = 'completed', file_size_bytes = ?, processed_at = ?, error_msg = NULL
                        WHERE file_id = ?
                    """, (out_size, int(time.time()), file_id))
                    conn.commit()

                    sleep_time = 2.0 if media_type == "photo" else 4.0
                    time.sleep(sleep_time)

                except Exception as e:
                    logger.error(f"Error processing {media_type} {file_id}: {e}")
                    cur.execute("""
                        UPDATE media_files
                        SET status = 'failed', retry_count = retry_count + 1, error_msg = ?
                        WHERE file_id = ?
                    """, (str(e), file_id))
                    conn.commit()
                    time.sleep(5.0)

                finally:
                    conn.close()

        except Exception as e:
            logger.error(f"Pipeline loop error: {e}", exc_info=True)
            time.sleep(30)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run one sync and process first batch, then exit")
    parser.add_argument("--limit", type=int, default=5, help="Limit number of items to process in --once mode")
    args = parser.parse_args()

    if args.once:
        init_db()
        sync_records()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT file_id, media_type, retry_count
            FROM media_files
            WHERE status = 'pending'
            ORDER BY sort_date ASC, rowid ASC
            LIMIT ?
        """, (args.limit,))
        items = cur.fetchall()
        conn.close()
        print(f"Processing test batch of {len(items)} items in chronological calendar order...")
        for file_id, media_type, retry_count in items:
            print(f"--> Processing {media_type} {file_id}...")
            try:
                if media_type == "photo":
                    process_single_photo(file_id)
                    out_size = (IMAGES_DIR / f"{file_id}.webp").stat().st_size
                else:
                    process_single_video(file_id)
                    out_size = (VIDEOS_DIR / f"{file_id}.mp4").stat().st_size
                conn = sqlite3.connect(DB_PATH)
                cur = conn.cursor()
                cur.execute("UPDATE media_files SET status = 'completed', file_size_bytes = ?, processed_at = ? WHERE file_id = ?",
                            (out_size, int(time.time()), file_id))
                conn.commit()
                conn.close()
                print(f"    Completed! ({out_size/1024:.1f} KB)")
            except Exception as e:
                print(f"    Failed: {e}")
        print("Test batch finished.")
    else:
        run_pipeline()
