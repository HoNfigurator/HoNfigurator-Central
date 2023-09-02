import asyncio
import io
import socket
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs
from datetime import datetime

def get_current_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

LOCAL_ADDR = "127.0.0.1"
LOCAL_PORT = 80
REMOTE_ADDR = "104.21.81.134"  # Replace with the target server's address
REMOTE_PORT = 80

def my_print(*args, **kwargs):
    msg = ' '.join(map(str, args))
    print(f"\n{get_current_timestamp()} {msg}", **kwargs)


class CustomHTTPRequestHandler(BaseHTTPRequestHandler):
    def __init__(self, request_data):
        self.rfile = io.BytesIO(request_data)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message

    def handle_request(self):
        user_agent = self.headers.get('User-Agent')
        my_print(f"User-Agent: {user_agent}")  # Print User-Agent
        if self.command == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            content_type = self.headers.get("Content-Type", "")
            post_data = self.rfile.read(content_length)
            if content_type == "application/x-www-form-urlencoded":
                post_data_dict = parse_qs(post_data.decode("utf-8"))
                my_print(f"POST request to {self.path} with data:")
                for key, values in post_data_dict.items():
                    print(f"  {key}: {values}")
            else:
                my_print(f"POST request to {self.path} with unsupported content type: {content_type}")

def parse_http_request(request_data):
    handler = CustomHTTPRequestHandler(request_data)
    handler.handle_request()

async def forward_data(src_reader, dst_writer, parser=None):
    while True:
        try:
            data = await asyncio.wait_for(src_reader.read(4096), timeout=5)
            if len(data) == 0:
                break

            if parser:
                parser(data)

            new_user_agent = b"S2 Games/Heroes of Newerth/4.10.8.0/las/x86-biarch"
            data = data.replace(b"User-Agent: S2 Games/Heroes of Newerth/4.10.9.0/las/x86-biarch", b"User-Agent: " + new_user_agent)

            dst_writer.write(data)
            await dst_writer.drain()
        except asyncio.TimeoutError:
            continue
        except ConnectionResetError:
            my_print("Connection reset")
            break


async def handle_client(reader, writer):
    remote_reader, remote_writer = await asyncio.open_connection(REMOTE_ADDR, REMOTE_PORT)

    asyncio.create_task(forward_data(reader, remote_writer, parse_http_request))
    asyncio.create_task(forward_data(remote_reader, writer))

async def shutdown(server):
    print("\n[*] Shutting down the server...")
    server.close()
    await server.wait_closed()

    tasks = asyncio.all_tasks()
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("[*] All tasks cancelled and server closed")

async def main():
    server = await asyncio.start_server(handle_client, LOCAL_ADDR, LOCAL_PORT)

    addr = server.sockets[0].getsockname()
    print(f"[*] Listening on {addr[0]}:{addr[1]}...")

    try:
        async with server:
            await server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down due to keyboard interrupt...")
    finally:
        await shutdown(server)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")