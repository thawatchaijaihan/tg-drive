import html
import re

SERVER_FILE = '/home/ubuntu/tg-filestream/stream_server.py'

with open(SERVER_FILE, 'r', encoding='utf-8') as f:
    code = f.read()

# Update CODECS in handle_hls_master to avc1 so all browsers support it
code = re.sub(
    r'CODECS="av01[^"]*"',
    'CODECS="avc1.640028,mp4a.40.2"',
    code
)

TEMPLATE = '''<!DOCTYPE html>
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

new_handle_watch = f"""PURE_PLAYER_HTML = '''{TEMPLATE}'''

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
    hls_master_url = f"/hls/{{chat_id}}/{{msg_id}}/master.m3u8"
    stream_url = f"/stream/{{chat_id}}/{{msg_id}}"

    html_content = PURE_PLAYER_HTML.replace("__FILE_NAME__", html.escape(file_name)) \\
                                   .replace("__HLS_URL__", hls_master_url) \\
                                   .replace("__STREAM_URL__", stream_url) \\
                                   .replace("__CHAT_ID__", str(chat_id)) \\
                                   .replace("__MSG_ID__", str(msg_id))

    return web.Response(
        text=html_content,
        content_type="text/html",
        charset="utf-8",
        headers={{
            "Access-Control-Allow-Origin": "*",
            "Content-Security-Policy": "frame-ancestors *",
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }}
    )
"""

start_marker = "PURE_PLAYER_HTML = '''"
end_marker = '# ─── TELEGRAM BOT LISTENER ────────────────────────────────────────────────────'

start_idx = code.find(start_marker)
end_idx = code.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_code = code[:start_idx] + new_handle_watch + '\n\n' + code[end_idx:]
    with open(SERVER_FILE, 'w', encoding='utf-8') as f:
        f.write(new_code)
    print("SUCCESS: Bulletproof player installed!")
else:
    print(f"ERROR: Markers not found: start={start_idx}, end={end_idx}")
