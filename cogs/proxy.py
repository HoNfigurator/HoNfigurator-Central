import socket
import threading
import struct

# Define constants
LOCAL_HOST = '127.0.0.1'
PROXY_PORT = 1245
BUFFER_SIZE = 4096

# Function to extract destination IP and port from the packet
def extract_dest_from_packet(packet):
    # Check if the packet is at least 20 bytes long (minimum IP header length)
    if len(packet) < 20:
        return None, None

    ip_header = struct.unpack('!BBHHHBBH4s4s', packet[:20])
    ip_header_length = (ip_header[0] & 0x0F) * 4

    # Check if the packet is long enough to contain the complete IP header and at least 20 bytes of TCP header
    if len(packet) < ip_header_length + 20:
        return None, None

    dest_ip = socket.inet_ntoa(ip_header[9])
    tcp_header = struct.unpack('!HHLLBBHHH', packet[ip_header_length:ip_header_length + 20])
    dest_port = tcp_header[1]

    return dest_ip, dest_port


# Function to handle traffic forwarding
def forward_traffic(src_socket, dest_socket):
    try:
        while True:
            data = src_socket.recv(BUFFER_SIZE)
            if len(data) == 0:
                break
            dest_socket.sendall(data)
    except Exception as e:
        pass
    finally:
        src_socket.close()
        dest_socket.close()

def recvall(sock, n):
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

def handle_client(client_socket):
    dest_ip, dest_port = None, None
    max_attempts = 5
    attempts = 0

    while dest_ip is None or dest_port is None:
        # Read the first two bytes to determine the length of the packet
        length_bytes = recvall(client_socket, 2)
        if length_bytes is None:
            print("Failed to read packet length")
            client_socket.close()
            return

        packet_length = struct.unpack('!H', length_bytes)[0]

        # Read the rest of the packet
        first_packet = recvall(client_socket, packet_length)
        if first_packet is None:
            print("Failed to read the full packet")
            client_socket.close()
            return

        dest_ip, dest_port = extract_dest_from_packet(first_packet)

        attempts += 1
        if attempts >= max_attempts:
            print("Failed to extract destination IP and port from the packet")
            client_socket.close()
            return

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.connect((dest_ip, dest_port))
    server_socket.sendall(length_bytes + first_packet)

    client_to_server = threading.Thread(target=forward_traffic, args=(client_socket, server_socket))
    server_to_client = threading.Thread(target=forward_traffic, args=(server_socket, client_socket))

    client_to_server.start()
    server_to_client.start()

    client_to_server.join()
    server_to_client.join()


# Main function to start the proxy server
def main():
    # Create a socket to listen for connections
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_socket.bind((LOCAL_HOST, PROXY_PORT))
    proxy_socket.listen(5)
    print(f"Proxy server listening on {LOCAL_HOST}:{PROXY_PORT}")

    # Accept incoming connections and handle them
    while True:
        client_socket, client_addr = proxy_socket.accept()
        print(f"Connection from {client_addr}")
        client_thread = threading.Thread(target=handle_client, args=(client_socket,))
        client_thread.start()

if __name__ == "__main__":
    main()
