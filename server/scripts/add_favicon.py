with open('/home/ubuntu/tg-filestream/stream_server.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Add handle_favicon
favicon_func = '''async def handle_favicon(request: web.Request):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#38bdf8"><polygon points="5 3 19 12 5 21 5 3"/></svg>'
    return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

'''

if 'async def handle_favicon' not in code:
    idx = code.find('async def handle_stream')
    if idx != -1:
        code = code[:idx] + favicon_func + code[idx:]

# 2. Add route in create_app
if 'add_get("/favicon.ico"' not in code:
    idx = code.find('app.router.add_get("/", handle_index)')
    if idx != -1:
        code = code[:idx] + 'app.router.add_get("/favicon.ico", handle_favicon)\n    ' + code[idx:]

with open('/home/ubuntu/tg-filestream/stream_server.py', 'w', encoding='utf-8') as f:
    f.write(code)

print("Applied favicon and route updates successfully!")
