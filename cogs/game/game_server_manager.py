# Import required modules
import phpserialize
import traceback
import asyncio
import hashlib
import os.path
import subprocess
import sys
from datetime import datetime, timedelta
import inspect
from cogs.misc.exceptions import HoNAuthenticationError, HoNServerError
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
        self.update()
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
        self.event_bus.subscribe('resubmit_match_stats_to_masterserver', self.resubmit_match_stats_to_masterserver)
        self.event_bus.subscribe('update_server_start_semaphore', self.update_server_start_semaphore)
        self.tasks = {
            'cli_handler':None,
            'health_checks':None,
            'autoping_listener':None,
            'gameserver_listener':None,
            'authentication_handler':None,
            'gameserver_startup':None,
            'task_cleanup': None
        }
        self.schedule_task(self.cleanup_tasks_every_30_minutes(), 'task_cleanup')
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
        # Initialise the autoping listener object
        self.auto_ping_listener = AutoPingListener(self.global_config, self.global_config['hon_data']['autoping_responder_port'])
        # Create game server instances
        LOGGER.info(f"Manager running, starting {self.global_config['hon_data']['svr_total']} servers. Staggered start ({self.global_config['hon_data']['svr_max_start_at_once']} at a time)")
        self.create_all_game_servers()

        coro = self.commands.handle_input()
        self.schedule_task(coro, 'cli_handler')

        # Start running health checks

        # Initialize MasterServerHandler and send requests
        self.master_server_handler = MasterServerHandler(master_server=self.global_config['hon_data']['svr_masterServer'], version=self.global_config['hon_data']['svr_version'], was=f'{self.global_config["hon_data"]["architecture"]}', event_bus=self.event_bus)
        self.health_check_manager = HealthCheckManager(self.game_servers, self.event_bus, self.check_upstream_patch, self.global_config)

        coro = self.health_check_manager.run_health_checks()
        self.schedule_task(coro, 'health_checks')
    
    def cleanup_tasks(self, tasks_dict, current_time):
        for task_name, task in list(tasks_dict.items()):  # Use list() to avoid "dictionary changed size during iteration" error
            if task is None:
                continue
            
            if not isinstance(task, asyncio.Task):
                LOGGER.error(f"Item '{task_name}' in tasks is not a Task object.")
                return

            if task.done() and task.exception() is None and task.end_time + timedelta(minutes=30) < current_time:
                del tasks_dict[task_name]
                
    async def cleanup_tasks_every_30_minutes(self):
        while True:
            current_time = datetime.now()
            # Iterate over all game servers and the manager
            for game_server in self.game_servers.values():
                self.cleanup_tasks(game_server.tasks, current_time)
            self.cleanup_tasks(self.tasks, current_time)
            await asyncio.sleep(30 * 60)  # Sleep for 30 minutes
    
    def schedule_task(self, coro, name, override = False):
        existing_task = self.tasks.get(name)  # Get existing task if any

        if existing_task is not None:
            if not isinstance(existing_task, asyncio.Task):
                LOGGER.error(f"Item '{name}' in tasks is not a Task object.")
                # Choose one of the following lines, depending on your requirements:
                # raise ValueError(f"Item '{name}' in tasks is not a Task object.")  # Option 1: raise an error
                existing_task = None  # Option 2: ignore the non-Task item and overwrite it later

        if existing_task:
            if existing_task.done():
                # If the task has finished, retrieve any possible exception to avoid 'unretrieved exception' warnings
                exception = existing_task.exception()
                if exception:
                    LOGGER.error(f"The previous task '{name}' raised an exception: {exception}. We are scheduling a new one.")
            else:
                if not override:
                    # Task is still running
                    LOGGER.warning(f"Task '{name}' is still running, new task not scheduled.")
                    return existing_task  # Return existing task
                

        # Create and register the new task
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: setattr(t, 'end_time', datetime.now()))
        self.tasks[name] = task
        return task
                    
    async def cmd_shutdown_server(self, game_server=None, force=False, delay=0, delete=False, disable=True):
        try:
            if game_server is None: return False
            client_connection = self.client_connections.get(game_server.port, None)
            await asyncio.sleep(delay)
            if client_connection:
                if force:
                    client_connection.writer.write(COMMAND_LEN_BYTES)
                    client_connection.writer.write(SHUTDOWN_BYTES)
                    await client_connection.writer.drain()
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. FORCED.")
                    return True
                else:
                    game_server.schedule_task(game_server.schedule_shutdown_server(client_connection, (COMMAND_LEN_BYTES, SHUTDOWN_BYTES), delete=delete, disable=disable),'scheduled_shutdown')
                    await asyncio.sleep(0)  # allow the scheduled task to be executed
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
                    return True
            else:
                # this server hasn't connected to the manager yet
                await game_server.stop_server_exe(disable=disable)
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

        local_svr_version = MISC.get_svr_version(self.global_config['hon_data']['hon_executable_path'])

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

    async def start_autoping_listener(self):
        LOGGER.debug("Starting AutoPingListener...")
        await self.auto_ping_listener.start_listener()

    async def start_api_server(self):
        await start_api_server(self.global_config, self.game_servers, self.tasks, self.event_bus, port=self.global_config['hon_data']['svr_api_port'])
    

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
        MISC.update_github_repository()
        MISC.save_last_working_branch()

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

            except (HoNAuthenticationError, ConnectionResetError ) as e:
                LOGGER.error(f"{e.__class__.__name__} occurred. Retrying in {retry} seconds...")
                await asyncio.sleep(retry)  # Replace x with the desired number of seconds
            except Exception as e:
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
            HoNAuthenticationError: If the authentication fails.
        """
        mserver_auth_response = await self.master_server_handler.send_replay_auth(f"{self.global_config['hon_data']['svr_login']}:", hashlib.md5(self.global_config['hon_data']['svr_password'].encode()).hexdigest())
        if mserver_auth_response[1] != 200:
            LOGGER.error(f"[{mserver_auth_response[1]}] Authentication to MasterServer failed. {mserver_auth_response[0]}")
            raise HoNAuthenticationError(f"[{mserver_auth_response[1]}] Authentication error. {mserver_auth_response[0]}")
        LOGGER.info("Authenticated to MasterServer.")
        parsed_mserver_auth_response = phpserialize.loads(mserver_auth_response[0].encode('utf-8'))
        parsed_mserver_auth_response = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_mserver_auth_response.items()}
        self.master_server_handler.set_server_id(parsed_mserver_auth_response['server_id'])
        self.master_server_handler.set_cookie(parsed_mserver_auth_response['session'])

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
            raise HoNAuthenticationError(f"[{chat_auth_response[1]}] Authentication error")

        LOGGER.info("Authenticated to ChatServer.")

        # Start handling packets from the chat server
        await chat_server_handler.handle_packets()

    async def resubmit_match_stats_to_masterserver(self, match_id, file_path):
        mserver_stats_response = await self.master_server_handler.send_stats_file(f"{self.global_config['hon_data']['svr_login']}:", hashlib.md5(self.global_config['hon_data']['svr_password'].encode()).hexdigest(), match_id, file_path)
        if mserver_stats_response[1] != 200 or mserver_stats_response[0] == '':
            # .stats submission will not work until KONGOR implements accepting .stats from the custom written manager.
            # TODO: Update below to .error once upstream is configured to accept our stats.
            LOGGER.debug(f"[{mserver_stats_response[1]}] Stats submission failed. Response: {mserver_stats_response[0]}")
            return
        parsed_mserver_stats_response = phpserialize.loads(mserver_stats_response[0].encode('utf-8'))
        parsed_mserver_stats_response = {key.decode() if isinstance(key, bytes) else key: (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_mserver_stats_response.items()}

        return

    def create_all_game_servers(self):
        for id in range (1,self.global_config['hon_data']['svr_total']+1):
            port = self.global_config['hon_data']['svr_starting_gamePort'] + id - 1
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
        id = game_server_port - self.global_config['hon_data']['svr_starting_gamePort'] + 1
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
        total_allowed_servers = MISC.get_total_allowed_servers(self.global_config['hon_data']['svr_total_per_core'])

        for i in range(total_allowed_servers):
            game_port = starting_game_port + i

            if game_port not in self.game_servers:
                return game_port

        return None

    async def balance_game_server_count(self, to_add=0, to_remove=0):
        """
        Ensures that the maximum number of game servers are running by creating new game servers
        and removing existing game servers as needed.

        Returns:
            None
        """
        max_servers = self.global_config['hon_data']['svr_total']
        if to_add == "all":
            max_servers = MISC.get_total_allowed_servers(self.global_config['hon_data']['svr_total_per_core'])
        elif to_add > 0:
            max_servers += to_add

        if to_remove == "all":
            max_servers = 0
        elif to_remove > 0:
            max_servers -= to_remove

        if max_servers < 0: max_servers = 0
        self.global_config['hon_data']['svr_total'] = max_servers

        self.setup.validate_hon_data(self.global_config['hon_data'])

        idle_servers = [game_server for game_server in self.game_servers.values() if game_server.get_dict_value('status') != 3]
        occupied_servers = [game_server for game_server in self.game_servers.values() if game_server.get_dict_value('status') == 3]
        total_num_servers = len(occupied_servers) + len(idle_servers)
        num_servers_to_remove = max(total_num_servers - max_servers, 0)
        num_servers_to_create = max(max_servers - total_num_servers, 0)

        if num_servers_to_create > 0:
            start_servers = []
            for i in range(num_servers_to_create):
                game_port = self.find_next_available_ports()

                if game_port is not None:
                    game_server = self.create_game_server(game_port)
                    start_servers.append(game_server)
                    LOGGER.info(f"Game server created at game_port: {game_port}")
                else:
                    LOGGER.warn("No available ports for creating a new game server.")
            coro = self.start_game_servers(start_servers)
            self.schedule_task(coro, 'gameserver_startup', override = True)
        
        async def remove_servers(servers, server_type):
            servers_removed = 0
            servers_to_remove = []
            for game_server in servers:
                await self.cmd_shutdown_server(game_server, delete=True)
                if not game_server.delete_me:
                    servers_to_remove.append(game_server.port)
                    servers_removed += 1
                    if servers_removed >= num_servers_to_remove:
                        break
            for port in servers_to_remove:
                if port in self.game_servers:
                    del self.game_servers[port]
            
            LOGGER.info(f"Removed {servers_removed} {server_type} game servers. {max_servers} game servers are now running.")
            return servers_removed

        if num_servers_to_remove > 0:
            removed_idle = await remove_servers(idle_servers, 'idle')
            num_servers_to_remove -= removed_idle
            if num_servers_to_remove > 0:
                removed_occupied = await remove_servers(occupied_servers, 'occupied')
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

        start_servers = []
        for i in range(num_servers_to_create):
            game_port = self.find_next_available_ports()

            if game_port is not None:
                game_server = self.create_game_server(game_port)
                start_servers.append(game_server)
                LOGGER.info(f"Game server created at game_port: {game_port}")
            else:
                LOGGER.warn("No available ports for creating a new game server.")
        
        coro = self.start_game_servers(start_servers)
        self.schedule_task(coro, 'gameserver_startup', override = True)

    async def check_for_restart_required(self):
        for game_server in self.game_servers.values():
            if game_server.params_are_different():
                await self.cmd_shutdown_server(game_server,disable=False)
                await asyncio.sleep(0.1)
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
        replay_file_path_longterm = (Path(self.global_config['application_data']['longterm_storage']['location']) / replay_file_name)
        file_exists = Path.exists(replay_file_path)
        if not file_exists and self.global_config['application_data']['longterm_storage']['active']:
            file_exists = Path.exists(replay_file_path_longterm)

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
                LOGGER.debug(f"GameServer #{client_connection.id} removing connection.")
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
    
    def update_server_start_semaphore(self):
        max_start_at_once = self.global_config['hon_data']['svr_max_start_at_once']
        self.server_start_semaphore = asyncio.Semaphore(max_start_at_once)

    async def start_game_servers(self, game_servers, timeout=120, launch=False):
        timeout = self.global_config['hon_data']['svr_startup_timeout']
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
        if MISC.get_os_platform() == "win32" and launch and await self.check_upstream_patch():
            if not await self.initialise_patching_procedure(source="startup"):
                return False

        else:
            # Patch not required
            pass

        async def start_game_server_with_semaphore(game_server, timeout):
            game_server.game_state.update({'status':GameStatus.QUEUED.value})
            async with self.server_start_semaphore:
                # Use the schedule_task method to start the server
                task = game_server.schedule_task(game_server.start_server(timeout=timeout), 'start_server')
                try:
                    # Await the completion of the task with the specified timeout
                    await asyncio.wait_for(task, timeout)
                    LOGGER.info(f"GameServer #{game_server.id} started successfully.")
                except asyncio.TimeoutError:
                    LOGGER.error(f"GameServer #{game_server.id} failed to start within the timeout period.")
                    await self.cmd_shutdown_server(game_server)
                except HoNServerError:
                    # LOGGER.error(f"GameServer #{game_server.id} encountered a server error.")
                    await self.cmd_shutdown_server(game_server)


        start_tasks = []
        if game_servers == "all":
            game_servers = list(self.game_servers.values())
            
        for game_server in game_servers:
            already_running = await game_server.get_running_server()
            if already_running:
                LOGGER.info(f"GameServer #{game_server.id} with public ports {game_server.get_public_game_port()}/{game_server.get_public_voice_port()} already running.")
            else:
                # Start all game servers using the semaphore
                if launch and not self.global_config['hon_data']['svr_start_on_launch']:
                    LOGGER.info("Waiting for manual server start up. svr_start_on_launch setting is disabled.")
                    return
                start_tasks.append(start_game_server_with_semaphore(game_server, timeout))
        await asyncio.gather(*start_tasks)

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

            temp_manager_proc = None
            while not temp_manager_proc:
                await asyncio.sleep(1)
                temp_manager_proc = MISC.find_process_by_cmdline_keyword("-manager", proc_name = self.global_config['hon_data']['hon_executable_name'])
                wait_for_temp_manager +=1
                if wait_for_temp_manager >= max:
                    LOGGER.error(f"Patching failed as it exceeded {max} seconds waiting for patcher to open manager.")
                    return False

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
            return False
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
