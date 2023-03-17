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
import math
from collections import OrderedDict
import traceback
import inspect

# Get the path of the current script
script_dir = os.path.dirname(os.path.abspath(__file__))

# Define the logging directory (in this case, a subdirectory called 'logs')
log_dir = os.path.join(script_dir, '..', 'logs')

# Create the logging directory if it doesn't already exist
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Set up logging to write to a file in the logging directory
log_path = os.path.join(log_dir, 'server.log')

# Set a maximum file size of 10MB for the log file
max_file_size = 10 * 1024 * 1024  # 10MB in bytes
file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=max_file_size, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Create a logger with a specific name for this module
logger = logging.getLogger("Server")
logger.addHandler(file_handler)

# Create a stream handler for outputting logs to the console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

logger.setLevel(logging.DEBUG)

def log_exception(exc_type, exc_value, exc_traceback):
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

# Install exception handler
sys.excepthook = log_exception

def my_print(*args, **kwargs):
    msg = ' '.join(map(str, args))
    logger.info(msg)
    #logger.debug(">")  # Add '>' to log file/console
    print(msg, **kwargs)
    print(">", end=" ", flush=True)

class PacketParser:
    def __init__(self, game_state, client_id):
        self.packet_handlers = {
            0x40: self.server_announce,
            0x41: self.server_closed,
            0x42: self.server_status,
            0x43: self.lobby_status,
            0x44: self.lobby_created,
            0x45: self.lobby_closed,
            0x47: self.server_connection,
            0x4A: self.replay_update,
        }
        self.game_state = game_state
        self.id = client_id

    def update_client_id(self, new_id):
        self.id = new_id

    async def handle_packet(self, packets):
        original_packet, split_packet = packets
        packet_type = split_packet[0]

        # Retrieve the packet handler function based on the packet_type
        handler = self.packet_handlers.get(packet_type, self.unhandled_packet)

        # Call the handler with the split_packet as an argument
        try:
            await handler(split_packet)
        except Exception as e:
            logger.error(f"Error in handler for packet type {packet_type}: {e}")

    async def server_announce(self,packet):        
        """ 0x40  Server announce
        int 0 - msg type
        int 1: (to end) server port
        """
        #my_print(f"Client #{self.id} Received server announce packet")
        port = int.from_bytes(packet[1:],byteorder='little')
        self.game_state.port = port


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
        self.game_state.update({
            'status': packet[1],                                        # extract status field from packet
            'uptime': int.from_bytes(packet[2:6], byteorder='little'),  # extract uptime field from packet
            'num_clients': packet[10],                                  # extract number of clients field from packet
            'match_started': packet[11],                                # extract match started field from packet
            'game_phase': packet[40],                                   # extract game phase field from packet
        })
        # If the packet only contains fixed-length fields, print the game info and return
        if len(packet) == 54:
            return

        # Otherwise, extract player data sections from the packet
        data = packet[53:]                                              # slice the packet to get player data section
        ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')    # define regex pattern for matching IP addresses

        # Parse the player data sections
        clients = []
        for idx, ip_match in enumerate(ip_pattern.finditer(data)):
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
        self.game_state.update({'players': clients})
        #my_print(f'{self.game_state.port} {self.game_state}')


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
            try:
                string_value = packet[current_index:current_index+null_byte_index].decode('utf-8')
            except (UnicodeDecodeError, ValueError) as e:
                inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
                logger.exception(f"An error occurred while handling the %s function: %s with this packet: {packet}", inspect.currentframe().f_code.co_name, traceback.format_exc())
                string_value = ""
                return
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
        self.game_state.update({'match_info':lobby_info})

        # Print the lobby information
        my_print(f"Client #{self.id} {lobby_info}")


    async def lobby_closed(self,packet):
        """   0x45 Lobby closed
        """
        my_print(f"Client #{self.id} Received lobby closed packet:", packet)
        empty_lobby_info = {
            'match_id': '',
            'map': '',
            'name': '',
            'mode': ''
        }
        self.game_state.update({'match_info':empty_lobby_info})


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

