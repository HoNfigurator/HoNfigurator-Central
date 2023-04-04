import cogs.handlers.data_handler as data_handler
import subprocess
import traceback
import asyncio
import psutil
import json
import math
import sys
import os
from cogs.misc.logging import flatten_dict, get_logger, get_home, get_misc
from cogs.TCP.packet_parser import GameManagerParser
from cogs.misc.utilities import Misc

LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()

class GameServer:
    def __init__(self, id, port, global_config, remove_self_callback):
        self.tasks = []
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
        self.scheduled_shutdown = False # used to determine if currently scheduled for shutdown
        self.game_manager_parser = GameManagerParser(self.id,LOGGER)
        """
        Game State specific variables
        """
        self.game_state = GameState()
        self.game_state.update({
            'status': None,
            'uptime': None,
            'num_clients': None,
            'match_started': None,
            'game_state_phase': None,
            'current_match_id': None,
            'players': [],
            'performance': {
                'grandtotal_skipped_frames': 0,
                'total_ingame_skipped_frames': 0,
                'now_ingame_skipped_frames': 0
            }
        })
        self.game_state.add_listener(self.on_game_state_change)
        self.data_file = os.path.join(f"{HOME_PATH}", "game_states", f"GameServer-{self.id}_state_data.json")
        self.load_gamestate_from_file(match_only=False)
        # Start the monitor_process method as a background task
        self.schedule_task(self.monitor_process())

    def schedule_task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    def cancel_tasks(self):
        for task in self.tasks:
            task.cancel()
    def link_client_connection(self,client_connection):
        self.client_connection = client_connection
    def on_game_state_change(self, key, value):
        if key == "match_started":
            if value == 0:
                self.set_server_priority_reduce()
            elif value == 1:
                LOGGER.info(f"GameServer #{self.id} -  Game Started: {self.game_state._state['current_match_id']}")
                self.set_server_priority_increase()
            # Add more phases as needed
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
                self.game_state._state['performance']['grandtotal_skipped_frames'] = performance_data['grandtotal_skipped_frames']
                self.game_state._state['performance']['total_ingame_skipped_frames'] = performance_data['total_ingame_skipped_frames']
            if self.game_state._state['current_match_id'] in performance_data:
                self.game_state._state.update({'now_ingame_skipped_frames':self.game_state._state['now_skipped_frames'] + performance_data[self.game_state._state['current_match_id']]['now_ingame_skipped_frames']})
    def save_gamestate_to_file(self):
        current_match_id = str(self.game_state._state['current_match_id'])

        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                performance_data = json.load(f)

            performance_data = {
                'grandtotal_skipped_frames':self.game_state._state['performance']['grandtotal_skipped_frames'],
                'total_ingame_skipped_frames':self.game_state._state['performance']['total_ingame_skipped_frames'],
                current_match_id: {
                    'now_ingame_skipped_frames': self.game_state._state['performance'].get('now_ingame_skipped_frames', 0)
                }
            }

        else:
            performance_data = {
                'grandtotal_skipped_frames': 0,
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

    def increment_skipped_frames(self, frames):
        self.game_state._state['performance']['grandtotal_skipped_frames'] +=frames
        if self.get_dict_value('match_started') == 1:
            self.game_state._state['performance']['total_ingame_skipped_frames'] += frames
            self.game_state._state['performance']['now_ingame_skipped_frames'] += frames

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
            'Status': 'Unknown',
            'Game Phase': 'Unknown',
            'Connections': 0,
            'Players': 'Unknown',
            'Uptime': 'Unknown',
            'Performance (lag)': f"{self.get_dict_value('grandtotal_skipped_frames')/1000} sec (grand total)\n{self.get_dict_value('total_ingame_skipped_frames')/1000} sec (total while in game)\n{self.get_dict_value('now_ingame_skipped_frames')/1000} sec (current game)"
        }
        if self.get_dict_value('status') == 0:
            temp['Status'] = 'Sleeping'
        if self.get_dict_value('status') == 1:
            temp['Status'] = 'Ready'
        elif self.get_dict_value('status') == 3:
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
        player_names = [player['name'] for player in self.game_state._state['players']] if 'players' in self.game_state._state else []
        temp['Game Phase'] = game_phase_mapping.get(self.get_dict_value('game_phase'), 'Unknown')
        temp['Players'] = ', '.join(player_names)
        temp['Uptime'] = format_time(self.get_dict_value('uptime') / 1000) if self.get_dict_value('uptime') is not None else 'Unknown'

        return flatten_dict(temp)

    async def start_server(self):
        if await self.get_running_server():
            self.scheduled_shutdown = False
            return True

        free_mem = psutil.virtual_memory().available
        #   HoN server instances use up to 1GM RAM per instance. Check if this is free before starting.
        if free_mem < 1000000000:
            raise Exception(f"GameServer #{self.id} - cannot start as there is not enough free RAM")

        #   Server instances write files to location dependent on USERPROFILE and APPDATA variables
        os.environ["USERPROFILE"] = self.global_config['hon_data']['hon_home_directory']
        os.environ["APPDATA"] = self.global_config['hon_data']['hon_home_directory']

        DETACHED_PROCESS = 0x00000008
        params = ';'.join(' '.join((f"Set {key}",str(val))) for (key,val) in self.config.local['params'].items())

        if MISC.get_os_platform() == "win32":
            cmdline_args = [self.config.local['config']['file_path'],"-dedicated","-noconfig","-execute",params,"-masterserver",self.global_config['hon_data']['svr_masterServer'],"-register",f"127.0.0.1:{self.global_config['hon_data']['svr_managerPort']}"]
            exe = subprocess.Popen(cmdline_args,close_fds=True, creationflags=DETACHED_PROCESS)
        else:
            cmdline_args = f'''{self.config.local['config']['file_path']} -dedicated -noconfig -execute '"{params}"' -masterserver {self.global_config['hon_data']['svr_masterServer']} -register 127.0.0.1:{self.global_config['hon_data']['svr_managerPort']}'''
            exe = subprocess.Popen(cmdline_args,close_fds=True, shell = True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._pid = exe.pid
        self._proc = exe
        self._proc_hook = psutil.Process(pid=exe.pid)
        self._proc_owner =self._proc_hook.username()
        self.scheduled_shutdown = False

        return True

    async def schedule_shutdown_server(self, client_connection, packet_data):
        self.scheduled_shutdown = True
        while True:
            num_clients = self.game_state["num_clients"]
            if num_clients is not None and num_clients > 0:
                await asyncio.sleep(10)
            else:
                await self.stop_server_nice(client_connection, packet_data)
                break

    async def stop_server_nice(self, client_connection, packet_data):
        if self.game_state["num_clients"] == 0:
            LOGGER.info(f"GameServer #{self.id} - Stopping")
            length_bytes, message_bytes = packet_data
            client_connection.writer.write(length_bytes)
            client_connection.writer.write(message_bytes)
            await client_connection.writer.drain()
            #self.remove_self_callback(self)
            await self.disable_server()
            await self.unschedule_shutdown()

    async def stop_server_exe(self):
        if self._proc:
            self._proc.terminate()
            #self.remove_self_callback(self)
            await self.disable_server()
            await self.unschedule_shutdown()

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
                    if not Misc.check_port(self.config.local['params']['svr_port']):
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
            self._proc_owner =proc.username()
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
            self._proc_hook.nice(0)
        LOGGER.info(f"GameServer #{self.id} - Priority set to Low.")
    def set_server_priority_increase(self):
        if sys.platform == "win32":
            self._proc_hook.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            self._proc_hook.nice(19)
        LOGGER.info(f"GameServer #{self.id} - Priority set to High.")
    async def monitor_process(self):
        while True:
            if self._proc is not None and self._proc_hook is not None:
                if not self._proc_hook.is_running() and self.enabled:
                    LOGGER.warning(f"GameServer #{self.id} - Starting...")
                    self._proc = None  # Reset the process reference
                    self._proc_hook = None  # Reset the process hook reference
                    self._pid = None
                    self._proc_owner = None
                    self.started = False
                    await self.start_server()  # Restart the server
                elif self._proc_hook.is_running() and not self.enabled and not self.scheduled_shutdown:
                    #   Schedule a shutdown, otherwise if shutdown is already scheduled, skip over
                    self.schedule_shutdown_server()
            await asyncio.sleep(5)  # Check every 5 seconds

    async def enable_server(self):
        self.enabled = True

    async def disable_server(self):
        self.enabled = False

    async def schedule_shutdown(self):
        self.scheduled_shutdown = True

    async def unschedule_shutdown(self):
        self.scheduled_shutdown = False

class GameState:
    def __init__(self):
        self._state = {}
        self._listeners = []

    def __getitem__(self, key):
        return self._state[key]

    def __setitem__(self, key, value):
        self._state[key] = value
        self._emit_event(key, value)

    def update(self, data):
        monitored_keys = ["match_started"]  # Put the list of items you want to monitor here

        for key, value in data.items():
            if key in monitored_keys and (key not in self._state or self[key] != value):
                self.__setitem__(key, value)
            else:
                self._state[key] = value

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _emit_event(self, key, value):
        for listener in self._listeners:
            listener(key, value)
