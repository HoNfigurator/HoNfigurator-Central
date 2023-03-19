import socket
import threading
import io
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

def handle_client(client_socket):
    remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    remote_socket.connect((REMOTE_ADDR, REMOTE_PORT))

    def forward_data(src_socket, dst_socket, parser=None):
        while True:
            data = src_socket.recv(4096)
            if len(data) == 0:
                break

            if parser:
                parser(data)

            dst_socket.sendall(data)

    threading.Thread(target=forward_data, args=(client_socket, remote_socket, parse_http_request)).start()
    threading.Thread(target=forward_data, args=(remote_socket, client_socket)).start()

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((LOCAL_ADDR, LOCAL_PORT))
    server.listen(5)

    print(f"[*] Listening on {LOCAL_ADDR}:{LOCAL_PORT}...")

    while True:
        client_socket, addr = server.accept()
        print(f"[+] Connection from {addr}")
        threading.Thread(target=handle_client, args=(client_socket,)).start()

if __name__ == "__main__":
    main()
