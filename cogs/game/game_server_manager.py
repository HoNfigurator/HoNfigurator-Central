# Import required modules
import phpserialize
import traceback
import asyncio
import hashlib
from cogs.misc.exceptions import ServerConnectionError, AuthenticationError
from cogs.connectors.masterserver_connector import MasterServerHandler
from cogs.connectors.chatserver_connector import ChatServerHandler
from cogs.TCP.listeners.packet_handler import handle_clients
from cogs.TCP.listeners.auto_ping import AutoPingListener
from cogs.game.game_server import GameServer
from cogs.handlers.commands import Commands
from cogs.misc.logging import get_logger
from enum import Enum

LOGGER = get_logger()

# Define an Enum class for health checks
class HealthChecks(Enum):
    public_ip_healthcheck = 1
    general_healthcheck = 2
    lag_healthcheck = 3

# Define a function to choose a health check based on its type
def choose_health_check(type):
    for health_check in HealthChecks:
        if type.lower() == health_check.name.lower():
            return health_check
    return None  # Return None if no matching health check is found

# Define a class for managing game servers
class GameServerManager:
    def __init__(self, global_config):
        """
        Initializes a new GameServerManager object.

        Args:
        global_config (dict): A dictionary containing the global configuration for the game server.
        """
        # Store the global configuration
        self.global_config = global_config
        # Initialize dictionaries to store game servers and client connections
        self.server_start_semaphore = asyncio.Semaphore(self.global_config['hon_data']['svr_max_start_at_once'])  # 2 max servers starting at once
        self.game_servers = {}
        self.client_connections = {}
        # Initialize a Commands object for sending commands to game servers
        self.commands = Commands(self.game_servers, self.client_connections, self.global_config, self.send_svr_command)
        # Create an event and task for handling input commands
        stop_event = asyncio.Event()
        asyncio.create_task(self.commands.handle_input(stop_event))
        # Create game server instances
        LOGGER.info(f"Manager running, starting {self.global_config['hon_data']['svr_total']} servers. Staggered start ({self.global_config['hon_data']['svr_max_start_at_once']} at a time)")
        for id in range (1,self.global_config['hon_data']['svr_total']+1):
            port = global_config['hon_data']['svr_starting_gamePort'] + id
            self.create_game_server(port)
        # Start running health checks
        asyncio.create_task(self.run_health_checks())

    async def send_svr_command(self, command, game_server_port, command_data):
        """
        Sends a server command to the game server with the specified port

        Args:
            game_server_port (int): the port of the game server to send the command to
            command_data (bytes): the command to send, as bytes

        Returns:
            None
        """
        client_connection = self.client_connections.get(game_server_port)
        if command == "shutdown":
            game_server = self.game_servers.get(game_server_port)
            if game_server:
                await game_server.schedule_shutdown_server(client_connection,command_data)
        else:
            # Get the client connection for the specified game server port and send the command
            if client_connection:
                length_bytes, message_bytes = command_data
                client_connection.writer.write(length_bytes)
                client_connection.writer.write(message_bytes)
                await client_connection.writer.drain()
            else:
                LOGGER.warn(f"No client connection found for port {game_server_port}")

    async def start_autoping_listener(self, port):
        # Create an AutoPing Responder to handle ping requests from master server
        autoping_responder = AutoPingListener(
            port,
            server_name=self.global_config['hon_data']['svr_name'],
            #   TODO: Get the real version number
            game_version="4.10.6.0")
        asyncio.create_task(autoping_responder.start_listener())

    async def start_game_server_listener(self,host,game_server_to_mgr_port):
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
        # Create a stop event to signal when the server should stop
        stop_event = asyncio.Event()

        try:
            # Wait for either the stop event to be set or for the client task to complete
            done, pending = await asyncio.wait(
                [stop_event.wait()],
                # input_task,
                return_when=asyncio.FIRST_COMPLETED
            )
        except KeyboardInterrupt:
            LOGGER.warn("Keyboard Interrupt: Server shutting down...")
            stop_event.set()

        if pending is not None:
            for task in pending:
                # Cancel any remaining pending tasks here
                task.cancel()

        # Close all client connections
        for connection in self.client_connections.values():
            await connection.close()

        # Close the server
        self.game_server_lsnr.close()
        await self.game_server_lsnr.wait_closed()

        LOGGER.info("Server stopped.")

    async def authenticate_to_masterserver(self, udp_ping_responder_port):
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
        # Send requests to the master server
        parsed_mserver_auth_response = await self.send_requests_to_masterserver()

        # Connect to the chat server and authenticate
        await self.authenticate_and_handle_chat_server(parsed_mserver_auth_response, udp_ping_responder_port)

    async def send_requests_to_masterserver(self):
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
        master_server_handler = MasterServerHandler(master_server="api.kongor.online", version="4.10.6.0")
        mserver_auth_response = await master_server_handler.send_replay_auth(f"{self.global_config['hon_data']['svr_login']}:", hashlib.md5(self.global_config['hon_data']['svr_password'].encode()).hexdigest())
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
            udp_ping_responder_port=udp_ping_responder_port
        )

        # connect and authenticate to chatserver
        chat_auth_response = await chat_server_handler.connect()

        if not chat_auth_response:
            LOGGER.error("Authentication to ChatServer failed.")
            raise AuthenticationError(f"[{chat_auth_response[1]}] Authentication error")
        LOGGER.info("Authenticated to ChatServer.")
        # Start handling packets from the chat server
        await chat_server_handler.handle_packets()

    def load_global_configuration():
        pass

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
        game_server = GameServer(id, game_server_port, self.global_config, self.remove_game_server)
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

    def add_client_connection(self,client_connection, port):
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
            return True
        else:
            #TODO: RAISE ERROR
            return False


    def remove_client_connection(self,client_connection):
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
                return True
        return False

    async def run_health_checks(self):
        """
        Perform health checks for the game servers.

        This function should be run periodically to ensure that all game servers are running
        properly. It can implement various health checks, such as checking the servers' public
        IP, general health, and lag.

        This function does not return anything, but can log errors or other information.
        """
        while True:
            await asyncio.sleep(30)
            for game_server in self.game_servers.values():
                # Perform health checks for each game server here
                pass

    async def start_game_servers(self):
        """
        Start all game servers.

        This function starts all the game servers that were created by the GameServerManager. It
        does this by calling the start_server method of each game server object.

        This function does not return anything, but can log errors or other information.
        """
        async def start_game_server_with_semaphore(game_server):
            async with self.server_start_semaphore:
                started = await game_server.start_server()
                if started:
                    LOGGER.info(f"GameServer #{game_server.id} with port {game_server.port} started successfully.")
                    # Wait for the game server to finish loading
                    while game_server.game_state._state['status'] is None:
                        await asyncio.sleep(1)
                else:
                    LOGGER.info(f"GameServer #{game_server.id} with port {game_server.port} failed to start.")

        # Start the game servers using the semaphore
        start_tasks = [start_game_server_with_semaphore(game_server) for game_server in self.game_servers.values()]
        await asyncio.gather(*start_tasks)
