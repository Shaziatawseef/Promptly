import os

# server.py
# Defaults (can be overridden by environment variables on Render)
PORT = int(os.environ.get("PORT", 9990))  # change it via env on Render
PASSWORD = os.environ.get("PASSWORD", "1234")  # change it in Render env
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # change it in Render env

import asyncio
import websockets
import base64
import os
import datetime
from colorama import Fore, Style, init
from aiohttp import web

init(autoreset=True)


LOG_FILE = "chat.log"

clients = {}
users = {}
warn_count = {}
banned_users = set()
muted_users = set()


def log(message, level="info"):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    color = {
        "info": Fore.CYAN,
        "error": Fore.RED,
        "warning": Fore.YELLOW,
        "success": Fore.GREEN
    }.get(level, Fore.WHITE)
    entry = f"{color}[{timestamp}] {message}{Style.RESET_ALL}"
    print(entry)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


async def broadcast(message, exclude_ws=None):
    for ws in list(clients.keys()):
        if ws != exclude_ws:
            try:
                await ws.send(message)
            except Exception:
                # remove dead websockets silently
                try:
                    clients.pop(ws, None)
                except Exception:
                    pass


async def send_online_users(to_ws=None):
    online = ', '.join(users.keys())
    count = len(users)
    msg = Fore.MAGENTA + f"Online users ({count}): {online}" + Style.RESET_ALL
    if to_ws:
        await to_ws.send(msg)
    else:
        await broadcast(msg)


async def send_help(ws, is_admin):
    help_msg = [
        Fore.CYAN + "📘 Available Commands:" + Style.RESET_ALL,
        "/pm username message  - Private message",
        "/send path/to/file    - Upload file",
        "/down filename        - Download file",
        "/list                 - Show online users (to admin only)",
        "/list show            - Broadcast online users to all",
        "/help                 - Show this help message"
    ]
    if is_admin:
        help_msg += [
            Fore.YELLOW + "Admin Commands:" + Style.RESET_ALL,
            "/ban username        - Ban user",
            "/war username        - Warn user (4 warns = ban)",
            "/mute username       - Mute user",
            "/unmute username     - Unmute user"
        ]
    await ws.send("\n".join(help_msg))


