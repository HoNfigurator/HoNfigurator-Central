import cogs.handlers.data_handler as data_handler
import subprocess
import time
import traceback
import asyncio
import psutil
import json
import math
import sys
import os
from cogs.misc.logging import flatten_dict, get_logger, get_home, get_misc, print_formatted_text
from cogs.handlers.events import stop_event, GameStatus, EventBus as GameEventBus
from cogs.TCP.packet_parser import GameManagerParser
from cogs.misc.utilities import Misc

LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()

class GameServer:
    def __init__(self, id, port, global_config, remove_self_callback, manager_event_bus):
        self.tasks = {}
        self.manager_event_bus = manager_event_bus
        self.port = port
        self.id = id
        self.global_config = global_config
        self.remove_self_callback = remove_self_callback
        self.set_configuration()
        # self.set_controller()
        self.started = None
        self._pid = None
        self._proc = None
        self._proc_owner = None
        self._proc_hook = None
        self.enabled = True # used to determine if the server should run
        self.delete_me = False # used to mark a server for deletion after it's been shutdown
        self.scheduled_shutdown = False # used to determine if currently scheduled for shutdown
        self.game_manager_parser = GameManagerParser(self.id,LOGGER)
        """
        Game State specific variables
        """
        self.status_received = asyncio.Event()
        self.server_closed = asyncio.Event()
        self.game_state = GameState()
        self.reset_game_state()
        self.game_state.add_listener(self.on_game_state_change)
        self.data_file = os.path.join(f"{HOME_PATH}", "game_states", f"GameServer-{self.id}_state_data.json")
        self.load_gamestate_from_file(match_only=False)
        # Start the monitor_process method as a background task
        self.tasks.update({'process_monitor':asyncio.create_task(self.monitor_process())})

    def schedule_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    def cancel_tasks(self):
        for task in self.tasks.values():
            task.cancel()

    def reset_game_state(self):
        self.status_received.clear()
        self.game_state.clear()

    def params_are_different(self):
        current_params = self._proc_hook.cmdline()[4]
        new_params = ';'.join(' '.join((f"Set {key}",str(val))) for (key,val) in self.config.get_local_configuration()['params'].items())
        if current_params != new_params:
            return True
        return False

    async def on_game_state_change(self, key, value):
        # if not self.status_received.is_set():
        #     self.status_received.set()
        #   Indicates that a status update has been received (we have a live connection)
        if key == "match_started":
            if value == 0:
                self.set_server_priority_reduce()
            elif value == 1:
                LOGGER.info(f"GameServer #{self.id} -  Game Started: {self.game_state._state['current_match_id']}")
                self.set_server_priority_increase()
            # Add more phases as needed
        elif key == "match_info.mode":
            if value == "botmatch":
                self.tasks.update({'botmatch_shutdown':asyncio.create_task(self.manager_event_bus.emit('cmd_shutdown_server', self, force=True, delay=30))})
                while self.status_received.is_set() and not self.server_closed.set():
                    await self.manager_event_bus.emit('cmd_message_server', self, f"Bot matches are disallowed on {self.global_config['hon_data']['svr_name']}. Server closing.")
                    await asyncio.sleep(5)

    def unlink_client_connection(self):
        del self.client_connection
    def get_dict_value(self, attribute, default=None):
        if attribute in self.game_state._state:
            return self.game_state._state[attribute]
        elif attribute in self.game_state._state['performance']:
            return self.game_state._state['performance'][attribute]
        else:
            return default

    def update_dict_value(self, attribute, value):
        if attribute in self.game_state._state:
            self.game_state._state[attribute] = value
        elif attribute in self.game_state._state['performance']:
            self.game_state._state['performance'][attribute] = value
        else:
            raise KeyError(f"Attribute '{attribute}' not found in game_state or performance dictionary.")

    def set_configuration(self):
        self.config = data_handler.ConfigManagement(self.id,self.global_config)
    def load_gamestate_from_file(self,match_only):
        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                performance_data = json.load(f)
            if not match_only:
                self.game_state._state['performance']['total_ingame_skipped_frames'] = performance_data['total_ingame_skipped_frames']
            if self.game_state._state['current_match_id'] in performance_data:
                self.game_state._state.update({'now_ingame_skipped_frames':self.game_state._state['now_skipped_frames'] + performance_data[self.game_state._state['current_match_id']]['now_ingame_skipped_frames']})
    def save_gamestate_to_file(self):
        current_match_id = str(self.game_state._state['current_match_id'])

        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                performance_data = json.load(f)

            performance_data = {
                'total_ingame_skipped_frames':self.game_state._state['performance']['total_ingame_skipped_frames'],
                current_match_id: {
                    'now_ingame_skipped_frames': self.game_state._state['performance'].get('now_ingame_skipped_frames', 0)
                }
            }

        else:
            performance_data = {
                'total_ingame_skipped_frames': 0,
                current_match_id: {
                    'now_ingame_skipped_frames': self.game_state._state['performance'].get('now_ingame_skipped_frames', 0)
                }
            }

        with open(self.data_file, "w") as f:
            json.dump(performance_data, f)

    def update(self, game_data):
        self.__dict__.update(game_data)

    def get(self, attribute, default=None):
        return getattr(self, attribute, default)

    def reset_skipped_frames(self):
        self.game_state._state['performance']['now_ingame_skipped_frames'] = 0

    def increment_skipped_frames(self, frames, time):
        if self.get_dict_value('match_started') == 1: # Only log skipped frames when we're actually in a match.
            self.game_state._state['performance']['total_ingame_skipped_frames'] += frames
            self.game_state._state['performance']['now_ingame_skipped_frames'] += frames
            self.game_state._state['skipped_frames_detailed'][time] = frames

    def get_pretty_status(self):
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
            'Region':self.config.get_local_by_key('svr_location'),
            'Status': 'Unknown',
            'Game Phase': 'Unknown',
            'Connections': self.get_dict_value('num_clients'),
            'Players': 'Unknown',
            'Uptime': 'Unknown',
            'CPU Core': self.config.get_local_by_key('host_affinity'),
            'Scheduled Shutdown': 'Yes' if self.scheduled_shutdown else 'No',
            'Marked for Deletion': 'Yes' if self.delete_me else 'No',
            'Performance (lag)': {
                'total while in-game':f"{self.get_dict_value('total_ingame_skipped_frames')/1000} seconds",
                'current game':f"{self.get_dict_value('now_ingame_skipped_frames')/1000} seconds"
            },
        }
        if self.get_dict_value('status') == GameStatus.SLEEPING.value:
            temp['Status'] = 'Sleeping'
        elif self.get_dict_value('status') == GameStatus.READY.value:
            temp['Status'] = 'Ready'
        elif self.get_dict_value('status') == GameStatus.OCCUPIED.value:
            temp['Status'] = 'Occupied'
        elif self.get_dict_value('status') == GameStatus.STARTING.value:
            temp['Status'] = 'Starting'
        elif self.get_dict_value('status') == GameStatus.QUEUED.value:
            temp['Status'] = 'Queued'

        game_phase_mapping = {
            0: '',
            1: 'In-Lobby',
            2: 'Picking Phase',
            3: 'Picking Phase',
            4: 'Loading into match..',
            5: 'Preparation Phase',
            6: 'Match Started',
        }
        player_names = [player['name'] for player in self.game_state._state['players']] if 'players' in self.game_state._state else []
        temp['Game Phase'] = game_phase_mapping.get(self.get_dict_value('game_phase'), 'Unknown')
        temp['Players'] = ', '.join(player_names)
        temp['Uptime'] = format_time(self.get_dict_value('uptime') / 1000) if self.get_dict_value('uptime') is not None else 'Unknown'

        return (temp)

    def cancel_task(self, task_name):
        task = self.tasks.get(task_name)
        if task is not None:
            task.cancel()

    async def start_server(self, timeout=180):
        # clear any existing startup monitor tasks, and reset the startup timer
        self.reset_game_state()
        self.server_closed.clear()
        self.reset_start_timer()

        if await self.get_running_server():
            self.unschedule_shutdown()
            self.enable_server()
            self.started = True
            return True

        free_mem = psutil.virtual_memory().available
        #   HoN server instances use up to 1GM RAM per instance. Check if this is free before starting.
        if free_mem < 1000000000:
            raise Exception(f"GameServer #{self.id} - cannot start as there is not enough free RAM")


        params = ';'.join(' '.join((f"Set {key}",str(val))) for (key,val) in self.config.get_local_configuration()['params'].items())

        if MISC.get_os_platform() == "win32":
            # Server instances write files to location dependent on USERPROFILE and APPDATA variables
            os.environ["USERPROFILE"] = str(self.global_config['hon_data']['hon_home_directory'])
            # os.environ["APPDATA"] = str(self.global_config['hon_data']['hon_home_directory'])

            DETACHED_PROCESS = 0x00000008

            cmdline_args = [self.config.local['config']['file_path'],"-dedicated","-mod","game;KONGOR","-noconfig","-execute",params,"-masterserver",self.global_config['hon_data']['svr_masterServer'],"-register",f"127.0.0.1:{self.global_config['hon_data']['svr_managerPort']}"]
            exe = subprocess.Popen(cmdline_args,close_fds=True, creationflags=DETACHED_PROCESS)
        else:
            cmdline_args = [
                self.config.local['config']['file_path'],
                '-dedicated',
                '-noconfig',
                '-execute',
                f'"{params}"',
                '-masterserver',
                self.global_config['hon_data']['svr_masterServer'],
                '-register',
                f'127.0.0.1:{self.global_config["hon_data"]["svr_managerPort"]}'
            ]
            exe = subprocess.Popen(cmdline_args, shell = False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


        self._pid = exe.pid
        self._proc = exe
        self._proc_hook = psutil.Process(pid=exe.pid)
        self._proc_owner =self._proc_hook.username()
        self.scheduled_shutdown = False
        self.game_state.update({'status':GameStatus.STARTING.value})

        self.unschedule_shutdown()
        self.enable_server()
        self.started = True

        #self.tasks.update({'startup_monitor':asyncio.create_task(self.monitor_game_state_status())})

        try:
            start_time = time.perf_counter()
            done, pending = await asyncio.wait([self.status_received.wait(), self.server_closed.wait()], return_when=asyncio.FIRST_COMPLETED, timeout=timeout)
            for task in pending:
                task.cancel()

            if self.status_received.is_set():
                elapsed_time = time.perf_counter() - start_time
                LOGGER.info(f"GameServer #{self.id} with port {self.port} started successfully in {elapsed_time:.2f} seconds.")
                return True
            elif self.server_closed.is_set():
                LOGGER.warning(f"GameServer #{self.id} with port {self.port} closed prematurely. Stopped waiting for it.")
                return False
        except asyncio.TimeoutError:
            LOGGER.error(f"GameServer #{self.id} with port {self.port} timed out ({timeout} seconds) waiting for executable to send data. Closing executable. If you believe the server is just slow to start, you can either:\n\t1. Increase the 'svr_startup_timeout' value: setconfig hon_data svr_startup_timeout <new value>.\n\t2. Reduce the svr_max_start_at_once value: setconfig hon_data svr_max_start_at_once <new value>")
            self.schedule_shutdown()
            return False

    async def schedule_shutdown_server(self, client_connection, packet_data, delete=False):
        self.scheduled_shutdown = True
        self.delete_me = delete
        # TODO: Schedule doesn't work while servers are still booting up. Example, setconfig hon_data svr_total <new val>
        # I BELIEVE ABOVE IS FIXED, NEED TO TEST
        while True:
            num_clients = self.game_state["num_clients"]
            if num_clients is not None and num_clients > 0:
                await asyncio.sleep(10)
            else:
                await self.stop_server_network(client_connection, packet_data)
                if delete:
                    self.manager_event_bus.emit('remove_game_server',self)
                break

    async def monitor_game_state_status(self, timeout=60):
        self.set_start_timer(0)
        while not self.status_received.is_set():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                print_formatted_text(f"Task {asyncio.current_task().get_name()} is cancelled. Stopping the coroutine.")
                break

            self.increment_start_timer(1)
            if self.get_start_timer() >= timeout:
                LOGGER.error(f"GameServer #{self.id} either did not start correctly or took too long to start.")
                self.reset_start_timer()
                break

    def get_start_timer(self):
        return self.start_timer

    def set_start_timer(self, val):
        self.start_timer = val

    def increment_start_timer(self, val):
        self.start_timer += 1

    def reset_start_timer(self):
        self.start_timer = 0

    async def stop_server_network(self, client_connection, packet_data, nice=True):
        if nice:
            if self.game_state["num_clients"] != 0:
                return
        self.status_received.clear()

        LOGGER.info(f"GameServer #{self.id} - Stopping")
        length_bytes, message_bytes = packet_data
        client_connection.writer.write(length_bytes)
        client_connection.writer.write(message_bytes)
        await client_connection.writer.drain()
        self.started = False
        self.disable_server()
        self.unschedule_shutdown()
        self.server_closed.set()

    async def stop_server_exe(self):
        if self._proc:
            self._proc.terminate()
            self.started = False
            self.status_received.clear()
            self.disable_server()
            self.unschedule_shutdown()
            self.server_closed.set()

    async def get_running_server(self):
        """
            Check if existing hon server is running.
        """
        running_procs = Misc.get_proc(self.config.local['config']['file_name'], slave_id = self.id)
        last_good_proc = None

        while len(running_procs) > 0:
            last_good_proc = None
            for proc in running_procs[:]:
                status = self.get_dict_value('status')
                if status == 3:
                    last_good_proc = proc
                elif status is None:
                    if not Misc.check_port(self.config.get_local_configuration()['params']['svr_port']):
                        proc.terminate()
                        running_procs.remove(proc)
                    else:
                        last_good_proc = proc
            if last_good_proc is not None:
                break
        if last_good_proc:
            #   update the process information with the healthy instance PID. Healthy playercount is either -3 (off) or >= 0 (alive)
            self._pid = proc.pid
            self._proc = proc
            self._proc_hook = psutil.Process(pid=proc.pid)
            self._proc_owner = proc.username()
            try:
                # self.set_runtime_variables()
                return True
            except Exception:
                LOGGER.exception(f"{traceback.format_exc()}")
        else:
            return False
    def set_server_priority_reduce(self):
        if sys.platform == "win32":
            self._proc_hook.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            self._proc_hook.nice(20)
        LOGGER.info(f"GameServer #{self.id} - Priority set to Low.")
    def set_server_priority_increase(self):
        if sys.platform == "win32":
            self._proc_hook.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            self._proc_hook.nice(-19)
        LOGGER.info(f"GameServer #{self.id} - Priority set to High.")

    async def monitor_process(self):
        while not stop_event.is_set():
            if self._proc is not None and self._proc_hook is not None:
                if not self._proc_hook.is_running() and self.enabled:
                    LOGGER.info(f"GameServer #{self.id} - Starting...")
                    self._proc = None  # Reset the process reference
                    self._proc_hook = None  # Reset the process hook reference
                    self._pid = None
                    self._proc_owner = None
                    self.started = False
                    self.server_closed.set()  # Set the server_closed event
                    self.reset_game_state()
                    asyncio.create_task(self.manager_event_bus.emit('start_game_servers', self))  # Restart the server
                elif self._proc_hook.is_running() and not self.enabled and not self.scheduled_shutdown:
                    #   Schedule a shutdown, otherwise if shutdown is already scheduled, skip over
                    self.schedule_shutdown()

            await asyncio.sleep(5)  # Monitor process every 5 seconds

    def enable_server(self):
        self.enabled = True

    def disable_server(self):
        self.enabled = False

    def schedule_shutdown(self, delete=False):
        self.scheduled_shutdown = True
        self.delete_me = True

    def unschedule_shutdown(self):
        self.scheduled_shutdown = False
        self.delete_me = False

class GameState:
    def __init__(self):
        self._state = {}
        self._listeners = []

    def __getitem__(self, key):
        return self._state[key]

    def __setitem__(self, key, value):
        self._state[key] = value
        self._emit_event(key, value)

    def get_full_key(self, key, current_level, level=None, path=None):
        if level is None:
            level = self._state

        if path is None:
            path = []

        if level is current_level:
            path.append(key)
            return ".".join(path)

        for k, v in level.items():
            if isinstance(v, dict):
                new_path = path.copy()
                new_path.append(k)
                result = self.get_full_key(key, current_level, v, new_path)
                if result:
                    return result

        return None


    def update(self, data, current_level=None):
        monitored_keys = ["match_started", "match_info.mode"]  # Put the list of items you want to monitor here

        # If we are at the root level, set the current level to the main dictionary
        if current_level is None:
            current_level = self._state

        for key, value in data.items():
            if isinstance(value, dict):
                # If the key does not exist in the current level, create an empty dictionary
                if key not in current_level:
                    current_level[key] = {}
                self.update(value, current_level[key])
            else:
                # Check if the full key is in the monitored_keys list
                full_key = self.get_full_key(key, current_level)
                if full_key in monitored_keys and (full_key not in self._state or self[full_key] != value):
                    self.__setitem__(full_key, value)
                else:
                    current_level[key] = value

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _emit_event(self, key, value):
        for listener in self._listeners:
            asyncio.create_task(listener(key, value))

    def clear(self):
        self.update({
            'status': None,
            'uptime': None,
            'num_clients': None,
            'match_started': None,
            'game_state_phase': None,
            'current_match_id': None,
            'players': [],
            'performance': {
                'total_ingame_skipped_frames': 0,
                'now_ingame_skipped_frames': 0
            },
            'skipped_frames_detailed': {},
            'match_info':{
                'map':None,
                'mode':None,
                'name':None,
                'match_id':None
            }
        })
