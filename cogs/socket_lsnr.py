import socket
import struct
import time
import re
import threading
from columnar import columnar

def my_print(*args, **kwargs):
    print(*args, **kwargs)
    print(">", end=" ", flush=True)
class ClientConnection:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.last_received = time.time()
        self.lock = threading.Lock()
        self.game = {}

    def run(self):
        global client_connections

        while True:
            try:
                packet = self.receive_packet()
            except ConnectionResetError:
                # Connection closed by client
                break
            if packet[0] is None or packet[0] == b'':
                # Connection closed by client
                break
            self.handle_packet(packet)

        # Handle client disconnect
        with self.lock:
            del client_connections[self.addr]
            self.sock.close()
            my_print(f"Client disconnected from {self.addr[0]}:{self.addr[1]}")

    def receive_packet(self):
        # Read the first two bytes to get the length of the packet
        length_bytes = self.sock.recv(2)
        length = int.from_bytes(length_bytes, "little")

        # Read the remaining bytes of the packet
        remaining_bytes = length
        data = b""
        while remaining_bytes > 0:
            chunk = self.sock.recv(remaining_bytes)
            if not chunk:
                # The socket has been closed
                return None
            data += chunk
            remaining_bytes -= len(chunk)

        # Check if there are any remaining bytes after parsing the packet
        if len(data) > length:
            # Recursively call receive_packet to parse the remaining bytes
            remaining_data = data[length:]
            remaining_packet = self.receive_packet(remaining_data)
            return (length_bytes + data[:length], data[:length]) + remaining_packet
        else:
            return length_bytes + data, data


    def handle_packet(self, packet):
        original_packet, split_packet = packet
        packet_type = split_packet[0]
        if packet_type == 0x40:
            self.server_announce(split_packet)
        elif packet_type == 0x41:
            self.server_closed(split_packet)
        elif packet_type == 0x42:
            self.server_status(split_packet)
        elif packet_type == 0x43:
            self.lobby_status(split_packet)
        elif packet_type == 0x44:
            self.lobby_created(split_packet)
        elif packet_type == 0x45:
            self.lobby_closed(split_packet)
        elif packet_type == 0x47:
            self.server_connection(split_packet)
        elif packet_type == 0x4A:
            self.replay_update(split_packet)
        else:
            self.unhandled_packet(split_packet)

    def schedule_shutdown(self):
        while True:
            if self.game['num_clients'] == 0:
                self.shutdown_server()
                break
            else:
                time.sleep(1)

    def shutdown_server(self):
        """ 
            Send a command to shut down the server.
            By default this does NOT schedule shut down, scheduling must be managed seperately
        """
        self.sock.send(b'\x01\x00')
        self.sock.send(b'"')
        #self.sock.close()
        my_print(f"Shutdown packet sent to {self.addr[0]}:{self.addr[1]}")

    def wake_server(self):
        self.sock.send(b'\x01\x00')
        self.sock.send(b'!')
        my_print(f"Wake packet sent to {self.addr[0]}:{self.addr[1]}")

    def sleep_server(self):
        self.sock.send(b'\x01\x00')
        self.sock.send(b' ')
        my_print(f"Sleep packet sent to {self.addr[0]}:{self.addr[1]}")
    
    def server_message(self,message):
        length = len(message)
        length_bytes = length.to_bytes(2, byteorder='little')
        self.sock.send(length_bytes)
        self.sock.send(message)
        my_print(f"Message packet sent to {self.addr[0]}:{self.addr[1]}")

    def server_announce(self,packet):
        """ 0x40  Server announce
        int 0 - msg type
        int 1: (to end) server port
        """
        my_print("Received server announce packet")
        self.port = int.from_bytes(packet[1:],byteorder='little')
        my_print(f"Connecting server is operating under port: {self.port}")
        self.game['port'] = self.port


    def server_closed(self,packet):
        """  0x41 Server closed
        when the server is killed / crashes / gracefully stopped.

        I have noticed since pretending to be manager, the server will terminate after 10 minutes with the following message:
            [Mar 13 11:54:25] Sv: [11:54:25] No users currently connected and received last manager communication 10 minutes ago, shutting down.
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down...
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down server...

        """
        my_print(f"Received server closed packet:", packet)


    def server_status(self,packet):
        """  0x42 Server status update packet.
            
                The most valuable packet so far, is sent multiple times a second, contains all "live" state including:
                playercount, game phase, game state, client information

                Total Length is 54 w 0 Players
                Contains:
                    int 1 msg_type			# 0
                    int 1 status			# 1
                    int 4 uptime			# 2-6
                    int 4 unknown			# 6-10
                    int 1 num_clients1		# 10
                    int 1 match_started		# 11
                    int 4 unknown           # 12-16
                    int 4 unknown           # 16-20
                    int 4 unknown           # 20-24
                    int 4 unknown           # 24-28
                    int 4 unknown           # 28-32
                    int 4 unknown           # 32-36
                    int 4 unknown           # 36-40
                    int 1 game_phase        # 40
                    int 4 unknown           # 40-44
                    int 4 unknown           # 44-48
                    int 4 unknown           # 48-52
                    int 1 num_clients2      # 53
                With Players, first 54 bytes remains as fixed values, so treat them first. Additional data is tacked on the end as the clients. See code below for parsing
        """
        # Parse fixed-length fields
        self.game.update({
            'status': packet[1],                                        # extract status field from packet
            'uptime': int.from_bytes(packet[2:6], byteorder='little'),  # extract uptime field from packet
            'num_clients': packet[10],                                  # extract number of clients field from packet
            'match_started': packet[11],                                # extract match started field from packet
            'game_phase': packet[40],                                   # extract game phase field from packet
            'num_clients2': packet[53]                                  # extract number of clients field from packet
        })
        # If the packet only contains fixed-length fields, print the game info and return
        if len(packet) == 54:
            # try:
            #     my_print(f'{self.port} {self.game}')
            # except AttributeError:
            #     my_print(f'{self.game}')
            return

        # Otherwise, extract player data sections from the packet
        data = packet[53:]                                              # slice the packet to get player data section
        ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')    # define regex pattern for matching IP addresses

        # Parse the player data sections
        clients = []
        for ip_match in ip_pattern.finditer(data):
            # Extract IP address, username, account ID, and location from the player data section
            ip_start, ip_end = ip_match.span()
            name_start = data[ip_end:].find(b'\x00') + ip_end
            name_end = data[name_start+1:].find(b'\x00') + name_start + 1
            name = data[name_start:name_end].decode('utf-8').replace('\x00', '')
            account_id = int.from_bytes(data[ip_start-4:ip_start], byteorder='little')
            location_start = data[name_end+1:].find(b'\x00') + name_end + 1
            location_end = data[location_start+1:].find(b'\x00') + location_start + 1
            location = data[location_start:location_end-1].decode('utf-8') if location_start > name_end+1 else ''
            
            # Append extracted data to the clients list as a dictionary
            clients.append({
                'account_id': account_id,
                'name': name,
                'location': location,
                'ip': data[ip_start:ip_end].decode('utf-8')
            })
        # Update game dictionary with player information and print
        self.game.update({'players': clients})
        #my_print(f'{self.port} {self.game}')


    def lobby_status(self,packet):
        """  0x43 Lobby status
        typically this occurs when a lobby is created, or a lobby is started. Unsure what a lot of the info is. All the clients are in here, however I focused on parsing them in 0x42 as 0x42 contains all the same info from what I can see.
        to summarise, a mostly useless packet.
        """
        my_print(f"Received lobby status update")


    def lobby_created(self,packet):
        """  0x44 Lobby created
                int 4 matchid (64 bit for futureproof) # 0-4
                string date     ? didnt find
                string map
                string game name
                string game mode
                int 1 unknown
        """
        my_print(f"Received lobby created packet")

        # Extract the match ID from the packet bytes
        match_id_bytes = packet[1:5]
        match_id = sum([match_id_bytes[i] * (256 ** i) for i in range(len(match_id_bytes))])

        # Extract the strings from the packet bytes
        strings = []
        current_index = 6
        while current_index < len(packet):
            # Find the null byte that terminates the current string
            null_byte_index = packet[current_index:].index(b'\x00')
            # Extract the current string and append it to the list of strings
            string_value = packet[current_index:current_index+null_byte_index].decode('utf-8')
            strings.append(string_value)
            # Update the current index to point to the next string
            current_index += null_byte_index + 1

        # Extract the unknown string from the packet bytes
        unknown = packet[28:32].decode('utf-8').rstrip('\x00')

        # Create a dictionary containing the lobby information
        lobby_info = {
            'match_id': match_id,
            'map': strings[0],
            'name': strings[1],
            'mode': strings[2]
        }

        # Print the lobby information
        my_print(lobby_info)


    def lobby_closed(self,packet):
        """   0x45 Lobby closed
        """
        my_print(f"Received lobby closed packet:", packet)


    def server_connection(self,packet):
        """ 0x47 Server selected / player joined
                
                This packet arrives any time someone begins connecting to the server
        """
        my_print(f"Received server selected packet (no lobby):", packet)
    

    def replay_update(self,packet):
        """ 0x4A Replay status packet
        
            This is an update from the game server regarding the status of the zipped replay file.
            Most likely for the manager to upload incrementally, if that setting is on (default not on)
        """
        my_print(f"Received replay zip update:", packet)


    def unhandled_packet(self,packet):
            """    Any unhandled packet
            """
            my_print(f"Received unknown packet:", packet)

    def get_status(self):
        with self.lock:
            return self.game

