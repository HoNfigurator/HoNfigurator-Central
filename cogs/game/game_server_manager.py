# Import required modules
import phpserialize
import traceback
import asyncio
import hashlib
import os.path
import subprocess
import sys
import time
import inspect
from cogs.misc.exceptions import ServerConnectionError, AuthenticationError, UnexpectedVersionError, HoNPatchError, InvalidServerBinaries
from cogs.connectors.masterserver_connector import MasterServerHandler
from cogs.connectors.chatserver_connector import ChatServerHandler
from cogs.TCP.game_packet_lsnr import handle_clients
from cogs.TCP.auto_ping_lsnr import AutoPingListener
from cogs.connectors.api_server import start_api_server
from cogs.game.game_server import GameServer
from cogs.handlers.commands import Commands
from cogs.handlers.events import stop_event, ReplayStatus, GameStatus, HealthChecks, EventBus as ManagerEventBus
from cogs.misc.logger import get_logger, get_misc, get_home
from pathlib import Path
from cogs.game.healthcheck_manager import HealthCheckManager
from enum import Enum
from os.path import exists

LOGGER = get_logger()
MISC = get_misc()
HOME_PATH = get_home()

# TCP Command definitions
COMMAND_LEN_BYTES = b'\x01\x00'
SHUTDOWN_BYTES = b'"'
SLEEP_BYTES = b' '
WAKE_BYTES = b'!'

# Define a function to choose a health check based on its type
# def choose_health_check(type):
#     for health_check in HealthChecks:
#         if type.lower() == health_check.name.lower():
#             return health_check
#     return None  # Return None if no matching health check is found

