# Import required modules
import phpserialize
import traceback
import asyncio
import hashlib
import os.path
import subprocess
import urllib
from datetime import datetime, timedelta
import inspect
import tempfile
import shutil
from cogs.misc.exceptions import HoNAuthenticationError, HoNServerError
from cogs.connectors.masterserver_connector import MasterServerHandler
from cogs.connectors.chatserver_connector import ChatServerHandler
from cogs.TCP.game_packet_lsnr import handle_clients
from cogs.TCP.auto_ping_lsnr import AutoPingListener
from cogs.connectors.api_server import start_api_server
from cogs.game.game_server import GameServer
from cogs.game.cow_master import CowMaster
from cogs.handlers.commands import Commands
from cogs.handlers.events import stop_event, ReplayStatus, GameStatus, GameServerCommands, EventBus as ManagerEventBus
from cogs.misc.logger import get_logger, get_misc, get_home, get_filebeat_status, get_filebeat_auth_url
from pathlib import Path
from cogs.game.healthcheck_manager import HealthCheckManager
from enum import Enum
from os.path import exists
from utilities.filebeat import main as filebeat, filebeat_status

LOGGER = get_logger()
from cogs.handlers.data_handler import get_cowmaster_configuration
MISC = get_misc()
HOME_PATH = get_home()
HON_VERSION_URL = "http://gitea.kongor.online/administrator/KONGOR/raw/branch/main/patch/was-crIac6LASwoafrl8FrOa/x86_64/version.cfg"
HON_UPDATE_X64_DOWNLOAD_URL = "http://gitea.kongor.online/administrator/KONGOR/raw/branch/main/patch/was-crIac6LASwoafrl8FrOa/x86_64/hon_update_x64.zip"

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
        self.event_bus.subscribe('start_game_servers_task', self.start_game_servers_task)
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
        self.event_bus.subscribe('cmd_custom_command', self.cmd_custom_command)
        self.event_bus.subscribe('fork_server_from_cowmaster', self.fork_server_from_cowmaster),
        # self.event_bus.subscribe('start_gameserver_from_cowmaster', self.start_gameserver_from_cowmaster)
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

        # make cowmaster, we may or may not use it
        self.use_cowmaster = False
        if self.global_config['hon_data']['man_use_cowmaster']:
            self.use_cowmaster = True
        self.cowmaster = CowMaster(self.global_config['hon_data']['svr_starting_gamePort'] - 2, self.global_config)

        # Initialize a Commands object for sending commands to game servers
        self.commands = Commands(self.game_servers, self.client_connections, self.global_config, self.event_bus, self.cowmaster)
        # Initialise the autoping listener object
        self.auto_ping_listener = AutoPingListener(self.global_config, self.global_config['hon_data']['autoping_responder_port'])
        # Create game server instances
        LOGGER.info(f"Manager running, starting {self.global_config['hon_data']['svr_total']} servers. Staggered start ({self.global_config['hon_data']['svr_max_start_at_once']} at a time)")
        self.create_all_game_servers()

        coro = self.commands.handle_input()
        self.schedule_task(coro, 'cli_handler')

        # Start running health checks

        # Initialize MasterServerHandler and send requests
        self.chat_server_handler = None
        self.master_server_handler = MasterServerHandler(master_server=self.global_config['hon_data']['svr_masterServer'], version=self.global_config['hon_data']['svr_version'], was=f'{self.global_config["hon_data"]["architecture"]}', event_bus=self.event_bus)
        self.health_check_manager = HealthCheckManager(self.game_servers, self.event_bus, self.check_upstream_patch, self.resubmit_match_stats_to_masterserver, self.global_config)

        coro = self.health_check_manager.run_health_checks()
        self.schedule_task(coro, 'health_checks')

        MISC.save_last_working_branch()

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
            for _ in range(30 * 60):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)

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
                if not existing_task.cancelled():
                    # If the task has finished and was not cancelled, retrieve any possible exception to avoid 'unretrieved exception' warnings
                    exception = existing_task.exception()
                    if exception:
                        LOGGER.error(f"The previous task '{name}' raised an exception: {exception}. We are scheduling a new one.")
                else:
                    LOGGER.info(f"The previous task '{name}' was cancelled.")
            else:
                if not override:
                    # Task is still running
                    LOGGER.debug(f"Task '{name}' is still running, new task not scheduled.")
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
                    client_connection.writer.write(GameServerCommands.COMMAND_LEN_BYTES.value)
                    client_connection.writer.write(GameServerCommands.SHUTDOWN_BYTES.value)
                    await client_connection.writer.drain()
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. FORCED.")
                    return True
                else:
                    game_server.schedule_task(game_server.schedule_shutdown_server(delete=delete, disable=disable),'scheduled_shutdown')
                    # await asyncio.sleep(0)  # allow the scheduled task to be executed
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
                    return True
            else:
                # this server hasn't connected to the manager yet
                await game_server.stop_server_exe(disable=disable, delete=delete)
                game_server.reset_game_state()
                return True
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, game_server):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if not client_connection: return

            # TODO: use client_connection.send_packet() ??
            client_connection.writer.write(GameServerCommands.COMMAND_LEN_BYTES.value)
            client_connection.writer.write(GameServerCommands.WAKE_BYTES.value)
            await client_connection.writer.drain()

            LOGGER.info(f"Command - Wake command sent to GameServer #{game_server.id}.")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, game_server):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if not client_connection: return

            # TODO: use client_connection.send_packet() ??
            client_connection.writer.write(GameServerCommands.COMMAND_LEN_BYTES.value)
            client_connection.writer.write(GameServerCommands.SLEEP_BYTES.value)
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
            message_bytes = GameServerCommands.MESSAGE_BYTES.value + message.encode('ascii') + b'\x00'
            length = len(message_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')

            # TODO: use client_connection.send_packet() ??
            client_connection.writer.write(length_bytes)
            client_connection.writer.write(message_bytes)
            await client_connection.writer.drain()
            LOGGER.info(f"Command - Message command sent to GameServer #{game_server.id}.")
        except Exception:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_custom_command(self, game_server, command, delay = 0):
        try:
            client_connection = self.client_connections.get(game_server.port, None)
            if client_connection is None:
                return
            await asyncio.sleep(delay)

            if isinstance(command, list): command = (' ').join(command)
            command_bytes = GameServerCommands.COMMAND_BYTES.value + command.encode('ascii') + b'\x00'
            length = len(command_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')

            # TODO: use client_connection.send_packet() ??
            client_connection.writer.write(length_bytes)
            client_connection.writer.write(command_bytes)
            await client_connection.writer.drain()
            LOGGER.info(f"Command - command sent to GameServer #{game_server.id}.")
        except Exception:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_cowmaster_fork(self, instance_number, port):
        try:
            client_connection = self.client_connections.get(self.cowmaster.get_port(), None)

            if client_connection is None:
                return

            command_bytes = b'\x28' + instance_number.to_bytes(1, "little") + port.to_bytes(2, "little") + b'\x00'

            #command_bytes = b'\x28\x01\x11\x27\x00'
            length = len(command_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')

            client_connection.writer.write(length_bytes)
            client_connection.writer.write(command_bytes)
            await client_connection.writer.drain()

            LOGGER.info(f"Command - command sent to CowMaster.")
        except Exception:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def fork_server_from_cowmaster(self, game_server):
        try:
            await self.cowmaster.fork_new_server(game_server)
        except Exception:
            LOGGER.error(traceback.format_exc())

    async def start_gameserver_from_cowmaster(self, num = "all"):
        try:
            starting_port = self.global_config.get("hon_data").get("svr_starting_gamePort")
            if num == "all":
                number_of_instances = self.global_config.get("hon_data").get("svr_total")
            else:
                number_of_instances = num

            for i in range(number_of_instances):
                print(i)
                await self.cmd_cowmaster_fork(i+1, starting_port)
                starting_port += 1
        except Exception as e:
            LOGGER.exception(e)

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
        await start_api_server(self.global_config, self.game_servers, self.tasks, self.health_check_manager.tasks, self.event_bus, self.find_replay_file, port=self.global_config['hon_data']['svr_api_port'])

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
        LOGGER.highlight(f"[*] HoNfigurator Manager - Listening on {host}:{game_server_to_mgr_port} (LOCAL)")

        await stop_event.wait()

        # Close all client connections
        for connection in list(self.client_connections.values()):
            await connection.close()

        # Close the server
        self.game_server_lsnr.close()
        await self.game_server_lsnr.wait_closed()

        await self.master_server_handler.close_session()

        LOGGER.info("Stopping HoNfigurator manager listener.")

    def update(self):
        MISC.update_github_repository()
        MISC.save_last_working_branch()

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
            prefix = (f"[{mserver_auth_response[1]}] Authentication to MasterServer failed. ")
            if mserver_auth_response[1] in [401, 403]:
                LOGGER.error(f"{prefix}Please ensure your username and password are correct in {HOME_PATH / 'config' / 'config.json'}")
            elif mserver_auth_response[1] > 500 and mserver_auth_response[1] < 600:
                LOGGER.error(f"{prefix}The issue is most likely server side.")
            raise HoNAuthenticationError(f"[{mserver_auth_response[1]}] Authentication error.")
        LOGGER.highlight("Authenticated to MasterServer.")
        parsed_mserver_auth_response = phpserialize.loads(mserver_auth_response[0].encode('utf-8'))
        parsed_mserver_auth_response = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_mserver_auth_response.items()}
        self.master_server_handler.set_server_id(parsed_mserver_auth_response['server_id'])
        self.master_server_handler.set_cookie(parsed_mserver_auth_response['session'])

        return parsed_mserver_auth_response


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

            except (HoNAuthenticationError, ConnectionResetError, Exception ) as e:
                LOGGER.error(f"{e.__class__.__name__} occurred. Retrying in {retry} seconds...")
                for _ in range(retry):
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(1)

        LOGGER.info("Stopping authentication handlers")
    async def authenticate_and_handle_chat_server(self, parsed_mserver_auth_response, udp_ping_responder_port):
        # Create a new ChatServerHandler instance and connect to the chat server
        self.chat_server_handler = ChatServerHandler(
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
        chat_auth_response = await self.chat_server_handler.connect()

        if not chat_auth_response:
            raise HoNAuthenticationError(f"Chatserver authentication failure")

        LOGGER.highlight("Authenticated to ChatServer.")

        # Start handling packets from the chat server
        await self.chat_server_handler.handle_packets()

    async def resubmit_match_stats_to_masterserver(self, match_id, file_path):
        mserver_stats_response = await self.master_server_handler.send_stats_file(f"{self.global_config['hon_data']['svr_login']}:", hashlib.md5(self.global_config['hon_data']['svr_password'].encode()).hexdigest(), match_id, file_path)
        if not mserver_stats_response or mserver_stats_response[1] != 200 or mserver_stats_response[0] == '':
            # .stats submission will not work until KONGOR implements accepting .stats from the custom written manager.
            # TODO: Update below to .error once upstream is configured to accept our stats.
            LOGGER.error(f"[{mserver_stats_response[1] if mserver_stats_response else 'unknown'}] Stats resubmission failed - {file_path}. Response: {mserver_stats_response[0] if mserver_stats_response else 'unknown'}")
            if mserver_stats_response and mserver_stats_response[1] == 400 and 'title' in mserver_stats_response[0]:
                if mserver_stats_response[0] == "One or more validation errors occurred.":
                    try:
                        shutil.move(file_path, f"{file_path}.failed")
                    except Exception:
                        LOGGER.error(traceback.format_exc())
            return False
        LOGGER.info(f"{match_id} Stats resubmission successful")
        parsed_mserver_stats_response = phpserialize.loads(mserver_stats_response[0].encode('utf-8'))
        parsed_mserver_stats_response = {key.decode() if isinstance(key, bytes) else key: (value.decode() if isinstance(value, bytes) else value) for key, value in parsed_mserver_stats_response.items()}

        return True

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
            # for port in servers_to_remove:
            #     await asyncio.sleep(0.1)
            #     if port in self.game_servers:
            #         game_server.cancel_tasks()
            #         del self.game_servers[port]

            LOGGER.info(f"Removed {servers_removed} {server_type} game servers. {total_num_servers - servers_removed} game servers are now running.")
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

    async def check_for_restart_required(self, game_server='all'):
        if game_server == 'all':
            for game_server in self.game_servers.values():
                if game_server.params_are_different():
                    await self.cmd_shutdown_server(game_server,disable=False)
                    self.cowmaster.stop_cow_master(disable=False)
                    await asyncio.sleep(0.1)
                    game_server.enable_server()
        else:
            if game_server.params_are_different():
                await self.cmd_shutdown_server(game_server,disable=False)
                self.cowmaster.stop_cow_master(disable=False)
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
        if game_server_port == self.cowmaster.get_port():
            return self.cowmaster

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

            if port == self.cowmaster.get_port():
                await self.cowmaster.set_client_connection(client_connection)
                self.cowmaster.status_received.set()

            else:

                game_server = self.game_servers.get(port, None)
                # this is in case game server doesn't exist (config change maybe)
                if game_server:
                    game_server.status_received.set()
                    await game_server.set_client_connection(client_connection)
                    await self.check_for_restart_required(game_server)
                # TODO
                # Create game server object here? May be happening already in game_packet_lsnr.py (handle_client_connection)
                # The instance of this happening, is for example, someone is running 10 servers. They modify the config on the fly to be 5 servers. Servers 5-10 are scheduled for shutdown, but game server objects have been destroyed.
                # since the game server isn't actually off yet, it will keep creating a connection.

            return True
        else:
            #TODO: raise error or happy with logger?
            if port == self.cowmaster.get_port():
                LOGGER.debug(f"Attempting to locate duplicate CowMaster server. Looking for TCP source port ({client_connection.addr[1]}) and TCP dest port ({self.global_config['hon_data']['svr_managerPort']})")
                cowmaster_proc = MISC.get_client_pid_by_tcp_source_port(self.global_config['hon_data']['svr_managerPort'], client_connection.addr[1])
                if cowmaster_proc:
                    LOGGER.info(f"Found duplicate CowMaster server. Killing process {cowmaster_proc.pid}")
                    cowmaster_proc.terminate()
                    return
                else:
                    LOGGER.warn("There is a duplicate CowMaster and we're unable to identify it's PID (Process ID). This  won't cause issues, but there may be some wasteful RAM usage.")
                    return
            LOGGER.error(f"A GameServer connection is already established for port {port}, this is either a dead connection, or something is very wrong (two servers with the same port).")
            return False

    async def find_replay_file(self,replay_file_name):
        replay_file_paths = [Path(self.global_config['hon_data']['hon_replays_directory']) / replay_file_name]
        if self.global_config['application_data']['longterm_storage']['active']:
            replay_file_paths.append(Path(self.global_config['application_data']['longterm_storage']['location']) / replay_file_name)

        for replay_path in replay_file_paths:
            file_exists = Path.exists(replay_path)
            if file_exists:
                replay_file_path = replay_path
                return True,replay_file_path

    async def handle_replay_request(self, match_id, extension, account_id):
        replay_file_name = f"M{match_id}.{extension}"
        LOGGER.debug(f"Received replay upload request.\n\tFile Name: {replay_file_name}\n\tAccount ID (requestor): {account_id}")

        replay_file_paths = [Path(self.global_config['hon_data']['hon_replays_directory']) / replay_file_name]
        if self.global_config['application_data']['longterm_storage']['active']:
            replay_file_paths.append(Path(self.global_config['application_data']['longterm_storage']['location']) / replay_file_name)
        file_exists,replay_file_path = await self.find_replay_file(replay_file_name)

        if not file_exists:
            # Send the "does not exist" packet
            # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.DOES_NOT_EXIST)
            res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.DOES_NOT_EXIST)
            non_existing_paths = [str(path) for path in replay_file_paths]
            LOGGER.warn(f"Replay file {replay_file_name} does not exist. Checked: {non_existing_paths}")
            return

        # Send the "exists" packet
        # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.QUEUED)
        res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.QUEUED)
        LOGGER.debug(f"Replay file exists ({replay_file_name}). Obtaining upload location information.")

        # Upload the file and send status updates as required
        file_size = os.path.getsize(replay_file_path)

        upload_details = await self.master_server_handler.get_replay_upload_info(match_id, extension, self.global_config['hon_data']['svr_login'], file_size)

        if upload_details is None or upload_details[1] != 200:
            # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            LOGGER.error(f"{replay_file_name} - Failed to obtain upload location information. HTTP Response ({upload_details[1]}):\n\t{upload_details[0]}")
            return

        upload_details_parsed = {key.decode(): (value.decode() if isinstance(value, bytes) else value) for key, value in upload_details[0].items()}
        LOGGER.debug(f"Uploading {replay_file_name} to {upload_details_parsed['TargetURL']}")

        LOGGER.debug(f"Uploading {replay_file_name} to {upload_details_parsed['TargetURL']}")

        # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOADING)
        res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.UPLOADING)
        try:
            upload_result = await self.master_server_handler.upload_replay_file(replay_file_path, replay_file_name, upload_details_parsed['TargetURL'])
        except Exception:
            LOGGER.error(f"Error uploading replay file {replay_file_path}")
            LOGGER.error(f"Undefined Exception: {traceback.format_exc()}")

        if upload_result[1] not in [204,200]:
            # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.GENERAL_FAILURE)
            LOGGER.error(f"Replay upload failed! HTTP Upload Response ({upload_result[1]})\n\t{upload_result[0]}")
            return
        # await self.event_bus.emit('replay_status_update', match_id, account_id, ReplayStatus.UPLOAD_COMPLETE)
        res = await self.chat_server_handler.create_replay_status_update_packet(match_id, account_id, ReplayStatus.UPLOAD_COMPLETE)
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
                    game_server.unset_client_connection()
                # indicate that the sub commands should be regenerated since the list of connected servers has changed.
                # await self.commands.initialise_commands()
                self.commands.subcommands_changed.set()
                return True
        return False

    def update_server_start_semaphore(self):
        max_start_at_once = self.global_config['hon_data']['svr_max_start_at_once']
        self.server_start_semaphore = asyncio.Semaphore(max_start_at_once)

    async def start_game_servers_task(self, game_servers):
        coro = self.start_game_servers(game_servers)
        self.schedule_task(coro, 'gameserver_startup')

    async def start_game_servers(self, game_servers, timeout=120, launch=False, service_recovery=False):
        try:
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
                if str(self.global_config['hon_data']['hon_install_directory']  / 'game') not in path_list:
                    os.environ["PATH"] = f"{self.global_config['hon_data']['hon_install_directory'] / 'game'}{os.pathsep}{self.preserved_path}"
            if MISC.get_os_platform() == "win32" and launch and await self.check_upstream_patch():
                if not await self.initialise_patching_procedure(source="startup"):
                    return False

            else:
                # TODO: Linux patching logic here?
                pass

            async def start_game_server_with_semaphore(game_server, timeout):
                game_server.game_state.update({'status':GameStatus.QUEUED.value})
                async with self.server_start_semaphore:
                    # Use the schedule_task method to start the server
                    if game_server not in self.game_servers.values():
                        return

                    # Ensure the task is actually a Task or Future
                    task = asyncio.ensure_future(game_server.schedule_task(game_server.start_server(timeout=timeout), 'start_server'))
                    try:
                        # Ensure asyncio.wait_for(task, timeout) and stop_event.wait() are Tasks
                        wait_for_task = asyncio.create_task(asyncio.wait_for(task, timeout))
                        stop_event_wait_task = asyncio.create_task(stop_event.wait())

                        # Prepare the tasks
                        tasks = [wait_for_task, stop_event_wait_task]

                        # Wait for any task to complete
                        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                        # If the stop_event was set, cancel the other task and return
                        if stop_event.is_set():
                            for task in pending:
                                task.cancel()
                            LOGGER.info(f"Shutting down uninitialised GameServer #{game_server.id} due to stop event.")
                            await self.cmd_shutdown_server(game_server)
                        else:
                            # The game server start task completed successfully
                            # LOGGER.info(f"GameServer #{game_server.id} started successfully.")
                            pass
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


            # setup or verify filebeat configuration for match log submission
            await filebeat_status()
            if launch:
                await filebeat(self.global_config)

                if self.use_cowmaster:
                    await self.cowmaster.start_cow_master()

                if not self.global_config['hon_data']['svr_start_on_launch']:
                    LOGGER.info("Waiting for manual server start up. svr_start_on_launch setting is disabled.")
                    return

            if not service_recovery and not get_filebeat_status()['running']:
                msg = f"Filebeat is not running, you may not start any game servers until you finalise the setup of filebeat.\nStatus\n\tInstalled: {get_filebeat_status()['installed']}\n\tRunning: {get_filebeat_status()['running']}\n\tCertificate Status: {get_filebeat_status()['certificate_status']}\n\tPending Auth: {True if get_filebeat_auth_url() else False}"
                if get_filebeat_auth_url():
                    print(f"Please authorise match log submissions to continue: {get_filebeat_auth_url()}")
                raise RuntimeError(msg)

            if self.use_cowmaster:
                if not self.cowmaster.client_connection:
                    if launch:
                        i = 0
                        incr = 5
                        while not self.cowmaster.client_connection:
                            LOGGER.warn(f"Waiting for CowMaster to connect to manager before starting servers. Waiting {i}/{timeout} seconds")
                            await asyncio.sleep(incr)
                            i += incr
                            if i > timeout:
                                return False
                    else:
                        LOGGER.warn("Cannot start servers. Cowmaster is in use, but not yet connected to the manager. Please wait and try again")
                        return

            for game_server in game_servers:
                start_tasks.append(start_game_server_with_semaphore(game_server, timeout))

            await asyncio.gather(*start_tasks)

            # indicate that the sub commands should be regenerated since the list of connected servers has changed.
            asyncio.create_task(self.commands.initialise_commands())
            self.commands.subcommands_changed.set()

        except Exception as e:
            LOGGER.error(f"GameServers failed to start\n{traceback.format_exc()}")
            if not launch:
                raise

    async def patch_extract_crc_from_file(self, url):
        try:
            with urllib.request.urlopen(url) as response:
                content = response.read().decode('utf-8')
            # sample: 4.10.8.0;4.10.8.honpatch;B30B80D1;hon_update_x64.zip;4DFDFDD5
            components = content.strip().split(';')
            version = components[0]
            patch = components[1]
            hon_exe_crc = components[2]
            filename = components[3]
            hon_update_exe_crc = components[-1]
            return hon_update_exe_crc

        except Exception as e:
            LOGGER.error(f"Error occurred while extracting CRC from file: {e}")
            return None

    async def initialise_patching_procedure(self, timeout=300, source=None):
        if self.patching:
            LOGGER.warn("Patching is already in progress.")
            return

        for game_server in self.game_servers.values():
            if game_server.started and game_server.enabled:
                await self.cmd_message_server(game_server, "!! ANNOUNCEMENT !! This server will shutdown after the current match for patching.")
            await self.cmd_shutdown_server(game_server)

        if MISC.get_proc(self.global_config['hon_data']['hon_executable_name']):
            return

        hon_update_x64_crc = await self.patch_extract_crc_from_file(HON_VERSION_URL)
        if (not exists(self.global_config['hon_data']['hon_install_directory'] / 'hon_update_x64.exe')) or (hon_update_x64_crc and hon_update_x64_crc.lower() != MISC.calculate_crc32(self.global_config['hon_data']['hon_install_directory'] / 'hon_update_x64.exe').lower()):
            try:
                temp_folder = tempfile.TemporaryDirectory()
                temp_path = temp_folder.name
                temp_zip_path = Path(temp_path) / 'hon_update_x64.zip'
                temp_update_x64_path = Path(temp_path) / 'hon_update_x64.exe'

                download_hon_update_x64 = urllib.request.urlretrieve(HON_UPDATE_X64_DOWNLOAD_URL, temp_zip_path)
                if not download_hon_update_x64:
                    LOGGER.warn(f"Newer hon_update_x64.zip is available, however the download failed.\n\t1. Please download the file manually: {HON_UPDATE_X64_DOWNLOAD_URL}\n\t2. Unzip the file into {self.global_config['hon_data']['hon_install_directory']}")
                    return

                temp_extracted_path = temp_folder.name
                MISC.unzip_file(source_zip=temp_zip_path, dest_unzip=temp_extracted_path)

                hon_update_x64_path = self.global_config['hon_data']['hon_install_directory'] / 'hon_update_x64.exe'

                # Check if the file is in use before moving it
                try:
                    shutil.move(temp_update_x64_path, hon_update_x64_path)
                except PermissionError:
                    LOGGER.warn(f"Hon Update - the file {self.global_config['hon_data']['hon_install_directory'] / 'hon_update_x64.exe'} is currently in use. Closing the file..")
                    process = MISC.get_proc(proc_name='hon_update_x64.exe')
                    if process: process.terminate()
                    try:
                        shutil.move(temp_update_x64_path, hon_update_x64_path)
                    except Exception:
                        LOGGER.error(f"HoN Update - Failed to copy downloaded hon_update_x64.exe into {self.global_config['hon_data']['hon_install_directory']}\n\t1. Please download the file manually: {HON_UPDATE_X64_DOWNLOAD_URL}\n\t2. Unzip the file into {self.global_config['hon_data']['hon_install_directory']}")
                        return

            except Exception as e:
                LOGGER.error(f"Error occurred during file download or extraction: {e}")

        patcher_exe = self.global_config['hon_data']['hon_install_directory'] / "hon_update_x64.exe"
        # subprocess.run([patcher_exe, "-norun"])
        try:
            subprocess.run([patcher_exe, "-norun"], timeout=timeout)

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
