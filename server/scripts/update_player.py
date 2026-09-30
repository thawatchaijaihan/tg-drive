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
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    #player-container {
      position: relative;
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
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
      z-index: 30;
      user-select: none;
      transition: opacity 0.35s ease, transform 0.35s ease;
    }
    .quality-wrap.fade-out {
      opacity: 0;
      pointer-events: none;
      transform: translateY(-4px);
    }
    .quality-btn {
      display: flex;
      align-items: center;
      gap: 0.45rem;
      background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      color: #f8fafc;
      padding: 0.4rem 0.85rem;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 15px rgba(0, 0, 0, 0.5);
      transition: all 0.2s ease;
      outline: none;
    }
    .quality-btn:hover {
      background: rgba(30, 41, 59, 0.95);
      border-color: rgba(56, 189, 248, 0.6);
      transform: scale(1.03);
    }
    .quality-btn svg {
      opacity: 0.9;
    }
    .quality-menu {
      display: none;
      position: absolute;
      top: calc(100% + 0.5rem);
      right: 0;
      background: rgba(15, 23, 42, 0.95);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.18);
      border-radius: 14px;
      padding: 0.35rem;
      min-width: 155px;
      box-shadow: 0 15px 35px rgba(0, 0, 0, 0.7);
      flex-direction: column;
      gap: 0.2rem;
    }
    .quality-menu.show {
      display: flex;
      animation: menuPop 0.15s ease-out;
    }
    @keyframes menuPop {
      from { opacity: 0; transform: translateY(-6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .quality-item {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.45rem 0.75rem;
      border-radius: 9px;
      font-size: 0.78rem;
      font-weight: 500;
      color: #cbd5e1;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .quality-item:hover {
      background: rgba(255, 255, 255, 0.12);
      color: #fff;
    }
    .quality-item.active {
      color: #38bdf8;
      font-weight: 700;
      background: rgba(56, 189, 248, 0.14);
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
      <button class="quality-btn" id="quality-btn" title="ปรับความละเอียด">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
        <span id="quality-label">Auto</span>
      </button>

      <div class="quality-menu" id="quality-menu">
        <div class="quality-item active" data-level="-1">
          <span class="check-icon">✓</span>
          <span>Auto (แนะนำ)</span>
        </div>
      </div>
    </div>
  </div>

  <script>
    const hlsUrl = "__HLS_URL__";
    const streamFallbackUrl = "__STREAM_URL__";
    const video = document.getElementById('video-player');
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

    function initPlayer() {
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
          setupQualityMenu(data.levels);
        });

        hls.on(Hls.Events.ERROR, (e, data) => {
          if (data.fatal) {
            console.warn('HLS fatal error, falling back to direct stream:', data);
            video.src = streamFallbackUrl;
            qualityWrap.style.display = 'none';
          }
        });

      } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // Native iOS / Safari HLS
        video.src = hlsUrl;
        qualityWrap.style.display = 'none';
      } else {
        // Fallback to direct HTTP range stream
        video.src = streamFallbackUrl;
        qualityWrap.style.display = 'none';
      }
    }

    function setupQualityMenu(levels) {
      if (!levels || levels.length === 0) {
        qualityWrap.style.display = 'none';
        return;
      }

      qualityMenu.innerHTML = '';

      // 1. Auto option (Default!)
      const autoItem = document.createElement('div');
      autoItem.className = 'quality-item active';
      autoItem.dataset.level = '-1';
      autoItem.innerHTML = '<span class="check-icon">✓</span><span>Auto (แนะนำ)</span>';
      autoItem.onclick = () => setQuality(-1, 'Auto');
      qualityMenu.appendChild(autoItem);

      // 2. Add each available level from HLS manifest
      levels.forEach((lvl, idx) => {
        const item = document.createElement('div');
        item.className = 'quality-item';
        item.dataset.level = idx;
        const name = lvl.height ? `${lvl.height}p` : lvl.name || `Level ${idx + 1}`;
        item.innerHTML = `<span class="check-icon">✓</span><span>${name}</span>`;
        item.onclick = () => setQuality(idx, name);
        qualityMenu.appendChild(item);
      });
    }

    function setQuality(levelIndex, label) {
      if (!hlsInstance) return;
      hlsInstance.currentLevel = levelIndex;
      qualityLabel.innerText = label;

      document.querySelectorAll('.quality-item').forEach(el => {
        if (parseInt(el.dataset.level, 10) === levelIndex) {
          el.classList.add('active');
        } else {
          el.classList.remove('active');
        }
      });

      qualityMenu.classList.remove('show');
    }

    // Toggle menu
    qualityBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      qualityMenu.classList.toggle('show');
    });

    document.addEventListener('click', (e) => {
      if (!e.target.closest('#quality-wrap')) {
        qualityMenu.classList.remove('show');
      }
    });

    // Smooth Autohide on idle (3s)
    let idleTimer = null;
    function showControl() {
      qualityWrap.classList.remove('fade-out');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (!qualityMenu.classList.contains('show') && !video.paused) {
          qualityWrap.classList.add('fade-out');
        }
      }, 3000);
    }

    document.addEventListener('mousemove', showControl);
    document.addEventListener('touchstart', showControl);
    video.addEventListener('play', showControl);
    video.addEventListener('pause', () => {
      qualityWrap.classList.remove('fade-out');
      clearTimeout(idleTimer);
    });
    showControl();

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
          document.getElementById('player-container').requestFullscreen?.();
        } else {
          document.exitFullscreen?.();
        }
      }
    });

    video.addEventListener('dblclick', () => {
      if (!document.fullscreenElement) {
        document.getElementById('player-container').requestFullscreen?.();
      } else {
        document.exitFullscreen?.();
      }
    });

    document.addEventListener('DOMContentLoaded', initPlayer);
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
        }}
    )
"""

with open('/home/ubuntu/tg-filestream/stream_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = "PURE_PLAYER_HTML = '''"
if start_marker not in content:
    start_marker = 'async def handle_watch(request: web.Request):'

end_marker = '# ─── TELEGRAM BOT LISTENER ────────────────────────────────────────────────────'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + new_handle_watch + '\n\n' + content[end_idx:]
    with open('/home/ubuntu/tg-filestream/stream_server.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('SUCCESS: stream_server.py updated with floating quality badge (Default: Auto)!')
else:
    print('ERROR: markers not found!', start_idx, end_idx)