# Define a class for managing game servers
class GameServerManager:
    def __init__(self, global_config, setup):
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
        self.event_bus.subscribe('add_game_servers', self.create_dynamic_game_server)
        self.event_bus.subscribe('remove_game_servers', self.remove_dynamic_game_server)
        self.event_bus.subscribe('remove_game_server', self.remove_game_server)
        self.event_bus.subscribe('balance_game_server_count', self.balance_game_server_count)
        self.event_bus.subscribe('enable_game_server', self.enable_game_server)
        self.event_bus.subscribe('disable_game_server', self.disable_game_server)
        self.event_bus.subscribe('cmd_message_server', self.cmd_message_server)
        self.event_bus.subscribe('cmd_shutdown_server', self.cmd_shutdown_server)
        self.event_bus.subscribe('cmd_wake_server', self.cmd_wake_server)
        self.event_bus.subscribe('cmd_sleep_server', self.cmd_sleep_server)
        self.event_bus.subscribe('patch_server', self.initialise_patching_procedure)
        self.event_bus.subscribe('update', self.update)
        self.event_bus.subscribe('check_for_restart_required', self.check_for_restart_required)
        self.tasks = {
            'game_servers':'',
            'cli_handler':'',
            'health_checks':'',
            'autoping_listener':'',
            'gameserver_listener':'',
            'authentication_handler':'',
            'gameserver_startup':''
        }
        # initialise the config validator in case we need it
        self.setup = setup

        # set the current state of patching
        self.patching = False

        # preserve the current system path. We need it for a silly fix.
        self.preserved_path = os.environ["PATH"]

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

        # Initialize MasterServerHandler and send requests
        self.master_server_handler = MasterServerHandler(master_server=self.global_config['hon_data']['svr_masterServer'], version=self.global_config['hon_data']['svr_version'], was=f'{self.global_config["hon_data"]["architecture"]}', event_bus=self.event_bus)
        self.health_check_manager = HealthCheckManager(self.game_servers, self.event_bus, self.check_upstream_patch, self.global_config)
        self.tasks.update({'healthchecks':asyncio.create_task(self.health_check_manager.run_health_checks())})

    async def cmd_shutdown_server(self, game_server=None, force=False, delay=0, delete=False):
        try:
            if game_server is None: return False
            client_connection = self.client_connections.get(game_server.port, None)
            await asyncio.sleep(delay)
            if client_connection:
                if force:
                    #await game_server.stop_server_network(client_connection, (COMMAND_LEN_BYTES, SHUTDOWN_BYTES), nice=False)
                    client_connection.writer.write(COMMAND_LEN_BYTES)
                    client_connection.writer.write(SHUTDOWN_BYTES)
                    await client_connection.writer.drain()
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. FORCED.")
                    return True
                else:
                    self.tasks.update({
                        'game_servers': {
                            game_server.port : { 'scheduled_shutdown' : asyncio.create_task(game_server.schedule_shutdown_server(client_connection, (COMMAND_LEN_BYTES, SHUTDOWN_BYTES), delete=delete))}
                        }
                    })
                    await asyncio.sleep(0)  # allow the scheduled task to be executed
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
                    return True
            else:
                # this server hasn't connected to the manager yet
                await game_server.stop_server_exe()
                game_server.reset_game_state()
                return True
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

    async def check_upstream_patch(self):
        if self.patching:
            LOGGER.info("Server patching is ongoing.. Please wait.")
            return

        try:
            local_svr_version = MISC.get_svr_version(self.global_config['hon_data']['hon_executable_path'])
        except UnexpectedVersionError:
            raise InvalidServerBinaries("The version check on the hon_x64.exe failed, because it was not a supported server binary. Please ensure you have correctly followed the guide to set up the server.")

        try:
            patch_information = await self.master_server_handler.compare_upstream_patch()
            if not patch_information:
                LOGGER.error("Checking the upstream patch version failed, as the upstream services were unavailable.")
                return
            if patch_information[1] != 200:
                LOGGER.error(f"Checking the upstream patch version failed with: [{patch_information[1]}] {patch_information[0]}")
                return
            parsed_patch_information = phpserialize.loads(patch_information[0].encode('utf-8'))
            parsed_patch_information = {key.decode() if isinstance(key, bytes) else key: (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_patch_information.items()}
            self.latest_available_game_version = parsed_patch_information['latest']

            if local_svr_version != self.latest_available_game_version:
                LOGGER.info(f"A newer patch is available. Initiating server shutdown for patching.\n\tUpgrading from {local_svr_version} --> {parsed_patch_information['latest']}")
                return True

            return False

        except Exception:
            LOGGER.error(f"{traceback.format_exc()}")

    async def start_autoping_listener_task(self, port):
        LOGGER.info("Starting AutoPingListener...")
        self.auto_ping_listener = AutoPingListener(self.global_config, port)
        self.auto_ping_listener_task = asyncio.create_task(self.auto_ping_listener.start_listener())
        self.tasks.update({'autoping_listener':self.auto_ping_listener_task})
        return self.auto_ping_listener_task

    def start_game_server_listener_task(self,*args):
        task = asyncio.create_task(self.start_game_server_listener(*args))
        self.tasks.update({'gameserver_listener':task})
        return task

    async def start_api_server(self):
        task = await start_api_server(self.global_config, self.game_servers, self.event_bus)
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

        await self.master_server_handler.close_session()

        LOGGER.info("Server stopped.")

    def update(self):
        try:
            # Change the current working directory to the HOME_PATH
            os.chdir(HOME_PATH)

            # Run the git pull command
            result = subprocess.run(["git", "pull"], check=True, text=True, capture_output=True)

            # Check if the update was successful
            if "Already up to date." not in result.stdout and "Fast-forward" in result.stdout:
                LOGGER.info("Update successful. Relaunching the code...")

                # Relaunch the code
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                LOGGER.info("Already up to date. No need to relaunch.")
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"Error updating the code: {e}")

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
        starting_game_port = self.global_config['hon_data']['svr_starting_gamePort'] + 1
        total_allowed_servers = MISC.get_total_allowed_servers(self.global_config['hon_data']['svr_total_per_core'])

        for i in range(total_allowed_servers):
            game_port = starting_game_port + i

            if game_port not in self.game_servers:
                return game_port

        return None

    async def balance_game_server_count(self, add_servers=0, remove_servers=0):
        """
        Ensures that the maximum number of game servers are running by creating new game servers
        and removing existing game servers as needed.

        Returns:
            None
        """
        max_servers = self.global_config['hon_data']['svr_total']
        if add_servers == "all":
            max_servers = MISC.get_total_allowed_servers(self.global_config['hon_data']['svr_total_per_core'])
        elif add_servers > 0:
            max_servers += add_servers

        if remove_servers == "all":
            max_servers = 0
        elif remove_servers > 0:
            max_servers -= remove_servers

        if max_servers < 0: max_servers = 0
        self.global_config['hon_data']['svr_total'] = max_servers

        self.setup.validate_hon_data(self.global_config['hon_data'])

        running_servers = [game_server for game_server in self.game_servers.values() if game_server.get_dict_value('match_started') != 1]
        num_running_servers = len(running_servers)
        num_servers_to_remove = max(num_running_servers - max_servers, 0)
        num_servers_to_create = max(max_servers - num_running_servers, 0)

        if num_servers_to_create > 0:
            for i in range(num_servers_to_create):
                game_port = self.find_next_available_ports()

                if game_port is not None:
                    game_server = self.create_game_server(game_port)
                    asyncio.create_task(self.start_game_servers(game_server))
                    LOGGER.info(f"Game server created at game_port: {game_port}")
                else:
                    LOGGER.warn("No available ports for creating a new game server.")

        if num_servers_to_remove > 0:
            servers_removed = 0
            for game_server in running_servers:
                if await self.cmd_shutdown_server(game_server):
                    del self.game_servers[game_server.port]
                    servers_removed += 1
                    if servers_removed >= num_servers_to_remove:
                        break

            LOGGER.info(f"Removed {servers_removed} game servers. {max_servers} game servers are now running.")
        elif num_servers_to_remove < 0:
            LOGGER.warn("Number of running game servers is greater than the maximum number of game servers.")


    async def create_dynamic_game_server(self):
        """
        Creates new game server instances with the next available ports until the maximum number of servers is reached

        Returns:
            None
        """
        max_servers = self.global_config['hon_data']['svr_total']
        running_servers = [game_server for game_server in self.game_servers.values() if game_server.started]
        num_servers_to_create = max_servers - len(running_servers)
        if num_servers_to_create <= 0:
            return

        for i in range(num_servers_to_create):
            game_port = self.find_next_available_ports()

            if game_port is not None:
                game_server = self.create_game_server(game_port)
                asyncio.create_task(self.start_game_servers(game_server))
                LOGGER.info(f"Game server created at game_port: {game_port}")
            else:
                LOGGER.warn("No available ports for creating a new game server.")

    async def check_for_restart_required(self):
        for game_server in self.game_servers.values():
            if game_server.params_are_different():
                await self.cmd_shutdown_server(game_server)
                game_server.enable_server()

    async def remove_dynamic_game_server(self):
        max_servers = self.global_config['hon_data']['svr_total']
        running_servers = [game_server for game_server in self.game_servers.values() if game_server.get_dict_value('match_started') != 0]
        num_servers_to_remove = len(running_servers) - max_servers
        if num_servers_to_remove <= 0:
            return

        servers_removed = 0
        for game_server in running_servers:
            if await self.cmd_shutdown_server(game_server):
                del self.game_servers[game_server.port]
                servers_removed += 1
                if servers_removed >= num_servers_to_remove:
                    break

        LOGGER.info(f"Removed {servers_removed} game servers. {max_servers} game servers are now running.")

        # count = 0
        # for i in range(num):
        #     removed = False
        #     for port, game_server in self.game_servers.items():
        #         if not game_server.started:
        #             if self.remove_game_server(game_server):
        #                 LOGGER.info(f"Removed game server {port}")
        #                 count += 1
        #                 removed = True
        #                 break
        #     if not removed:
        #         LOGGER.info(f"No more running game servers found after removing {count} game servers.")
        #         break
        # LOGGER.info(f"Removed a total of {count} game servers.")

    def remove_game_server(self, game_server):
        """
        Removes a game server instance with the specified port from the game server dictionary

        Args:
            port (int): the port of the game server to remove

        Returns:
            None
        """
        for key, value in self.game_servers.items():
            if value == game_server and not game_server.started:
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
            game_server = self.game_servers.get(port, None)
            # this is in case game server doesn't exist (config change maybe)
            if game_server:
                game_server.status_received.set()
            # TODO
            # Create game server object here?
            # The instance of this happening, is for example, someone is running 10 servers. They modify the config on the fly to be 5 servers. Servers 5-10 are scheduled for shutdown, but game server objects have been destroyed.
            # since the game server isn't actually off yet, it will keep creating a connection.

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
        replay_file_path = (Path(self.global_config['hon_data']['hon_replays_directory']) / replay_file_name)
        file_exists = Path.exists(replay_file_path)

        LOGGER.debug(f"Received replay upload request.\n\tFile Name: {replay_file_name}\n\tAccount ID (requestor): {account_id}")

        if not file_exists:
            # Send the "does not exist" packet
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.DOES_NOT_EXIST)
            LOGGER.warn(f"Replay file {replay_file_path} does not exist.")
            return

        # Send the "exists" packet
        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.QUEUED)
        LOGGER.debug(f"Replay file exists. Obtaining upload location information.")

        # Upload the file and send status updates as required
        file_size = os.path.getsize(replay_file_path)

        upload_details = await self.master_server_handler.get_replay_upload_info(match_id, extension, self.global_config['hon_data']['svr_login'], file_size)


        if upload_details is None or upload_details[1] != 200:
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            LOGGER.error(f"Failed to obtain upload location information. HTTP Response ({upload_details[1]}):\n\t{upload_details[0]}")
            return

        upload_details_parsed = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in upload_details[0].items()}
        LOGGER.debug(f"Uploading replay to {upload_details_parsed['TargetURL']}")

        LOGGER.debug(f"Uploading replay to {upload_details_parsed['TargetURL']}")

        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOADING)
        try:
            upload_result = await self.master_server_handler.upload_replay_file(replay_file_path, replay_file_name, upload_details_parsed['TargetURL'])
        except Exception:
            LOGGER.exception(f"Undefined Exception: {traceback.format_exc()}")

        if upload_result[1] not in [204,200]:
            await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            LOGGER.error(f"Replay upload failed! HTTP Upload Response ({upload_result[1]})\n\t{upload_result[0]}")
            return
        await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOAD_COMPLETE)
        LOGGER.debug("Replay upload completed successfully.")


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
                game_server = self.game_servers.get(key, None)
                #   This is in case game server doesn't exist intentionally (maybe config changed)
                if game_server:
                    game_server.reset_game_state()
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
        if MISC.get_os_platform() == "win32":
            # this is an atrocious fix until I find a better solution.
            # on some systems, the compiled honfigurator.exe file, which is just launcher.py from cogs.misc causes issues for the opened hon_x64.exe. The exe is unable to locate one of the game dll resources.
            # I wasted a lot of time trying to troubleshoot it, launching main.py directly works fine. This is my solution until a better one comes around. It's set within the scope of the script, and doesn't modify the systems environment.
            path_list = os.environ["PATH"].split(os.pathsep)
            if self.global_config['hon_data']['hon_install_directory'] not in path_list:
                os.environ["PATH"] = f"{self.global_config['hon_data']['hon_install_directory'] / 'game'}{os.pathsep}{self.preserved_path}"
        if MISC.get_os_platform() == "win32" and await self.check_upstream_patch():
            if await self.initialise_patching_procedure(source="startup"):
                # patching was successful. Continue starting servers.
                pass
            else:
                return False

        else:
            # Patch not required
            pass

        async def start_game_server_with_semaphore(game_server, timeout):
            game_server.game_state.update({'status':GameStatus.QUEUED.value})
            async with self.server_start_semaphore:
                started = await game_server.start_server(timeout=timeout)
                if not started:
                    LOGGER.error(f"GameServer #{game_server.id} with port {game_server.port} failed to start.")
                    await self.cmd_shutdown_server(game_server)

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

    async def initialise_patching_procedure(self, timeout=300, source=None):
        if self.patching:
            LOGGER.warn("Patching is already in progress.")
            return

        for game_server in self.game_servers.values():
            if game_server.started and game_server.enabled:
                await self.cmd_message_server(game_server, "!! ANNOUNCEMENT !! This server will shutdown after the current match for patching.")
            await self.cmd_shutdown_server(game_server)

        if MISC.get_proc(self.global_config['hon_data']['hon_executable_path']):
            return

        # begin patch
        patcher_exe = self.global_config['hon_data']['hon_install_directory'] / "hon_update_x64.exe"
        # subprocess.run([patcher_exe, "-norun"])
        try:
            subprocess.run([patcher_exe, "-manager"], timeout=timeout)
            # the hon_update_x64.exe will launch the default k2 server manager, indicating patching is complete. We don't need it so close it.
            wait_for_temp_manager = 0
            max = 5
            while not MISC.find_process_by_cmdline_keyword("-manager"):
                await asyncio.sleep(1)
                wait_for_temp_manager +=1
                if wait_for_temp_manager >= max:
                    LOGGER.error(f"Patching failed as it exceeded {max} seconds waiting for patcher to open manager.")
                    return False

            temp_manager_proc = MISC.find_process_by_cmdline_keyword("-manager")
            temp_manager_proc.terminate()

            svr_version = MISC.get_svr_version(self.global_config['hon_data']['hon_executable_path'])
            if MISC.get_svr_version(self.global_config['hon_data']['hon_executable_path']) != self.latest_available_game_version:
                LOGGER.error(f"Server patching failed. Current version: {svr_version}")
                return False

            LOGGER.info("Patching successful!")
            if source == "startup":
                return True
            elif source == "healthcheck":
                await self.start_game_servers("all")

        except subprocess.TimeoutExpired:
            LOGGER.warn(f"Patching failed as it exceeded {timeout} seconds to patch resources.")
            return False
        except Exception:
            LOGGER.error(f"An unexpected error occured while patching: {traceback.format_exc()}")
        finally:
            # patching is done. Whether it failed or otherwise.
            self.patching = False

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
