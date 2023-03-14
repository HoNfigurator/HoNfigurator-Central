import socket
import struct
import time
import re
import asyncio
from columnar import columnar
import aioconsole
import logging
import logging.handlers
import sys,os

# Get the path of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Define the logging directory (in this case, a subdirectory called 'logs')
log_dir = os.path.join(script_dir, '..\\logs')

# Create the logging directory if it doesn't already exist
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Set up logging to write to a file in the logging directory
log_path = os.path.join(log_dir, 'server.log')
logging.basicConfig(filename=log_path, level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Set a maximum file size of 10MB for the log file
max_file_size = 10 * 1024 * 1024  # 10MB in bytes
file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=max_file_size, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(file_handler)

def exception_handler(type, value, traceback):
    logging.exception("Uncaught exception: ", exc_info=(type, value, traceback))

# Install exception handler
sys.excepthook = exception_handler

def my_print(*args, **kwargs):
    msg = ' '.join(map(str, args))
    logging.debug(msg)
    #logging.debug(">")  # Add '>' to log file/console
    print(msg, **kwargs)
    print(">", end=" ", flush=True)

class ClientConnection:
    def __init__(self, sock, addr, client_index):
        self.sock = sock
        self.addr = addr
        self.last_received = time.time()
        self.game = {}
        self.id = client_index

    async def run(self):
        global client_connections

        while True:
            try:
                packet = await self.receive_packet()
            except ConnectionResetError:
                # Connection closed by client
                break
            if packet[0] is None or packet[0] == b'':
                # Connection closed by client
                #   TODO: Check if this should be continue
                break
            await self.handle_packet(packet)

        del client_connections[self.id]
        self.sock.close()
        my_print(f"Client#{self.id} disconnected from {self.addr[0]}:{self.addr[1]}")

    async def receive_packet(self):
        # Read the first two bytes to get the length of the packet
        length_bytes = await asyncio.get_running_loop().sock_recv(self.sock, 2)
        length = int.from_bytes(length_bytes, "little")

        # Read the remaining bytes of the packet
        remaining_bytes = length
        data = b""
        while remaining_bytes > 0:
            chunk = await asyncio.get_running_loop().sock_recv(self.sock, remaining_bytes)
            if not chunk:
                # The socket has been closed
                return None
            data += chunk
            remaining_bytes -= len(chunk)

        # Check if there are any remaining bytes after parsing the packet
        if len(data) > length:
            # Recursively call receive_packet to parse the remaining bytes
            remaining_data = data[length:]
            remaining_packet = await self.receive_packet(remaining_data)
            return (length_bytes + data[:length], data[:length]) + remaining_packet
        else:
            return length_bytes + data, data


    async def handle_packet(self, packet):
        original_packet, split_packet = packet
        packet_type = split_packet[0]
        if packet_type == 0x40:
            await self.server_announce(split_packet)
        elif packet_type == 0x41:
            await self.server_closed(split_packet)
        elif packet_type == 0x42:
            await self.server_status(split_packet)
        elif packet_type == 0x43:
            await self.lobby_status(split_packet)
        elif packet_type == 0x44:
            await self.lobby_created(split_packet)
        elif packet_type == 0x45:
            await self.lobby_closed(split_packet)
        elif packet_type == 0x47:
            await self.server_connection(split_packet)
        elif packet_type == 0x4A:
            await self.replay_update(split_packet)
        else:
            await self.unhandled_packet(split_packet)
    async def schedule_shutdown(self):
        while True:
            if self.game['num_clients'] == 0:
                await self.shutdown_server()
                break
            else:
                await asyncio.sleep(1)

    async def shutdown_server(self):
        """ 
            Send a command to shut down the server.
            By default this does NOT schedule shut down, scheduling must be managed separately
        """
        self.sock.send(b'\x01\x00')
        self.sock.send(b'"')
        #self.sock.close()
        my_print(f"Shutdown packet sent to client #{self.id}")

    async def wake_server(self):
        self.sock.send(b'\x01\x00')
        self.sock.send(b'!')
        my_print(f"Wake packet sent to client #{self.id}")

    async def sleep_server(self):
        self.sock.send(b'\x01\x00')
        self.sock.send(b' ')
        my_print(f"Sleep packet sent to client #{self.id}")
    
    async def server_message(self,message):
        length = len(message)
        length_bytes = length.to_bytes(2, byteorder='little')
        self.sock.send(length_bytes)
        self.sock.send(message)
        my_print(f"Message packet sent to client #{self.id}")

    async def server_announce(self,packet):
        global client_connections
        
        """ 0x40  Server announce
        int 0 - msg type
        int 1: (to end) server port
        """
        #my_print(f"Client #{self.id} Received server announce packet")
        self.port = int.from_bytes(packet[1:],byteorder='little')
        my_print(f"Client #{self.id} is operating under port: {self.port}")
        self.game['port'] = self.port


    async def server_closed(self,packet):
        """  0x41 Server closed
        when the server is killed / crashes / gracefully stopped.

        I have noticed since pretending to be manager, the server will terminate after 10 minutes with the following message:
            [Mar 13 11:54:25] Sv: [11:54:25] No users currently connected and received last manager communication 10 minutes ago, shutting down.
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down...
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down server...

        """
        my_print(f"Client #{self.id} Received server closed packet:", packet)


    async def server_status(self,packet):
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


    async def lobby_status(self,packet):
        """  0x43 Lobby status
        typically this occurs when a lobby is created, or a lobby is started. Unsure what a lot of the info is. All the clients are in here, however I focused on parsing them in 0x42 as 0x42 contains all the same info from what I can see.
        to summarise, a mostly useless packet.
        """
        my_print(f"Client #{self.id} Received lobby status update")


    async def lobby_created(self,packet):
        """  0x44 Lobby created
                int 4 matchid (64 bit for futureproof) # 0-4
                string date     ? didnt find
                string map
                string game name
                string game mode
                int 1 unknown
        """
        my_print(f"Client #{self.id} Received lobby created packet")

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
        my_print(f"Client #{self.id} {lobby_info}")


    async def lobby_closed(self,packet):
        """   0x45 Lobby closed
        """
        my_print(f"Client #{self.id} Received lobby closed packet:", packet)


    async def server_connection(self,packet):
        """ 0x47 Server selected / player joined
                
                This packet arrives any time someone begins connecting to the server
        """
        my_print(f"Client #{self.id} Received server connection packet:", packet)
    

    async def replay_update(self,packet):
        """ 0x4A Replay status packet
        
            This is an update from the game server regarding the status of the zipped replay file.
            Most likely for the manager to upload incrementally, if that setting is on (default not on)
        """
        my_print(f"Client #{self.id} Received replay zip update:", packet)


    async def unhandled_packet(self,packet):
            """    Any unhandled packet
            """
            my_print(f"Client #{self.id} Received unknown packet:", packet)

    async def get_status(self):
        return self.game
async def handle_client_connection(client_sock, client_addr, client_index):
    global client_connections

    my_print(f"Client connected from {client_addr[0]}:{client_addr[1]}")

    # Create a new ClientConnection object to handle this client
    client_connection = ClientConnection(client_sock, client_addr, client_index)
    
    # Wait for the server hello packet
    try:
        packet = await client_connection.receive_packet()
    except ConnectionResetError:
        # Connection closed by client
        return
    if packet[1][0] != 0x40:
        my_print(f"Waiting for server hello from Client #{client_connection.id}...")
        return
    await client_connection.handle_packet(packet)

    # Add client connection object to the dictionary
    client_connections[client_index] = client_connection
    
    # Sort client connections based on server port
    client_connections = {c.id: c for c in sorted(client_connections.values(), key=lambda c: getattr(c, 'game', {}).get('port', None))}
    
    # Run the client connection coroutine
    await client_connection.run()

async def handle_input():
    global client_connections

    while True:
        command = await aioconsole.ainput("> ")
        if not command:
            print("> ",end="")
            continue  # Skip if command is empty
        elif command == "quit":
            # Close all client connections and exit
            for connection in client_connections.values():
                connection.sock.close()
            break
        elif command.lower() == "list":
            # Print list of connected clients
            if len(client_connections) == 0:
                my_print("No clients connected.")
                continue
            headers = ["Index", "IP Address", "Port"]
            rows = []
            for client in client_connections.values():
                rows.append([client.id, client.addr[0], client.port if client.port is not None else 'None'])
            table = columnar(rows, headers=headers)
            my_print(table)
        elif command == "status":
            # Print status of all connected clients
            if len(client_connections) == 0:
                my_print("No clients connected.")
                continue
            data = []
            for client in client_connections.values():
                status = await client.get_status()
                data.append([client.id,client.port if client.port is not None else 'None', status])
            headers = ["#", "Port", "Status"]
            table = columnar(data, headers=headers)
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
            await client.sleep_server()
        elif command.lower().startswith("wake"):
            # Parse sleep command
            parts = command.split()
            if len(parts) < 2:
                raise ValueError("Usage: wake <client_index>")
            client_index = int(parts[1]) - 1
            if client_index < 0 or client_index >= len(client_connections):
                raise ValueError(f"Invalid client index: {client_index+1}")
            client = list(client_connections.values())[client_index]
            await client.wake_server()
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
            await client.sock.send(data)
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
                await client.server_message(data)
        elif command.lower().startswith("shutdown"):
            # Parse shutdown command
            parts = command.split()
            if len(parts) < 2:
                raise ValueError("Usage: shutdown <client_index>")
            client_index = int(parts[1]) - 1
            if client_index < 0 or client_index >= len(client_connections):
                raise ValueError(f"Invalid client index: {client_index+1}")
            client = list(client_connections.values())[client_index]
            await client.schedule_shutdown()
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
        # else:
        #     my_print("Unknown command:", command)

async def main():
    global client_connections

    host = "127.0.0.1"
    port = 1135
    client_connections = {}  # dictionary to store client connections

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((host, port))
    server_sock.listen(10)

    my_print(f"Listening on {host}:{port}")

    # Handle user input in a separate coroutine
    loop = asyncio.get_running_loop()
    loop.create_task(handle_input())

    client_index = 0
    while True:
        client_sock, client_addr = await loop.sock_accept(server_sock)
        # Create a new task to handle this client connection
        loop.create_task(handle_client_connection(client_sock, client_addr, client_index))
        client_index += 1
if __name__ == "__main__":
    asyncio.run(main())