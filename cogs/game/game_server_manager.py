# Import required modules
import phpserialize
import traceback
import asyncio
import hashlib
import os.path
import time
import inspect
from cogs.misc.exceptions import ServerConnectionError, AuthenticationError
from cogs.connectors.masterserver_connector import MasterServerHandler
from cogs.connectors.chatserver_connector import ChatServerHandler
from cogs.TCP.game_packet_lsnr import handle_clients
from cogs.TCP.auto_ping_lsnr import AutoPingListener
from cogs.connectors.api_server import start_api_server
from cogs.game.game_server import GameServer
from cogs.handlers.commands import Commands
from cogs.handlers.events import stop_event, EventBus as ManagerEventBus
from cogs.misc.logging import get_logger, get_misc
from enum import Enum
from os.path import exists

LOGGER = get_logger()
MISC = get_misc()

# TCP Command definitions
COMMAND_LEN_BYTES = b'\x01\x00'
SHUTDOWN_BYTES = b'"'
SLEEP_BYTES = b' '
WAKE_BYTES = b'!'

# Define an Enum class for health checks
class HealthChecks(Enum):
    public_ip_healthcheck = 1
    general_healthcheck = 2
    lag_healthcheck = 3
class ReplayStatus(Enum):
    NONE = -1
    GENERAL_FAILURE = 0
    DOES_NOT_EXIST = 1
    INVALID_HOST = 2
    ALREADY_UPLOADED = 3
    ALREADY_QUEUED = 4
    QUEUED = 5
    UPLOADING = 6
    UPLOAD_COMPLETE = 7

# Define a function to choose a health check based on its type
# def choose_health_check(type):
#     for health_check in HealthChecks:
#         if type.lower() == health_check.name.lower():
#             return health_check
#     return None  # Return None if no matching health check is found

