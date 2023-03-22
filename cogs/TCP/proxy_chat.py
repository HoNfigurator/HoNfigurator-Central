import socket
import threading
import struct
import sys
import traceback
import re

# Connection details
LOCAL_ADDR = '127.0.0.1'
LOCAL_PORT_SVR = 11032  # Port the game server connects to
LOCAL_PORT_MGR = 11033  # Port the manager connects to
REMOTE_ADDR = '212.181.3.23'
REMOTE_PORT_SVR = 11032  # Port of the remote chat server
REMOTE_PORT_MGR = 11033  # Port of the remote chat server

def parse_packet(data, src, dst, src_name, dst_name):
    msg_len = int.from_bytes(data[0:2], byteorder='little')
    if len(data) == 2:  #   this means we have the len only.
            next_packet_data = src.recv(msg_len)    # receive the message in full
            msg_type = int.from_bytes(next_packet_data[0:2], byteorder='little')
            dst.sendall(data)   # send the packet size
            dst.sendall(next_packet_data)   # send the message
            return msg_len, msg_type, data, next_packet_data,False
    
    msg_type = int.from_bytes(data[2:4], byteorder='little')
    

    modified_packet = data[2:]

    return msg_len, msg_type, data, modified_packet,True


def handle_gameserver_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    print_prefix = f">>> [GAME|CHATSV] - [{hex(msg_type)}] "
    if msg_len != packet_len:
        print(f"{print_prefix}LEN: {packet_len} MSG_LEN: {msg_len}.. original packet: {original_packet}")
    if msg_type == 0x500:
        #   Log in
        server_id = int.from_bytes(new_packet[2:6],byteorder='little')  # not the slave ID, the server ID given by master server
        session_id,_,remaining_data = new_packet[6:].partition(b'\x00')     # session ID is cookie given by master server
        chat_protocol = int.from_bytes(remaining_data,byteorder='little')   # unlikely to change
        session_id = session_id.decode('utf8')
        print(f"{print_prefix}Logging in...\n\tServer ID: {server_id}\n\tSession ID: {session_id}")
    elif msg_type == 0x2a00:
        print(f"{print_prefix}Sending heartbeat..")
    elif msg_type == 0x502:
        """Send server information
        """
        server_id = int.from_bytes(new_packet[2:6],byteorder='little')
        ip_addr, _, remaining_data = new_packet[6:].partition(b'\x00')
        port = int.from_bytes(remaining_data[0:2],byteorder='little')
        region, _, remaining_data = remaining_data[2:].partition(b'\x00')
        server_name, _, remaining_data = remaining_data.partition(b'\x00')
        slave_id = int.from_bytes(remaining_data[0:2],byteorder='little')
        #   2-4 ? b'\x00\x00'
        match_id = int.from_bytes(remaining_data[4:8],byteorder='little')
        u1 = new_packet[8]  # mb chatserver protocol
        u2 = new_packet[9]  # ?
        u3 = new_packet[10] # ?     this and above 2 combined = 2097155
        #   8-10 ? b'x03\x00 '
        ip_addr = ip_addr.decode('utf-8')
        region = region.decode('utf-8')
        server_name = server_name.decode('utf-8')
        #reversed_bytes = new_packet[::-1]
        #second_null_index = reversed_bytes[1:].find(b'\x00')
        # version_index = second_null_index+8+2   #   there are always 8 null bytes after the hostname in the reversed byte array. add 2 to make up for the skipped null index at the start
        # version_number = reversed_bytes[version_index:].split(b'\x00', 1)[0].decode('utf-8')
        # version_number = version_number[::-1]
        print(f"{print_prefix}Server sent lobby information\n\tIP Addr: {ip_addr}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tSlave ID: {slave_id}\n\tMatch ID: {match_id}")
    elif msg_type == 0x513:
        print(f"{print_prefix}Player connection")
    else:
        print(f"{print_prefix}{new_packet}")

