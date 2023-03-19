import socket
import threading
import struct
import sys
import traceback

# Connection details
LOCAL_ADDR = '127.0.0.1'
LOCAL_PORT_SVR = 11032  # Port the game server connects to
LOCAL_PORT_MGR = 11033  # Port the manager connects to
REMOTE_ADDR = '212.181.3.23'
REMOTE_PORT_SVR = 11032  # Port of the remote chat server
REMOTE_PORT_MGR = 11033  # Port of the remote chat server

def parse_packet(data):
    msg_len = int.from_bytes(data[0:2],byteorder='little')
    msg_type = int.from_bytes(data[0:2], byteorder='little')
    packet_len = len(data)
    if packet_len > 2:
        modified_packet = data[4:]
    else: modified_packet = data
    return msg_len,msg_type, data, modified_packet

def handle_gameserver_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    if msg_len != packet_len -2:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        elif msg_type in [0x2afd,0x2ae5,0x2afc,0x2afe,0x2aff,0x2b00,0x2b01,0x2b02,0x2b03]: pass     # found that the msg type changes based on the region
        else:
            print(f">>> [type:{hex(msg_type)}] Most likely the type for this packet is wrong, as the len taken from this packet is not correct.. original packet: {original_packet}")
    if msg_type == 0x500:
        #   Log in
        session_id = new_packet[4:].split(b'\x00', 1)[0].decode('utf-8')
        print(f">>> [type:{hex(msg_type)}] Logging in...\n\tSession ID: {session_id}")
    elif msg_type == 0x0:
        #   send heartbeat
        if new_packet[1] != 0x0:    # ignore the first packet which defines the size of the msg in this case
            print(f">>> [type:{hex(msg_type)}] Sending heartbeat..")
    elif msg_type in [0x2afd,0x2ae5,0x2afc,0x2afe,0x2aff,0x2b00,0x2b01,0x2b02,0x2b03]:
        """Send server information
        The above hex values represent the following regions:
            SEA = 2afd
            AU = 2ae5
            NEWERTH = 2afc
            USW = 2afe
            USE = 2aff
            TH = 2b00
            RU = 2b01
            EU = 2b02
            BR = 2b03
        """
        #   Send server information
        # Parse IP address, region, and server name
        ip_addr, _, remaining_data = new_packet[2:].partition(b'\x00')
        region, _, remaining_data = remaining_data[2:].partition(b'\x00')
        server_name, _, _ = remaining_data.partition(b'\x00')
        ip_addr = ip_addr.decode('utf-8')
        region = region.decode('utf-8')
        server_name = server_name.decode('utf-8')

        reversed_bytes = new_packet[::-1]
        second_null_index = reversed_bytes[1:].find(b'\x00')
        version_index = second_null_index+8+2   #   there are always 8 null bytes after the hostname in the reversed byte array. add 2 to make up for the skipped null index at the start
        version_number = reversed_bytes[version_index:].split(b'\x00', 1)[0].decode('utf-8')
        version_number = version_number[::-1]
        print(f">>> [{hex(msg_type)}] Server sent lobby information\n\tIP Addr: {ip_addr}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version_number}")
    elif msg_type == 0x29de:
        print()
    else:
        print(f">>> [type:{hex(msg_type)}] {new_packet}")

def handle_manager_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    if msg_len != packet_len -2:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f">>> [type:{hex(msg_type)}] Most likely the len taken from this packet is not correct.. original packet: {original_packet}")
    if msg_type == 0x1600:
        #   b'+\x00\x00\x16Y\xf0\x02\x007f9c6567063d467cbf604aa21f220c40\x00F\x00\x00\x00' -mine
        #   b'+\x00\x00\x16Y\xf0\x02\x00f7851dd680764deaabf4bcc447ce5b57\x00F\x00\x00\x00'  -working
        server_id = int.from_bytes(new_packet[0:4],byteorder='little')
        session_id = new_packet[4:].split(b'\x00', 1)[0].decode('utf-8')
        print(f'>>> [type:{hex(msg_type)}] Handshake\n\tServer ID: {server_id}\n\tSession: {session_id}')
    elif msg_type == 0xf059:
        #   b'8\x00Y\xf0\x01AUSFRANKHOST:\x00NEWERTH\x00TEST 0\x004.10.6.0\x00103.193.80.121\x00' - mine
        #   b'\x02\x16Y\xf0\x02\x00AUSFRANKHOST:\x00NEWERTH\x00T4NK 0\x004.10.6.0\x00103.193.80.121\x00\xe3+\x00' - original
        #  send server information
        #   int 1 unknown
        #   str username
        #   str region
        #   str server name
        #   str version
        #   str ip addr
        unknown = new_packet[1]
        username, region, server_name, version, ip_addr = [s.decode('utf-8') for s in new_packet[2:].split(b'\x00', 5)[:-1]]
        print(f">>> [{hex(msg_type)}] Sending server info:\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Addr: {ip_addr}")
    elif msg_type == 0x0:
        if packet_len > 0:
            print(f">>> [{hex(msg_type)}] Sending heartbeat..")
    elif msg_type == 0x2a01:
        print(f">>> [{hex(msg_type)}] Received heartbeat")
    else:
        print(f">>> [type:{hex(msg_type)}] {new_packet}")