async def handle_message(ws, username, message):
    _, is_admin = clients[ws]

    if username in banned_users:
        await ws.send(Fore.RED + "You are banned from this server." + Style.RESET_ALL)
        return

    if message.strip() == "/help":
        await send_help(ws, is_admin)
        return

    if username in muted_users and not is_admin:
        await ws.send(Fore.RED + "You are muted and cannot send public messages." + Style.RESET_ALL)
        return

    if message.startswith("/pm"):
        parts = message.split(" ", 2)
        if len(parts) < 3:
            await ws.send(Fore.YELLOW + "Usage: /pm username message" + Style.RESET_ALL)
            return
        target, msg = parts[1], parts[2]
        if target not in users:
            await ws.send(Fore.RED + f"User {target} not found." + Style.RESET_ALL)
            return
        send_msg = Fore.MAGENTA + f"[PM] {username} -> {target}: {msg}" + Style.RESET_ALL
        await users[target].send(send_msg)
        await ws.send(send_msg)
        log(f"[PM] {username} -> {target}: {msg}")
        return

    if message.startswith("/send"):
        parts = message.split(" ", 2)
        if len(parts) < 3:
            await ws.send(Fore.YELLOW + "Usage: /send filename base64data" + Style.RESET_ALL)
            return
        fname, b64data = parts[1], parts[2]
        try:
            with open(fname, "wb") as f:
                f.write(base64.b64decode(b64data))
            await ws.send(Fore.GREEN + f"File '{fname}' uploaded." + Style.RESET_ALL)
            log(f"{username} uploaded file: {fname}")
        except Exception as e:
            await ws.send(Fore.RED + f"Error saving file: {e}" + Style.RESET_ALL)
        return

    if message.startswith("/down"):
        parts = message.split(" ", 1)
        if len(parts) < 2:
            await ws.send(Fore.YELLOW + "Usage: /down filename" + Style.RESET_ALL)
            return
        fname = parts[1]
        if not os.path.exists(fname):
            await ws.send(Fore.RED + f"File '{fname}' not found." + Style.RESET_ALL)
            return
        try:
            with open(fname, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            await ws.send(f"\U0001F4E5 {fname} {b64}")
            log(f"{username} downloaded file: {fname}")
        except Exception as e:
            await ws.send(Fore.RED + f"Error reading file: {e}" + Style.RESET_ALL)
        return

    if is_admin:
        if message.startswith("/ban"):
            parts = message.split(" ", 1)
            if len(parts) < 2:
                await ws.send(Fore.YELLOW + "Usage: /ban username" + Style.RESET_ALL)
                return
            target = parts[1]
            if target in users:
                banned_users.add(target)
                await users[target].send(Fore.RED + "You are banned by admin." + Style.RESET_ALL)
                await users[target].close()
                log(f"Admin banned {target}")
                await broadcast(Fore.RED + f"User {target} has been banned by admin." + Style.RESET_ALL)
            else:
                await ws.send(Fore.RED + f"User {target} not found." + Style.RESET_ALL)
            return

        if message.startswith("/war"):
            parts = message.split(" ", 1)
            if len(parts) < 2:
                await ws.send(Fore.YELLOW + "Usage: /war username" + Style.RESET_ALL)
                return
            target = parts[1]
            warn_count[target] = warn_count.get(target, 0) + 1
            if warn_count[target] >= 4:
                banned_users.add(target)
                if target in users:
                    await users[target].send(Fore.RED + "You are banned after 4 warnings." + Style.RESET_ALL)
                    await users[target].close()
                    log(f"{target} banned after 4 warnings")
                await broadcast(Fore.RED + f"User {target} banned after 4 warnings." + Style.RESET_ALL)
            else:
                if target in users:
                    await users[target].send(Fore.YELLOW + f"Warning ({warn_count[target]}/4) from admin." + Style.RESET_ALL)
            return

        if message.startswith("/mute"):
            parts = message.split(" ", 1)
            if len(parts) < 2:
                await ws.send("Usage: /mute username")
                return
            target = parts[1]
            if target in users:
                muted_users.add(target)
                await users[target].send(Fore.YELLOW + "You have been muted by admin." + Style.RESET_ALL)
                await ws.send(Fore.GREEN + f"{target} is muted." + Style.RESET_ALL)
                log(f"Admin muted {target}")
            else:
                await ws.send(Fore.RED + f"User {target} not found." + Style.RESET_ALL)
            return

        if message.startswith("/unmute"):
            parts = message.split(" ", 1)
            if len(parts) < 2:
                await ws.send("Usage: /unmute username")
                return
            target = parts[1]
            if target in muted_users:
                muted_users.remove(target)
                await users[target].send(Fore.GREEN + "You have been unmuted by admin." + Style.RESET_ALL)
                await ws.send(Fore.GREEN + f"{target} is unmuted." + Style.RESET_ALL)
                log(f"Admin unmuted {target}")
            else:
                await ws.send(Fore.YELLOW + f"{target} is not muted." + Style.RESET_ALL)
            return

        if message.startswith("/list"):
            if message.strip() == "/list show":
                await send_online_users()
            else:
                await send_online_users(to_ws=ws)
            return

    time = datetime.datetime.now().strftime("%H:%M:%S")
    full_msg = Fore.WHITE + f"[{time}] {username}: {message}" + Style.RESET_ALL
    log(f"{username}: {message}")
    await broadcast(full_msg, exclude_ws=ws)
    await ws.send(Fore.GREEN + f"[{time}] You: {message}" + Style.RESET_ALL)


async def handler(ws, path):
    await ws.send("Please enter password:")
    try:
        password = await ws.recv()
    except websockets.exceptions.ConnectionClosed:
        return
    if password != PASSWORD:
        await ws.send(Fore.RED + "Wrong password." + Style.RESET_ALL)
        await ws.close()
        return

    await ws.send("Enter your username:")
    try:
        username = await ws.recv()
    except websockets.exceptions.ConnectionClosed:
        return

    is_admin = False
    if username == "admin":
        await ws.send("Enter admin password:")
        try:
            admin_pw = await ws.recv()
        except websockets.exceptions.ConnectionClosed:
            return
        if admin_pw != ADMIN_PASSWORD:
            await ws.send(Fore.RED + "Incorrect admin password." + Style.RESET_ALL)
            await ws.close()
            return
        is_admin = True

    if username in banned_users:
        await ws.send(Fore.RED + "You are banned from this server." + Style.RESET_ALL)
        await ws.close()
        return

    if username in users:
        await ws.send(Fore.RED + "Username already taken." + Style.RESET_ALL)
        await ws.close()
        return

    clients[ws] = (username, is_admin)
    users[username] = ws
    warn_count.setdefault(username, 0)

    log(f"User connected: {username}")
    await broadcast(Fore.GREEN + f"User {username} joined the chat." + Style.RESET_ALL)
    await send_online_users()
    await ws.send(Fore.GREEN + f"Welcome {username}! Type /help for commands." + Style.RESET_ALL)

    try:
        async for message in ws:
            await handle_message(ws, username, message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        clients.pop(ws, None)
        users.pop(username, None)
        warn_count.pop(username, None)
        muted_users.discard(username)
        log(f"User disconnected: {username}")
        await broadcast(Fore.YELLOW + f"User {username} left the chat." + Style.RESET_ALL)
        await send_online_users()


# -----------------------
# HTTP keep-alive / health server for Render + cron
# -----------------------

async def keepalive_handler(request):
    """
    Endpoint for cron job keep-alive.
    Visiting /keepalive will:
      - return a simple status JSON/html
      - (optionally) broadcast a small heartbeat message to connected websocket clients
    """
    try:
        # optional: broadcast a heartbeat message so that connected clients know server is alive
        heartbeat = Fore.YELLOW + f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Server: keepalive ping" + Style.RESET_ALL
        # Do not await broadcast here if you want the endpoint to respond immediately.
        # We'll schedule it so response is fast.
        asyncio.create_task(broadcast(heartbeat))
    except Exception as e:
        log(f"Keepalive broadcast error: {e}", level="warning")

    data = {
        "status": "ok",
        "time": datetime.datetime.utcnow().isoformat() + "Z",
        "online_users": len(users)
    }
    return web.json_response(data)


async def health_handler(request):
    return web.Response(text="OK")


async def start_http_server(host="0.0.0.0", port=None):
    app = web.Application()
    app.add_routes([
        web.get("/keepalive", keepalive_handler),
        web.get("/health", health_handler),
        web.get("/", lambda req: web.Response(text="WebSocket Chat Server is running. Use /keepalive for cron.")),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site_port = port if port is not None else PORT
    site = web.TCPSite(runner, host, site_port)
    await site.start()
    log(f"HTTP server running on port {site_port}", level="success")
    return runner  # callers can cleanup if needed


async def main():
    # Start HTTP server (for keepalive and health checks)
    await start_http_server(port=PORT)

    # Start websocket server on same port but different path
    # We'll listen on same port but path handled by websockets server (it doesn't conflict with aiohttp)
    # Note: Render expects a single TCP port — both aiohttp and websockets here bind to the same port via asyncio create_server usage.
    # To keep it simple on Render, we let websockets listen on same host and PORT but websockets.serve uses the same port;
    # however, binding twice to same port typically fails. So we run the websockets server on the same port but on a different task using the same host.
    # In practice, running both on the same port is tricky; instead, we run websockets on the same host and PORT but as a WebSocket server attached to the same loop.
    # websockets.serve will attempt to bind the port; to avoid double-bind, if aiohttp already bound the port, we must start websockets on another port.
    # Render gives a single port — but aiohttp is enough for keepalive; clients that expect raw websockets can connect to the websockets server on a subpath handled by websockets.
    # The websockets library supports path-based handling when used with a shared server socket, but that's advanced.
    # Simpler approach: run websockets server on the same host and PORT but using the underlying loop create_server of websockets library which will raise if port already used.
    # To avoid conflicts we will run the websockets server on PORT as well but if binding fails fallback to PORT+1.
    ws_port = PORT
    try:
        server = await websockets.serve(handler, "0.0.0.0", ws_port)
        log(f"WebSocket server running on port {ws_port}", level="success")
    except Exception as e:
        # fallback if port already in use by aiohttp (common on Render). Try PORT+1.
        ws_port = PORT + 1
        server = await websockets.serve(handler, "0.0.0.0", ws_port)
        log(f"WebSocket server port {PORT} in use; running on fallback port {ws_port}", level="warning")

    # Keep running forever
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("Server shutting down.", level="warning")