def handle_manager_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    print_prefix = f">>> [MGR|CHATSV] - [{hex(msg_type)}] "
    if msg_len != packet_len:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f"{print_prefix}LEN: {packet_len} MSG_LEN: {msg_len}.. original packet: {original_packet}")
    if msg_type == 0x1600:
        #   Handshake
        #   b'+\x00\x00\x16Y\xf0\x02\x007f9c6567063d467cbf604aa21f220c40\x00F\x00\x00\x00' -mine
        #   b'+\x00\x00\x16Y\xf0\x02\x00f7851dd680764deaabf4bcc447ce5b57\x00F\x00\x00\x00'  -working
        server_id = int.from_bytes(new_packet[2:6],byteorder='little')
        session_id = new_packet[6:].split(b'\x00', 1)[0].decode('utf-8')
        print(f'{print_prefix}Handshake\n\tServer ID: {server_id}\n\tSession: {session_id}')
    elif msg_type == 0x1602:
        #   b'\x02\x16Y\xf0\x02\x00AUSFRANKHOST:\x00NEWERTH\x00T4NK 0\x004.10.6.0\x00103.193.80.121\x00\xe3+\x00' - original
        server_id = int.from_bytes(new_packet[2:6],byteorder='little')
        username,_,remaining_data = new_packet[6:].partition(b'\x00')
        region,_,remaining_data = remaining_data.partition(b'\x00')
        server_name,_,remaining_data = remaining_data.partition(b'\x00')
        version,_,remaining_data = remaining_data.partition(b'\x00')
        ip_addr,_,remaining_data = remaining_data.partition(b'\x00')
        port = int.from_bytes(remaining_data[0:2],byteorder='little')

        username = username.decode('utf8')
        region = region.decode('utf8')
        server_name = server_name.decode('utf8')
        version = version.decode('utf8')
        ip_addr = ip_addr.decode('utf8')

        print(f"{print_prefix}Sending server info:\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Addr: {ip_addr}\n\tAuto-Ping Port: {port}")
    elif msg_type == 0x2a00:
        print(f"{print_prefix}Sending heartbeat..")
    elif msg_type == 0x2a01:
        print(f"{print_prefix}Received heartbeat")
    else:
        print(f"{print_prefix}{new_packet}")

def handle_chatserver_to_gameserver_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    print_prefix = f"<<< [GAME|CHATSV] - [{hex(msg_type)}] "
    if msg_len != packet_len:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f"{print_prefix}LEN: {packet_len} MSG_LEN: {msg_len}.. original packet: {original_packet}")
    if msg_type == 0x1500:
        #   Authenticated
        print(f"{print_prefix}Authenticated to Chat Server")
    elif msg_type == 0x2a01:
        print(f"{print_prefix}Received heartbeat")
    else:
        print(f"{print_prefix}{new_packet}")

def handle_chatserver_to_manager_packet(msg_len, msg_type, original_packet, new_packet):
    packet_len = len(new_packet)
    print_prefix = f"<<< [MGR|CHATSV] - [{hex(msg_type)}] "
    if msg_len != packet_len:
        if msg_type == 0x0: pass    # this is expected because the msg len is provided in the first msg not the 2nd one
        else:
            print(f"{print_prefix}LEN: {packet_len} MSG_LEN: {msg_len}.. original packet: {original_packet}")
    if msg_type == 0x1700:
        print(f'{print_prefix}Handshake accepted')
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
        print(f'{print_prefix}Upload replay\n Account ID: {account_id}\n Match ID: {match_id}\n Extension: {extension}\n Filehost: {filehost}\n Directory: {directory}\n Upload to ftb: {upload_to_ftb}\n Upload to S3: {upload_to_s3}\n Download Link: {download_link}')
    elif msg_type == 0x2a01:
        print(f"{print_prefix}Received heartbeat")
    else:
        # 0x1703: OK to server info? b'\x01\x01\x00\x01\x01\x01\x00\x00\x00'
        # 0x2a01: ? b''
        print(f"{print_prefix}{new_packet}")

def forward(src, dst, src_name, dst_name):
    try:
        while True:
            data = src.recv(4096)
            if len(data) == 0:
                break
            if src_name == "manager":
                msg_len, msg_type, original_packet, new_packet, process_next = parse_packet(data, src, dst, src_name, dst_name)
                handle_manager_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet)
            elif src_name == "gameserver":
                msg_len, msg_type, original_packet, new_packet, process_next = parse_packet(data, src, dst, src_name, dst_name)
                handle_gameserver_to_chatserver_packet(msg_len, msg_type, original_packet, new_packet)
            elif src_name == "chatserver":
                if dst_name == "manager":
                    msg_len, msg_type, original_packet, new_packet, process_next = parse_packet(data, src, dst, src_name, dst_name)
                    handle_chatserver_to_manager_packet(msg_len, msg_type, original_packet, new_packet)
                if dst_name == "gameserver":
                    msg_len, msg_type, original_packet, new_packet, process_next = parse_packet(data, src, dst, src_name, dst_name)
                    handle_chatserver_to_gameserver_packet(msg_len, msg_type, original_packet, new_packet)
            if process_next: dst.sendall(data)
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
    print(f'[*] Listening on {LOCAL_ADDR}:{LOCAL_PORT_MGR} - Manager')

    server_gameserver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_gameserver.bind((LOCAL_ADDR, LOCAL_PORT_SVR))
    server_gameserver.listen(5)
    print(f'[*] Listening on {LOCAL_ADDR}:{LOCAL_PORT_SVR} - GameServer')

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


