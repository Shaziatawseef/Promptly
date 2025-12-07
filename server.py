import os
import asyncio
import base64
import datetime
from aiohttp import web
import aiohttp
import aiohttp.web
from colorama import Fore, Style, init

init(autoreset=True)

PORT = int(os.environ.get("PORT", 9990))
PASSWORD = os.environ.get("PASSWORD", "1234")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

LOG_FILE = "chat.log"

clients = {}
users = {}
warn_count = {}
banned_users = set()
muted_users = set()


def log(message, level="info"):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


async def broadcast(message, exclude_ws=None):
    dead = []
    for username, ws in users.items():
        if ws != exclude_ws:
            try:
                await ws.send_str(message)
            except:
                dead.append(username)
    for u in dead:
        users.pop(u, None)


async def send_online_users(to_ws=None):
    online = ', '.join(users.keys())
    count = len(users)
    msg = f"Online users ({count}): {online}"
    if to_ws:
        await to_ws.send_str(msg)
    else:
        await broadcast(msg)


async def send_help(ws, is_admin):
    help_msg = [
        "📘 Available Commands:",
        "/pm username message",
        "/send filename base64data",
        "/down filename",
        "/list",
        "/help"
    ]
    if is_admin:
        help_msg += [
            "Admin Commands:",
            "/ban username",
            "/war username",
            "/mute username",
            "/unmute username"
        ]
    await ws.send_str("\n".join(help_msg))


async def handle_message(ws, username, message):
    is_admin = (username == "admin")

    if username in banned_users:
        await ws.send_str("You are banned.")
        return

    if message.strip() == "/help":
        await send_help(ws, is_admin)
        return

    if username in muted_users and not is_admin:
        await ws.send_str("You are muted.")
        return

    if message.startswith("/pm"):
        parts = message.split(" ", 2)
        if len(parts) < 3:
            return await ws.send_str("Usage: /pm username message")
        target, msg = parts[1], parts[2]
        if target not in users:
            return await ws.send_str("User not found.")
        await users[target].send_str(f"[PM] {username}: {msg}")
        await ws.send_str(f"[PM to {target}] {msg}")
        return

    if message.startswith("/send"):
        parts = message.split(" ", 2)
        if len(parts) < 3:
            return await ws.send_str("Usage: /send filename base64")
        fname, b64 = parts[1], parts[2]
        try:
            with open(fname, "wb") as f:
                f.write(base64.b64decode(b64))
            await ws.send_str(f"Uploaded {fname}")
        except Exception as e:
            await ws.send_str(str(e))
        return

    if message.startswith("/down"):
        parts = message.split(" ", 1)
        if len(parts) < 2:
            return await ws.send_str("Usage: /down filename")
        fname = parts[1]
        if not os.path.exists(fname):
            return await ws.send_str("File not found.")
        with open(fname, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        await ws.send_str(f"{fname} {b64}")
        return

    if is_admin:
        if message.startswith("/ban "):
            target = message.split(" ", 1)[1]
            banned_users.add(target)
            if target in users:
                await users[target].send_str("You are banned.")
                await users[target].close()
            return

        if message.startswith("/war "):
            target = message.split(" ", 1)[1]
            warn_count[target] = warn_count.get(target, 0) + 1
            if warn_count[target] >= 4:
                banned_users.add(target)
                if target in users:
                    await users[target].send_str("Banned after warnings.")
                    await users[target].close()
            return

        if message.startswith("/mute "):
            muted_users.add(message.split(" ", 1)[1])
            return

        if message.startswith("/unmute "):
            muted_users.discard(message.split(" ", 1)[1])
            return

        if message.startswith("/list"):
            await send_online_users(ws)
            return

    await broadcast(f"{username}: {message}", exclude_ws=ws)
    await ws.send_str(f"You: {message}")


async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    await ws.send_str("Enter password:")
    password = await ws.receive_str()

    if password != PASSWORD:
        await ws.send_str("Wrong password.")
        await ws.close()
        return ws

    await ws.send_str("Enter username:")
    username = await ws.receive_str()

    if username in banned_users:
        await ws.send_str("You are banned.")
        await ws.close()
        return ws

    if username in users:
        await ws.send_str("Username in use.")
        await ws.close()
        return ws

    users[username] = ws
    warn_count.setdefault(username, 0)

    log(f"{username} connected.")
    await broadcast(f"{username} joined.")
    await send_online_users()

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            await handle_message(ws, username, msg.data)

    users.pop(username, None)
    await broadcast(f"{username} left.")
    return ws


async def keepalive(request):
    return web.json_response({"status": "alive"})


async def health(request):
    return web.Response(text="OK")


def create_app():
    app = web.Application()
    app.add_routes([
        web.get("/", lambda r: web.Response(text="Server running.")),
        web.get("/health", health),
        web.get("/keepalive", keepalive),
        web.get("/ws", websocket_handler)
    ])
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