class Commands:
    def __init__(self):
        self.command_handlers = {
            "shutdown": self.cmd_shutdown_server,
            "wake": self.cmd_wake_server,
            "sleep": self.cmd_sleep_server,
            "message": self.cmd_server_message,
            "cmd": self.cmd_custom_cmd,
            "status": self.status,
            "reconnect": self.reconnect,
            "help": self.help
        }
    async def handle_input(self, stop_event):
        while not stop_event.is_set():
            command = await aioconsole.ainput("> ")
            try:
                # Split the input into command name and arguments
                command_parts = command.strip().split()
                if not command_parts:
                    print("> ", end="")
                    continue  # Skip if command is empty
                cmd_name = command_parts[0].lower()
                cmd_args = command_parts[1:]

                if cmd_name == "quit":
                    stop_event.set()
                    break
                elif cmd_name in self.command_handlers:
                    handler = self.command_handlers[cmd_name]
                    await handler(*cmd_args)
                else:
                    my_print("Unknown command:", command)

            except Exception as e:
                logger.exception("An error occurred while handling the command: %s", e)
    
    async def cmd_shutdown_server(self, *cmd_args):
        global client_connections
        try:
            if len(cmd_args) != 1:
                raise ValueError("Usage: shutdown <client_index>")

            client_index = int(cmd_args[0]) - 1
            client = list(client_connections.values())[client_index]
            length_bytes = b'\x01\x00'
            message_bytes = b'"'
            client.writer.write(length_bytes)
            client.writer.write(message_bytes)
            await client.writer.drain()
            my_print(f"Shutdown packet sent to {client.addr[0]}:{client.addr[1]}")

        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, *cmd_args):
        global client_connections
        try:
            if len(cmd_args) != 1:
                raise ValueError("Usage: wake <client_index>")

            client_index = int(cmd_args[0]) - 1
            client = list(client_connections.values())[client_index]
            length_bytes = b'\x01\x00'
            message_bytes = b'!'
            client.writer.write(length_bytes)
            client.writer.write(message_bytes)
            await client.writer.drain()
            my_print(f"Wake packet sent to {client.addr[0]}:{client.addr[1]}")
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, *cmd_args):
        global client_connections
        try:
            if len(cmd_args) != 1:
                raise ValueError("Usage: sleep <client_index>")

            client_index = int(cmd_args[0]) - 1
            client = list(client_connections.values())[client_index]
            length_bytes = b'\x01\x00'
            message_bytes = b' '
            client.writer.write(length_bytes)
            client.writer.write(message_bytes)
            await client.writer.drain()
            my_print(f"Sleep packet sent to {client.addr[0]}:{client.addr[1]}")
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_server_message(self, *cmd_args):
        global client_connections
        try:
            if len(cmd_args) < 2:
                raise ValueError("Usage: message <client_index> <message>")
            client_index = int(cmd_args[0]) - 1
            client = list(client_connections.values())[client_index]
            message = ' '.join(cmd_args[1:])
            message_bytes = message.encode('ascii')
            length = len(message_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')
            client.writer.write(length_bytes)
            client.writer.write(message_bytes)
            await client.writer.drain()
            my_print(f"Message packet sent to {client.addr[0]}:{client.addr[1]}")
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def cmd_custom_cmd(self, *cmd_args):
        global client_connections
        try:
            if len(cmd_args) < 2:
                raise ValueError("Usage: cmd <client_index> <data>")

            client_index = int(cmd_args[0]) - 1
            if client_index < 0 or client_index >= len(client_connections):
                raise ValueError(f"Invalid client index: {client_index+1}")
            client = list(client_connections.values())[client_index]
            data = b''
            for part in cmd_args[1:]:
                if re.fullmatch(r'[0-9a-fA-F]+', part):
                    data += bytes.fromhex(part)
                else:
                    data += part.encode('ascii')
            client.writer.write(data)
            await client.writer.drain()
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def status(self):
        global client_connections
        try:
            # Print status of all connected clients
            if len(client_connections) == 0:
                my_print("No clients connected.")
                return

            headers = []
            rows = []
            for client in client_connections.values():
                status = client.game_state.get_status()
                data = []
                for k, v in status.items():
                    if k not in headers:
                        headers.append(k)
                    data.append(v)
                rows.append(data)

            table = columnar(rows, headers=headers)
            my_print(table)
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def reconnect(self):
        try:
            # Close all client connections, forcing them to reconnect
            for connection in client_connections.values():
                await connection.close()
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def help(self):
        try:
            headers = ["Command", "Description"]
            rows = [
                ["list", "Show list of connected clients"],
                ["status", "Show status of connected clients"],
                ["sleep <index>", "Put a client server to sleep"],
                ["wake <index>", "Wake up a client server"],
                ["send <index> <data>", "Send data to a client"],
                ["message <index> <message>", "Send a message to a client"],
                ["shutdown <index>", "Shutdown a client server"],
                ["reconnect", "Close all client connections, forcing them to reconnect"],
                ["quit", "Quit the proxy server"],
                ["help", "Show this help text"],
            ]
            table = columnar(rows, headers=headers)
            my_print(table)
        except Exception as e:
            inspect.currentframe().f_code.co_name = inspect.currentframe().f_code.co_name
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
class GameState:
    def __init__(self, client_id):
        self.status = None
        self.uptime = None
        self.num_clients = None
        self.match_started = None
        self.game_state_phase = None
        self.players = []
        self.port = None
        self.id = client_id
    
    def update_client_id(self, new_id):
        self.id = new_id

    def update(self, game_data):
        self.__dict__.update(game_data)

    def get(self, attribute, default=None):
        return getattr(self, attribute, default)
    
    def get_status(self):
        def format_time(seconds):
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            days, hours = divmod(hours, 24)

            time_str = ""
            if days > 0:
                time_str += f"{days}d "
            if hours > 0:
                time_str += f"{hours}h "
            if minutes > 0:
                time_str += f"{math.ceil(minutes)}m "
            if seconds > 0:
                time_str += f"{math.ceil(seconds)}s"

            return time_str.strip()

        temp = {
            'ID': self.id,
            'Port': self.port,
            'Status': 'Unknown',
            'Game Phase': 'Unknown',
            'Players': 0,
            'Uptime': 'Unknown'
        }

        if self.status == 1:
            temp['Status'] = 'Ready'
        elif self.status == 3:
            temp['Status'] = 'Active'

        game_phase_mapping = {
            0: '',
            1: 'In-Lobby',
            2: 'Picking Phase',
            3: 'Picking Phase',
            4: 'Loading into match..',
            5: 'Preparation Phase',
            6: 'Match Started',
        }
        temp['Game Phase'] = game_phase_mapping.get(self.game_phase, 'Unknown')
        temp['Players'] = self.num_clients
        temp['Uptime'] = format_time(self.uptime / 1000) if self.uptime is not None else 'Unknown'

        return temp
class ClientConnection:
    def __init__(self, reader, writer, addr):
        self.reader = reader
        self.writer = writer
        self.addr = addr
        self.id = None
        self.game_state = GameState(client_id=None)
        self.packet_parser = PacketParser(self.game_state, self.id)
    
        # Set TCP keepalive on the socket
        sock = self.writer.get_extra_info('socket')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

    def set_id(self, new_id):
        self.id = new_id
        self.packet_parser.update_client_id(new_id)
        self.game_state.update_client_id(new_id)

    async def receive_packet(self, timeout = 600):
        try:
            # Try to read up to 2 bytes for the length field
            length_bytes = await self.reader.read(2)

            # If we didn't receive at least 2 bytes, return None
            if len(length_bytes) == 0:
                return None
            elif len(length_bytes) == 1:
                my_print(f"Client #{self.id} Single byte packet: {length_bytes} received.")
                logging.warn(f"Client #{self.id} Single byte packet: {length_bytes} received.")

            # Otherwise, proceed to read the rest of the packet
            length = int.from_bytes(length_bytes, byteorder='little')
            # Wait for the next `length` bytes to get the packet data
            data = await asyncio.wait_for(self.reader.readexactly(length), timeout)

            packet = (length, data)
            return packet, data

        except asyncio.TimeoutError as e:
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            # Raise a timeout error if the packet did not arrive within the specified timeout
            raise TimeoutError("Packet reception timed out")

        except ConnectionResetError as e:
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

            # Check if the writer object is not None before closing it
            if self.writer is not None:
                await self.writer.close()

        except ValueError as e:
            logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            # Handle incomplete length field in packet
            my_print(f"Error receiving packet: {e}")
            return b"", b""

    async def handle_packet(self, packets):
        # Use the PacketParser instance to handle the packet
        await self.packet_parser.handle_packet(packets)

    async def run(self):
        while True:
            try:
                packets = await self.receive_packet()

                if packets is None:
                    # Handle the case where the packet is incomplete
                    my_print(f"Client #{self.id} Incomplete packet: {packets}. Closing connection..")
                    break
            except (ConnectionResetError, asyncio.IncompleteReadError) as e:
                logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                # Connection closed by client or incomplete packet received
                break
            except TimeoutError as e:
                logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                # Packet reception timed out
                my_print(f"{self.id} Packet reception timed out")
                continue
            except Exception as e:
                logger.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                # Handle other unexpected exceptions gracefully
                my_print(f"An unexpected error occurred: {e}")
                break

            await self.handle_packet(packets)

            # Add a small delay to allow other clients to send packets
            await asyncio.sleep(0.01)
        # Remove this client connection from the dictionary
        if self.game_state.port in client_connections:
            my_print(f"Client #{self.id} has been disconnected.")
            del client_connections[self.game_state.port]

    async def send_packet(self, packet):
        data = bytes(packet)
        self.writer.write(data)
        await self.writer.drain()


    async def close(self):
        global client_connections
        my_print(f"Terminating client #{self.id}..")
        self.reader.close()
        self.writer.close()
        await self.writer.wait_closed()
        # Remove this client connection from the dictionary
        if self.game_state.port in client_connections:
            del client_connections[self.game_state.port]
    
async def handle_client_connection(client_reader, client_writer):
    global client_connections

    # Get the client address
    client_addr = client_writer.get_extra_info("peername")

    my_print(f"Client connected from {client_addr[0]}:{client_addr[1]}")

    # Create a new ClientConnection object to handle this client
    client_connection = ClientConnection(client_reader, client_writer, client_addr)

    try:
        # Wait for the server hello packet
        packets = await client_connection.receive_packet()

        if packets is None:
            # Handle the case where the packet is incomplete
            my_print(f"Incomplete packet received from {client_addr[0]}:{client_addr[1]}")
            return

        if packets[1][0] != 0x40:
            my_print(f"Waiting for server hello from {client_addr[0]}:{client_addr[1]}...")
            return

        # Process the server hello packet
        await client_connection.handle_packet(packets)

        # Add client connection object to the dictionary
        client_connections[client_connection.game_state.port] = client_connection

        # Sort client connections based on server port
        client_connections = OrderedDict(sorted(client_connections.items(), key=lambda c: c[1].game_state.port))

        # Set client ids based on the order in the sorted dictionary
        for i, client in enumerate(client_connections.values(), 1):
            client.set_id(i)

        # Run the client connection coroutine
        await client_connection.run()

    except (ConnectionResetError, asyncio.exceptions.IncompleteReadError, asyncio.CancelledError) as e:
        logger.exception(f"Client #{client_connection.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
        # Connection closed by client, server, or incomplete packet received

    finally:
        client_writer.close()
        await client_writer.wait_closed()

        if client_connection.game_state.port in client_connections:
            my_print(f"Client #{client_connection.id} has been disconnected.")
            del client_connections[client_connection.game_state.port]

async def handle_clients(client_reader, client_writer):
    # Create a new task to handle this client connection
    asyncio.create_task(handle_client_connection(client_reader, client_writer))

async def main():
    global client_connections

    host = "127.0.0.1"
    port = 1234
    client_connections = {}  # dictionary to store client connections
    
    server = await asyncio.start_server(
        handle_clients, host, port
    )

    my_print(f"Listening on {host}:{port}")

    # Create a stop event to signal when the server should stop
    stop_event = asyncio.Event()

    # Initialize the Commands class with the client_connections and packet_parser
    commands = Commands()

    # Handle user input in a separate coroutine
    input_task = asyncio.create_task(commands.handle_input(stop_event))

    # Wait for either the stop event to be set or for the client task to complete
    done, pending = await asyncio.gather(
        stop_event.wait(),
        input_task,
        return_exceptions=True
    )

    if pending is not None:
        for task in pending:
            # Cancel any remaining pending tasks here
            task.cancel()

    # Close all client connections
    for connection in client_connections.values():
        await connection.close()

    # Close the server
    server.close()
    await server.wait_closed()

    my_print("Server stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down the server gracefully...")