def handle_input(client_connections):
    while True:
        try:
            command = input("").strip().lower()
            if not command:
                print("> ",end="")
                continue  # Skip if command is empty
            elif command.lower() == "exit":
                # Exit command shell
                break
            elif command.lower() == "list":
                # Print list of connected clients
                if len(client_connections) == 0:
                    my_print("No clients connected.")
                    continue
                headers = ["Index", "IP Address", "Port"]
                rows = [[i+1, addr[0], addr[1]] for i, (addr, client) in enumerate(client_connections.items())]
                table = columnar(rows, headers=headers)
                my_print(table)
            elif command.lower() == "status":
                if len(client_connections) == 0:
                    my_print("No clients connected.")
                    continue
                headers = ["Index", "Client", "Status"]
                rows = []
                for i, client in enumerate(client_connections.values()):
                    status = client.get_status()
                    if status is None:
                        rows.append([i+1, str(client), "Not connected"])
                    else:
                        rows.append([i+1, str(client), status])
                table = columnar(rows, headers=headers)
                my_print(table)
            elif command.lower().startswith("sleep"):
                # Parse sleep command
                parts = command.split()
                if len(parts) < 2:
                    raise ValueError("Usage: sleep <client_index>")
                client_index = int(parts[1]) - 1
                if client_index < 0 or client_index >= len(client_connections):
                    raise ValueError(f"Invalid client index: {client_index+1}")
                client = list(client_connections.values())[client_index]
                client.sleep_server()
            elif command.lower().startswith("wake"):
                # Parse sleep command
                parts = command.split()
                if len(parts) < 2:
                    raise ValueError("Usage: wake <client_index>")
                client_index = int(parts[1]) - 1
                if client_index < 0 or client_index >= len(client_connections):
                    raise ValueError(f"Invalid client index: {client_index+1}")
                client = list(client_connections.values())[client_index]
                client.wake_server()
            elif command.lower().startswith("send"):
                # Parse send command
                parts = command.split()
                if len(parts) < 3:
                    raise ValueError("Usage: send <client_index> <data>")
                client_index = int(parts[1]) - 1
                if client_index < 0 or client_index >= len(client_connections):
                    raise ValueError(f"Invalid client index: {client_index+1}")
                client = list(client_connections.values())[client_index]
                data = b''
                for part in parts[2:]:
                    if re.fullmatch(r'[0-9a-fA-F]+', part):
                        # If part is a hex string, convert it to bytes
                        data += bytes.fromhex(part)
                    else:
                        # Otherwise, it's an ASCII string, encode it to bytes
                        data += part.encode('ascii')
                client.sock.send(data)
            elif command.lower().startswith("message"):
                # Parse message command
                parts = command.split()
                if len(parts) < 3:
                    raise ValueError("Usage: message <client_index> <message>")
                client_index = int(parts[1]) - 1
                if client_index < 0 or client_index >= len(client_connections):
                    raise ValueError(f"Invalid client index: {client_index+1}")
                client = list(client_connections.values())[client_index]
                message = ' '.join(parts[2:])
                data = b'$' + message.encode('ascii') + b'\x00'
                client.server_message(data)
            elif command.lower().startswith("shutdown"):
                # Parse shutdown command
                parts = command.split()
                if len(parts) < 2:
                    raise ValueError("Usage: shutdown <client_index>")
                client_index = int(parts[1]) - 1
                if client_index < 0 or client_index >= len(client_connections):
                    raise ValueError(f"Invalid client index: {client_index+1}")
                client = list(client_connections.values())[client_index]
                shutdown_thread = threading.Thread(target=client.schedule_shutdown)
                shutdown_thread.start()
            elif command.lower() == "help":
                headers = ["Command", "Description"]
                rows = [
                    ["list", "Show list of connected clients"],
                    ["status", "Show status of connected clients"],
                    ["send <index> <data>", "Send data to a client"],
                    ["shutdown <index>", "Shutdown a client server"],
                    ["exit", "Exit the command shell"]
                ]
                table = columnar(rows, headers=headers)
                my_print(table)
            else:
                raise ValueError(f"Invalid command: {command}")
        except Exception as e:
            my_print(f"Error: {e}")


def main():
    global client_connections

    host = "127.0.0.1"
    port = 1234
    client_connections = {}  # dictionary to store client connections

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((host, port))
    server_sock.listen(10)

    my_print(f"Listening on {host}:{port}")

    command_thread = threading.Thread(target=handle_input, args=(client_connections,))
    command_thread.start()

    while True:
        client_sock, client_addr = server_sock.accept()
        my_print(f"Client connected from {client_addr[0]}:{client_addr[1]}")

        # Create a new thread to handle the client connection
        client_connection = ClientConnection(client_sock, client_addr)
        client_connections[client_addr] = client_connection
        client_thread = threading.Thread(target=client_connection.run)
        client_thread.start()

if __name__ == "__main__":
    main()