# Define a class for managing game servers
class GameServerManager:
    def __init__(self, global_config):
        """
        Initializes a new GameServerManager object.

        Args:
        global_config (dict): A dictionary containing the global configuration for the game server.
        """
        self.global_config = global_config
        """
        Event Subscriptions. These are used to call other parts of the code in an event-driven approach within async functions.
        """
        self.event_bus = ManagerEventBus()
        self.event_bus.subscribe('handle_replay_request', self.handle_replay_request)
        self.event_bus.subscribe('authenticate_to_chat_svr', self.authenticate_and_handle_chat_server)
        self.event_bus.subscribe('start_game_servers', self.start_game_servers)
        self.event_bus.subscribe('enable_game_server', self.enable_game_server)
        self.event_bus.subscribe('disable_game_server', self.disable_game_server)
        self.event_bus.subscribe('cmd_message_server', self.cmd_message_server)
        self.event_bus.subscribe('cmd_shutdown_server', self.cmd_shutdown_server)
        self.event_bus.subscribe('cmd_wake_server', self.cmd_wake_server)
        self.event_bus.subscribe('cmd_sleep_server', self.cmd_sleep_server)
        self.tasks = {
            'game_servers':'',
            'cli_handler':'',
            'health_checks':'',
            'autoping_listener':'',
            'gameserver_listener':'',
            'authentication_handler':'',
            'gameserver_startup':''
        }
        #self.event_bus.subscribe('reset')

        # Initialize dictionaries to store game servers and client connections
        self.server_start_semaphore = asyncio.Semaphore(self.global_config['hon_data']['svr_max_start_at_once'])  # 2 max servers starting at once
        self.game_servers = {}
        self.client_connections = {}

        # Initialize a Commands object for sending commands to game servers
        self.commands = Commands(self.game_servers, self.client_connections, self.global_config, self.event_bus)
        # Create game server instances
        LOGGER.info(f"Manager running, starting {self.global_config['hon_data']['svr_total']} servers. Staggered start ({self.global_config['hon_data']['svr_max_start_at_once']} at a time)")
        self.create_all_game_servers()
        
        self.tasks.update({'cli_handler':asyncio.create_task(self.commands.handle_input())})

        # Start running health checks
        self.health_check_manager = HealthCheckManager(self.game_servers, self.event_bus)
        self.tasks.update({'healthchecks':asyncio.create_task(self.health_check_manager.run_health_checks())})
    
    async def cmd_shutdown_server(self, game_server=None, force=False, delay=0):
        try:
            if game_server is None: return
            client_connection = self.client_connections.get(game_server.port, None)
            await asyncio.sleep(delay)
            if client_connection:
                if force:
                    #await game_server.stop_server_network(client_connection, (COMMAND_LEN_BYTES, SHUTDOWN_BYTES), nice=False)
                    client_connection.writer.write(COMMAND_LEN_BYTES)
                    client_connection.writer.write(SHUTDOWN_BYTES)
                    await client_connection.writer.drain()
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. FORCED.")
                else:
                    self.tasks.update({
                        'game_servers': {
                            game_server.port : { 'scheduled_shutdown' : asyncio.create_task(game_server.schedule_shutdown_server(client_connection, (COMMAND_LEN_BYTES, SHUTDOWN_BYTES)))}
                        }
                    })
                    await asyncio.sleep(0)  # allow the scheduled task to be executed
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
            else:
                # this server hasn't connected to the manager yet
                await game_server.stop_server_exe()
                game_server.reset_game_state()
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, game_server):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if not client_connection: return
            
            client_connection.writer.write(COMMAND_LEN_BYTES)
            client_connection.writer.write(WAKE_BYTES)
            await client_connection.writer.drain()
            
            LOGGER.info(f"Command - Wake command sent to GameServer #{game_server.id}.")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, game_server):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if not client_connection: return
            
            client_connection.writer.write(COMMAND_LEN_BYTES)
            client_connection.writer.write(SLEEP_BYTES)
            await client_connection.writer.drain()
            
            LOGGER.info(f"Command - Sleep command sent to GameServer #{game_server.id}.")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_message_server(self, game_server, message):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if client_connection is None:
                return

            if isinstance(message, list): message = (' ').join(message)
            message_bytes = b'$' + message.encode('ascii') + b'\x00'
            length = len(message_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')

            client_connection.writer.write(length_bytes)
            client_connection.writer.write(message_bytes)
            await client_connection.writer.drain()
            LOGGER.info(f"Command - Message command sent to GameServer #{game_server.id}.")
        except Exception:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    def start_autoping_listener_task(self, port):
        # Create an AutoPing Responder to handle ping requests from master server
        autoping_responder = AutoPingListener(
            port,
            server_name=self.global_config['hon_data']['svr_name'],
            #   TODO: Get the real version number
            game_version=self.global_config['hon_data']['svr_version'])
        task = asyncio.create_task(autoping_responder.start_listener())
        self.tasks.update({'autoping_listener':task})
        return task

    def start_game_server_listener_task(self,*args):
        task = asyncio.create_task(self.start_game_server_listener(*args))
        self.tasks.update({'gameserver_listener':task})
        return task

    def start_api_server(self):
        """legacy"""
        task = asyncio.create_task(start_api_server(self.global_config))
        self.tasks.update({'api_server':task})
        return task

    async def start_game_server_listener(self, host, game_server_to_mgr_port):
        """
        Starts a listener for incoming client connections on the specified host and port

        Args:
            host (str): the host to listen on
            game_server_to_mgr_port (int): the port to listen on

        Returns:
            None
        """

        # Start the listener for incoming client connections
        self.game_server_lsnr = await asyncio.start_server(
            lambda *args, **kwargs: handle_clients(*args, **kwargs, game_server_manager=self),
            host, game_server_to_mgr_port
        )
        LOGGER.info(f"[*] HoNfigurator Manager - Listening on {host}:{game_server_to_mgr_port} (LOCAL)")

        await stop_event.wait()

        # Close all client connections
        for connection in list(self.client_connections.values()):
            await connection.close()

        # Close the server
        self.game_server_lsnr.close()
        await self.game_server_lsnr.wait_closed()

        LOGGER.info("Server stopped.")

    def create_handle_connections_task(self, *args):
        task = asyncio.create_task(self.manage_upstream_connections(*args))
        self.tasks.update({'authentication_handler':task})
        return task

    async def manage_upstream_connections(self, udp_ping_responder_port, retry=30):
        """
        Authenticate the game server with the master server and connect to the chat server.

        This function sends a request to the master server to authenticate the game server, and then
        connects to the chat server and authenticates the game server with the chat server. It also starts
        handling packets from the chat server.

        Args:
            udp_ping_responder_port (int): The port to use for the UDP ping responder.

        Returns:
            None
        """
        while not stop_event.is_set():
            try:
                # Send requests to the master server
                parsed_mserver_auth_response = await self.send_auth_request_to_masterserver()

                # Connect to the chat server and authenticate
                await self.authenticate_and_handle_chat_server(parsed_mserver_auth_response, udp_ping_responder_port)

            except (AuthenticationError, ConnectionResetError) as e:
                LOGGER.error(f"{e.__class__.__name__} occurred. Retrying in {retry} seconds...")
                await asyncio.sleep(retry)  # Replace x with the desired number of seconds

    async def send_auth_request_to_masterserver(self):
        """
        Send a request to the master server to authenticate the game server.

        This function sends a request to the master server to authenticate the game server using the
        replay_auth method. If the authentication is successful, it returns the parsed response.

        Returns:
            dict: A dictionary containing the parsed response from the master server.

        Raises:
            AuthenticationError: If the authentication fails.
        """
        # Initialize MasterServerHandler and send requests
        self.master_server_handler = MasterServerHandler(master_server="api.kongor.online", version=self.global_config['hon_data']['svr_version'], was="was-crIac6LASwoafrl8FrOa", event_bus=self.event_bus)
        mserver_auth_response = await self.master_server_handler.send_replay_auth(f"{self.global_config['hon_data']['svr_login']}:", hashlib.md5(self.global_config['hon_data']['svr_password'].encode()).hexdigest())
        if mserver_auth_response[1] != 200:
            LOGGER.error("Authentication to MasterServer failed.")
            raise AuthenticationError(f"[{mserver_auth_response[1]}] Authentication error")
        LOGGER.info("Authenticated to MasterServer.")
        parsed_mserver_auth_response = phpserialize.loads(mserver_auth_response[0].encode('utf-8'))
        parsed_mserver_auth_response = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_mserver_auth_response.items()}

        return parsed_mserver_auth_response

    async def authenticate_and_handle_chat_server(self, parsed_mserver_auth_response, udp_ping_responder_port):
        # Create a new ChatServerHandler instance and connect to the chat server
        chat_server_handler = ChatServerHandler(
            parsed_mserver_auth_response["chat_address"],
            parsed_mserver_auth_response["chat_port"],
            parsed_mserver_auth_response["session"],
            parsed_mserver_auth_response["server_id"],
            username=self.global_config['hon_data']['svr_login'],
            version=self.global_config['hon_data']['svr_version'],
            region=self.global_config['hon_data']['svr_location'],
            server_name=self.global_config['hon_data']['svr_name'],
            ip_addr=self.global_config['hon_data']['svr_ip'],
            udp_ping_responder_port=udp_ping_responder_port,
            event_bus=self.event_bus
        )

        # connect and authenticate to chatserver
        chat_auth_response = await chat_server_handler.connect()

        if not chat_auth_response:
            raise AuthenticationError(f"[{chat_auth_response[1]}] Authentication error")

        LOGGER.info("Authenticated to ChatServer.")

        # Start handling packets from the chat server
        await chat_server_handler.handle_packets()

    def create_all_game_servers(self):
        for id in range (1,self.global_config['hon_data']['svr_total']+1):
            port = self.global_config['hon_data']['svr_starting_gamePort'] + id
            self.create_game_server(port)

    def create_game_server(self, game_server_port):
        """
        Creates a new game server instance and adds it to the game server dictionary

        Args:
            id (int): the ID of the new game server
            game_server_port (int): the port of the new game server

        Returns:
            None
        """
        id = game_server_port - self.global_config['hon_data']['svr_starting_gamePort']
        game_server = GameServer(id, game_server_port, self.global_config, self.remove_game_server, self.event_bus)
        self.game_servers[game_server_port] = game_server
        return game_server

    def find_next_available_ports(self):
        """
        Finds the next available port for creating a new game server

        Returns:
            int or None: the next available port, or None if no ports are available
        """
        starting_game_port = self.global_config['hon_data']['svr_starting_gamePort']
        total_allowed_servers = self.global_config['hon_data']['svr_total']

        for i in range(total_allowed_servers):
            game_port = starting_game_port + i

            if game_port not in self.game_servers:
                return game_port

        return None

    def create_dynamic_game_server(self):
        """
        Creates a new game server instance with the next available port

        Returns:
            None
        """
        game_port = self.find_next_available_ports()

        if game_port is not None:
            self.create_game_server(game_port)
            LOGGER.info(f"Game server created at game_port: {game_port}")
        else:
            LOGGER.warn("No available ports for creating a new game server.")

    def remove_game_server(self, game_server):
        """
        Removes a game server instance with the specified port from the game server dictionary

        Args:
            port (int): the port of the game server to remove

        Returns:
            None
        """
        for key, value in self.game_servers.items():
            if value == game_server:
                game_server.cancel_tasks()
                del self.game_servers[key]
                return True
        return False

    def get_game_server_by_id(self, id):
        """
        Returns the game server instance with the specified ID

        Args:
            id (int): the ID of the game server to get

        Returns:
            GameServer or None: the game server instance, or None if no game server with the specified ID exists
        """
        return self.game_servers.get(id)

    def get_game_server_by_port(self, game_server_port):
        """
        Returns the game server instance with the specified port

        Args:
            game_server_port (int): the port of the game server to get

        Returns:
            GameServer or None: the game server instance, or None if no game server with the specified port exists
        """
        return self.game_servers.get(game_server_port, None)

    async def add_client_connection(self,client_connection, port):
        """
        Adds a client connection to the client connection dictionary with the specified port as the key

        Args:
            client_connection (ClientConnection): the client connection instance to add
            port (int): the port associated with the client connection

        Returns:
            bool: True if the client connection was added successfully, False otherwise
        """
        if port not in self.client_connections:
            self.client_connections[port] = client_connection
            self.game_servers[port].status_received.set()
            # indicate that the sub commands should be regenerated since the list of connected servers has changed.
            await self.commands.initialise_commands()
            self.commands.subcommands_changed.set()
            return True
        else:
            #TODO: raise error or happy with logger?
            LOGGER.error(f"A connection is already established for port {port}, this is either a dead connection, or something is very wrong.")
            return False

    async def handle_replay_request(self, match_id, extension, account_id):
        replay_file_name = f"M{match_id}.{extension}"
        replay_file_path = (self.global_config['hon_data']['hon_replays_directory'] / replay_file_name)
        file_exists = exists(replay_file_path)

        if not file_exists:
            # Send the "does not exist" packet
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.DOES_NOT_EXIST)
            return

        # Send the "exists" packet
        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.QUEUED)

        # Upload the file and send status updates as required
        file_size = os.path.getsize(replay_file_path)

        upload_details = await self.master_server_handler.get_replay_upload_info(match_id, extension, self.global_config['hon_data']['svr_login'], file_size)

        if upload_details is None or upload_details[1] != 200:
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            return

        upload_details_parsed = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in upload_details[0].items()}

        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOADING)
        upload_result = await self.master_server_handler.upload_replay_file(replay_file_path, replay_file_name, upload_details_parsed['TargetURL'])
        if upload_result[1] not in [204,200]:
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            return
        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOAD_COMPLETE)


    async def remove_client_connection(self,client_connection):
        """
        Removes a client connection from the client connection dictionary with the specified port as the key

        Args:
            client_connection (ClientConnection): the client connection instance to remove
            port (int): the port associated with the client connection

        Returns:
            None
        """
        for key, value in self.client_connections.items():
            if value == client_connection:
                del self.client_connections[key]
                self.game_servers[key].reset_game_state()
                # indicate that the sub commands should be regenerated since the list of connected servers has changed.
                await self.commands.initialise_commands()
                self.commands.subcommands_changed.set()
                return True
        return False

    def start_game_servers_task(self, *args, timeout=120):
        task = asyncio.create_task(self.start_game_servers(*args))
        self.tasks.update({'gameserver_startup':task})
        return task

    async def start_game_servers(self, game_server, timeout=120):
        """
        Start all game servers.

        This function starts all the game servers that were created by the GameServerManager. It
        does this by calling the start_server method of each game server object.

        Game servers are started using a "semaphore", to stagger their start to groups and not all at once.
        The timeout value may be reached, for slow servers, it may need to be adjusted in the config file if required.

        This function does not return anything, but can log errors or other information.
        """
        async def start_game_server_with_semaphore(game_server, timeout):
            async with self.server_start_semaphore:
                started = await game_server.start_server(timeout=timeout)
                if not started:
                    LOGGER.error(f"GameServer #{game_server.id} with port {game_server.port} failed to start.")

        if game_server == "all":
            start_tasks = []
            monitor_tasks = []
            # Start all game servers using the semaphore
            for game_server in self.game_servers.values():
                already_running = await game_server.get_running_server()
                if already_running:
                    LOGGER.info(f"GameServer #{game_server.id} with port {game_server.port} already running.")
                else:
                    start_tasks.append(start_game_server_with_semaphore(game_server, timeout))
            await asyncio.gather(*start_tasks, *monitor_tasks)
        else:
            await start_game_server_with_semaphore(game_server, timeout)

    async def disable_game_server(self, game_server):
        game_server.disable_server()
    
    async def enable_game_server(self, game_server):
        game_server.enable_server()

    def start_hon_proxy():
        pass

    def check_hon_proxy_running():
        pass

    def create_hon_proxy_config():
        pass

class HealthCheckManager:
    def __init__(self, game_servers, event_bus):
        self.game_servers = game_servers
        self.event_bus = event_bus

    async def public_ip_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the public IP health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.public_ip_healthcheck)
                pass
            await asyncio.sleep(30)

    async def general_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the general health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.general_healthcheck)
                pass
            await asyncio.sleep(60)

    async def lag_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the lag health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.lag_healthcheck)
                pass
            await asyncio.sleep(120)

    async def run_health_checks(self):
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            [self.public_ip_healthcheck(), self.general_healthcheck(), self.lag_healthcheck(), stop_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