def handle_chatserver_to_gameserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    if msg_len != packet_len -2:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f"<<< [type:{hex(msg_type)}] Most likely the len taken from this packet is not correct.. original packet: {original_packet}")
    if msg_type == 0x1500:
        #   Authenticated
        print(f"<<< [type:{hex(msg_type)}] Authenticated to Chat Server")
    elif msg_type == 0x2a01:
        print(f"<<< [type:{hex(msg_type)}] Received heartbeat")
    else:
        print(f"<<< [type:{hex(msg_type)}] {new_packet}")

def handle_chatserver_to_manager_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    if msg_len != packet_len -2:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f"<<< [type:{hex(msg_type)}] Most likely the len taken from this packet is not correct.. original packet: {original_packet}")
    if msg_type == 0x1700:
        print(f'<<< [{hex(msg_type)}] Handshake accepted')
    elif msg_type == 0x1704:
        #   Replay request
        account_id, match_id, ext_len, filehost_len, dir_len, upload_to_ftb, upload_to_s3 = struct.unpack('!I I I I I B B', new_packet[:22])
        offset = 22
        extension = new_packet[offset:offset + ext_len].decode('utf-8')
        offset += ext_len
        filehost = new_packet[offset:offset + filehost_len].decode('utf-8')
        offset += filehost_len
        directory = new_packet[offset:offset + dir_len].decode('utf-8')
        offset += dir_len
        download_link = new_packet[offset:].decode('utf-8')
        print(f'<<< [{hex(msg_type)}] Upload replay\n Account ID: {account_id}\n Match ID: {match_id}\n Extension: {extension}\n Filehost: {filehost}\n Directory: {directory}\n Upload to ftb: {upload_to_ftb}\n Upload to S3: {upload_to_s3}\n Download Link: {download_link}')
    elif msg_type == 0x2a01:
        print(f"<<< [{hex(msg_type)}] Received heartbeat")
    else:
        # 0x1703: OK to server info? b'\x01\x01\x00\x01\x01\x01\x00\x00\x00'
        # 0x2a01: ? b''
        print(f"<<< [{hex(msg_type)}] {new_packet}")

def forward(src, dst, src_name, dst_name):
    try:
        while True:
            data = src.recv(4096)
            if len(data) == 0:
                break
            if src_name == "manager":
                msg_len, msg_type, original_packet, new_packet = parse_packet(data)
                handle_manager_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet)
            elif src_name == "gameserver":
                msg_len, msg_type, original_packet, new_packet = parse_packet(data)
                handle_gameserver_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet)
            elif src_name == "chatserver":
                if dst_name == "manager":
                    msg_len, msg_type, original_packet, new_packet = parse_packet(data)
                    handle_chatserver_to_manager_packet(msg_len, msg_type, original_packet, new_packet)
                if dst_name == "gameserver":
                    msg_len, msg_type, original_packet, new_packet = parse_packet(data)
                    handle_chatserver_to_gameserver_packet(msg_len, msg_type, original_packet, new_packet)
            dst.sendall(data)
    except ConnectionResetError:
        print(f"ConnectionResetError: {traceback.format_exc()}")
        dst.close()
        src.close()
        return
    except Exception:
        print(f"An error occurred: {traceback.format_exc()}")

    dst.close()
    src.close()



def handle_connections(server, remote_port, src_name, dst_name):
    while True:
        client, addr = server.accept()
        print(f'[*] Accepted connection from {addr[0]}:{addr[1]} ({src_name})')

        remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote_socket.connect((REMOTE_ADDR, remote_port))

        t1 = threading.Thread(target=forward, args=(client, remote_socket, src_name, dst_name))
        t2 = threading.Thread(target=forward, args=(remote_socket, client, dst_name, src_name))

        t1.start()
        t2.start()

        try:
            t1.join()
            t2.join()
        except ConnectionResetError:
            print(f"Client disconnected: {addr[0]}:{addr[1]} ({src_name})")
        finally:
            client.close()
            remote_socket.close()


def main():
    server_manager = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_manager.bind((LOCAL_ADDR, LOCAL_PORT_MGR))
    server_manager.listen(5)
    print(f'[*] Listening on {LOCAL_ADDR}:{LOCAL_PORT_MGR}')

    server_gameserver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_gameserver.bind((LOCAL_ADDR, LOCAL_PORT_SVR))
    server_gameserver.listen(5)
    print(f'[*] Listening on {LOCAL_ADDR}:{LOCAL_PORT_SVR}')

    try:
        t_manager = threading.Thread(target=handle_connections, args=(server_manager, REMOTE_PORT_MGR, "manager", "chatserver"))
        t_gameserver = threading.Thread(target=handle_connections, args=(server_gameserver, REMOTE_PORT_SVR, "gameserver", "chatserver"))

        t_manager.start()
        t_gameserver.start()

        t_manager.join()
        t_gameserver.join()

    except KeyboardInterrupt:
        print("Keyboard interrupt received. Shutting down.")
        server_manager.close()
        server_gameserver.close()
        sys.exit(0)

if __name__ == '__main__':
    main()


