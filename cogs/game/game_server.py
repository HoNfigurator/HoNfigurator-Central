import cogs.handlers.data_handler as data_handler
import subprocess
import traceback
import asyncio
import psutil
import time
import json
import math
import sys
import os
from datetime import datetime, timedelta
from os.path import exists
from cogs.misc.logger import get_logger, get_home, get_misc, get_mqtt
from cogs.handlers.events import stop_event, GameStatus, GameServerCommands, GamePhase
from cogs.misc.exceptions import HoNCompatibilityError, HoNInvalidServerBinaries, HoNServerError
from cogs.misc.logparser import find_game_info_post_launch, find_match_id_post_launch
from cogs.TCP.packet_parser import GameManagerParser
from cogs.db.roles_db_connector import RolesDatabase
import aiofiles
import glob
import re
import random

LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()

class GameServer:
    def __init__(self, id, port, global_config, remove_self_callback, manager_event_bus):
        self.tasks = {
            'process_monitor': None,
            'match_monitor': None,
            'botmatch_shutdown': None,
            'proxy_task': None,
            'idle_disconnect_timer': None,
            'shutdown_self': None
        }
        self.manager_event_bus = manager_event_bus
        self.port = port
        self.id = id
        self.global_config = global_config
        self.remove_self_callback = remove_self_callback
        self.set_configuration()
        self.started = None
        self._pid = None
        self._proc = None
        self._proc_owner = None
        self._proc_hook = None
        self._proxy_process = None
        self.enabled = True # used to determine if the server should run
        self.delete_me = False # used to mark a server for deletion after it's been shutdown
        self.scheduled_shutdown = False # used to determine if currently scheduled for shutdown
        self.game_manager_parser = GameManagerParser(self.id,LOGGER,mqtt=get_mqtt())
        self.client_connection = None
        self.idle_disconnect_timer = 0
        self.game_in_progress = False
        """
        Game State specific variables
        """
        self.status_received = asyncio.Event()
        self.server_closed = asyncio.Event()
        self.game_state = GameState(self.id, self.config.local)
        self.reset_game_state()
        self.game_state.add_listener(self.on_game_state_change)
        self.game_state._state.update({'instance_id': self.id})
        self.game_state._state.update({'instance_name': self.id})
        self.data_file = os.path.join(f"{HOME_PATH}", "game_states", f"GameServer-{self.id}_state_data.json")
        # asyncio.create_task(self.load_gamestate_from_file(match_only=False)) # disabled function
        # Start the monitor_process method as a background task
        coro = self.monitor_process
        self.schedule_task(coro,'process_monitor', coro_bracket=True)
        # Start the heartbeat task. This sends a status update to MQTT
        coro = self.heartbeat
        self.schedule_task(coro, 'heartbeat', coro_bracket=True)

    def schedule_task(self, coro, name, coro_bracket = False):
        existing_task = self.tasks.get(name)  # Get existing task if any

        if existing_task is not None:
            if not isinstance(existing_task, asyncio.Task):
                LOGGER.error(f"GameServer #{self.id} Item '{name}' in tasks is not a Task object.")
                # Choose one of the following lines, depending on your requirements:
                # raise ValueError(f"Item '{name}' in tasks is not a Task object.")  # Option 1: raise an error
                existing_task = None  # Option 2: ignore the non-Task item and overwrite it later

        if existing_task:
            if existing_task.done():
                if not existing_task.cancelled():
                    # If the task has finished and was not cancelled, retrieve any possible exception to avoid 'unretrieved exception' warnings
                    exception = existing_task.exception()
                    if exception:
                        LOGGER.error(f"GameServer #{self.id} The previous task '{name}' raised an exception: {exception}. We are scheduling a new one.")
                else:
                    LOGGER.info(f"GameServer #{self.id} The previous task '{name}' was cancelled.")
            else:
                # Task is still running
                LOGGER.debug(f"GameServer #{self.id} Task '{name}' is still running, new task not scheduled.")
                return existing_task  # Return existing task

        # Create and register the new task
        if coro_bracket:
            task = asyncio.create_task(coro())
        else:
            task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: setattr(t, 'end_time', datetime.now()))
        self.tasks[name] = task
        return task

    def stop_task(self, task):
        if task is None:
            return
        elif isinstance(task, asyncio.Task):
            if not task.done():
                task.cancel()
                return True
        else:
            return

    def cancel_tasks(self):
        for task in self.tasks.values():
            self.stop_task(task)
    
    def get_public_game_port(self):
        if self.config.local['params']['man_enableProxy']:
            return self.config.local['params']['svr_proxyPort']
        else:
            return self.config.local['params']['svr_port']

    def get_public_voice_port(self):
        if self.config.local['params']['man_enableProxy']:
            return self.config.local['params']['svr_proxyRemoteVoicePort']
        else:
            return self.config.local['params']['svr_proxyLocalVoicePort']

    def reset_game_state(self):
        LOGGER.debug(f"GameServer #{self.id} - Reset state")
        self.status_received.clear()
        self.game_state.clear()

    def params_are_different(self):
        if not self._proc_hook: return

        try:
            current_params = self._proc_hook.cmdline()
        except psutil.NoSuchProcess:
            return False
        self.set_configuration()
        if self.global_config['hon_data'].get('man_use_cowmaster'):
            new_params = MISC.build_commandline_args(data_handler.get_cowmaster_configuration(self.global_config['hon_data']), self.global_config, cowmaster=True)
        else:
            new_params = MISC.build_commandline_args(self.config.local, self.global_config)
        
        if current_params != new_params:
            LOGGER.info(f"GameServer #{self.id} New configuration has been provided. Existing executables must be relaunched, as their settings do not match the incoming settings.")
            return True
        LOGGER.debug(f"GameServer #{self.id} A server configuration change has been suggested, but the suggested settings and existing live executable settings match. Skipping.")
        return False

    async def match_timer(self):
        while True:
            elapsed_time = time.time() - self.game_state['match_info']['start_time']
            self.game_state['match_info']['duration'] = elapsed_time
            await asyncio.sleep(1)

    async def start_match_timer(self):
        self.game_state['match_info']['start_time'] = time.time()
        coro = self.match_timer
        self.schedule_task(coro, 'match_monitor', coro_bracket=True)

    async def stop_match_timer(self):
        self.stop_task(self.tasks['match_monitor'])
        self.game_state['match_info']['start_time'] = 0

    async def start_disconnect_timer(self):
        while True:
            self.idle_disconnect_timer += 1
            if self.idle_disconnect_timer >= 60:
                await self.manager_event_bus.emit('cmd_message_server', self, "Removing idle players. Players have remained connected when game is over for 60+ seconds.")
                LOGGER.info(f"GameServer #{self.id} - Removing idle players. Players have remained connected when game is over for 60+ seconds.\n\tGame Phase: {GamePhase(self.game_state['game_phase']).name if self.game_state['game_phase'] else 'unknown'}")

                i = 0
                while len(self.game_state['players']) > 0 and i < 12:
                    for player in list(self.game_state['players']):
                        player_name = player['name']
                        player_name = re.sub(r'\[.*?\]', '', player_name)
                        LOGGER.info(f"GameServer #{self.id} - Attempting to terminate player: {player_name}")
                        await self.manager_event_bus.emit('cmd_custom_command', self, f"terminateplayer {player_name}", delay=5)

                    LOGGER.info(f"GameServer #{self.id} - {self.game_state['players']} are still connected. Waiting for termination of idle players.")
                    await asyncio.sleep(5)
                    i += 1

                if len(self.game_state['players']) > 0:
                    LOGGER.info(f"GameServer #{self.id} - Waited 1 minute. Players still connected. Resetting server.")
                    await self.manager_event_bus.emit('cmd_custom_command', self, "serverreset", delay=5)
                    if get_mqtt():
                        get_mqtt().publish_json("game_server/match",{"event_type":"server_reset", "reason": "players still connected after 60 seconds when game is ended.", **self.game_state._state})

                break
            await asyncio.sleep(1)

    async def stop_disconnect_timer(self):
        self.stop_task(self.tasks['idle_disconnect_timer'])
        self.idle_disconnect_timer = 0

    async def on_game_state_change(self, key, value, old_value):
        if key == "match_started":
            if value == 0:
                LOGGER.debug(f"GameServer #{self.id} - Game Ended: {self.game_state['current_match_id']}")
                if get_mqtt():
                    get_mqtt().publish_json("game_server/match", {"event_type":"match_ended", **self.game_state._state})

                await self.set_server_priority_reduce()
                await self.stop_match_timer()
                await self.stop_disconnect_timer()
                await self.stop_monitor_skipped_frames()
                if self.global_config['hon_data']['svr_restart_between_games'] and self.game_in_progress:
                    LOGGER.info(f"GameServer #{self.id} - Restart game server between games as 'svr_restart_between_games' is enabled.")
                    coro = self.schedule_shutdown_server(disable=False)
                    self.schedule_task(coro,'shutdown_self')
                    self.game_in_progress = False
            elif value == 1:
                LOGGER.info(f"GameServer #{self.id} -  Game Started: {self.game_state._state['current_match_id']}")
                if get_mqtt():
                    get_mqtt().publish_json("game_server/match", {"event_type":"match_started", **self.game_state._state})
                self.game_in_progress = True
                await self.set_server_priority_increase()
                await self.start_match_timer()
                await self.schedule_task(self.start_monitor_skipped_frames,'monitor_skipped_frames',coro_bracket=True)
            # Add more phases as needed
        elif key == "game_phase":
            LOGGER.debug(f"GameServer #{self.id} - Game phase {value}")
            if get_mqtt():
                get_mqtt().publish_json("game_server/match", {"event_type":"phase_change", **self.game_state._state})
            if value == GamePhase.IDLE.value and self.scheduled_shutdown:
                await self.stop_server_network()
            elif value in [GamePhase.GAME_ENDING.value,GamePhase.GAME_ENDED.value]:
                skipped_frames = self.get_dict_value('now_ingame_skipped_frames')

                performance = None
                if 0 <= skipped_frames < 5000:
                    # performance = "Excellent." # we don't care
                    pass
                elif 5000 <= skipped_frames < 10000:
                    # performance = "Acceptable." # we don't care
                    pass
                elif skipped_frames >= 10000:
                    performance = "Poor. Host has been notified."
                
                if performance:
                    await self.manager_event_bus.emit('cmd_message_server', self, f"Total server lag: {skipped_frames /1000} seconds. Lag rating: {performance}")

                if skipped_frames > 5000 and value == GamePhase.GAME_ENDED.value:
                    # send request to management.honfig requesting administrator be notified
                    await self.manager_event_bus.emit(
                        'notify_discord_admin',
                        type='lag',
                        time_lagged=skipped_frames / 1000,
                        instance=self.id,
                        server_name=self.global_config['hon_data']['svr_name'],
                        match_id=self.get_dict_value('current_match_id')
                    )
                LOGGER.debug(f"GameServer #{self.id} - Game in final stages, game ending.")
                await self.schedule_task(self.start_disconnect_timer,'idle_disconnect_timer', coro_bracket=True)

            # add more phases as needed

        elif key == "status":
            if value == GameStatus.OCCUPIED.value and self.game_state._state['current_match_id'] == 0:
                match_id = await find_match_id_post_launch(self.id, self.global_config['hon_data']['hon_logs_directory'])
                if match_id:
                    self.game_state.update({'current_match_id':match_id, 'match_info':{'match_id':match_id}})
                    await self.manager_event_bus.emit('cmd_custom_command', self, 'FlushServerLogs') # force server to dump the logs
                    file_path = self.global_config['hon_data']['hon_logs_directory'] / f"M{match_id}.log"
                    match_info = await find_game_info_post_launch(self.id, file_path)
                    if match_info:
                        self.game_state.update({'match_info':match_info})

        elif key == "match_info.mode":
            if value == "botmatch" and not self.global_config['hon_data']['svr_enableBotMatch']:

                delay = 30
                coro = self.manager_event_bus.emit('cmd_custom_command', self, "serverreset", delay=delay)
                self.schedule_task(coro,'botmatch_shutdown')

                msg_count = 0
                while self.game_state['status'] != GameStatus.READY.value:
                    await self.manager_event_bus.emit('cmd_message_server', self, f"Bot matches are disallowed on {self.global_config['hon_data']['svr_name']}. Server closing in {delay - (msg_count*5)} seconds.")
                    msg_count +=1
                    if msg_count > 10:
                        break
                    await asyncio.sleep(5)

        elif key == "players":
            stable_keys = ['name', 'ip', 'location', 'account_id']

            # Extract the relevant keys and values from the player dictionaries
            old_players = [{k: player[k] for k in stable_keys} for player in old_value]
            new_players = [{k: player[k] for k in stable_keys} for player in value]

            # Convert the dictionaries to JSON strings and create sets
            old_value_set = set(json.dumps(player) for player in old_players)
            value_set = set(json.dumps(player) for player in new_players)

            # Find players who left
            left_players = old_value_set - value_set
            # Find players who joined
            joined_players = value_set - old_value_set

            # Convert the JSON strings back to dictionaries for easy reading
            left_players = [json.loads(player) for player in left_players]
            joined_players = [json.loads(player) for player in joined_players]

            if len(joined_players) > 0:
                if get_mqtt():
                    get_mqtt().publish_json("game_server/match", {"event_type":"player_connection", "player_name":joined_players[0]['name'], "player_ip":joined_players[0]['ip'], **self.game_state._state})
            elif len(left_players) >0:
                if get_mqtt():
                    get_mqtt().publish_json("game_server/match", {"event_type":"player_disconnection", "player_name":left_players[0]['name'], "player_ip":left_players[0]['ip'], **self.game_state._state})

    def unlink_client_connection(self):
        del self.client_connection
    def get_dict_value(self, attribute, default=None):
        if attribute in self.game_state._state:
            return self.game_state._state[attribute]
        elif attribute in self.game_state._performance:
            return self.game_state._performance[attribute]
        else:
            return default

    def update_dict_value(self, attribute, value):
        if attribute in self.game_state._state:
            self.game_state.update({attribute:value})
        elif attribute in self.game_state._performance:
            return self.game_state._performance[attribute]
        else:
            raise KeyError(f"Attribute '{attribute}' not found in game_state or performance dictionary.")

    async def set_client_connection(self, client_connection):
        self.client_connection = client_connection
        await self.get_running_server()

        # when servers connect they may be in a "Sleeping" state. Wake them up
        await self.client_connection.send_packet(GameServerCommands.WAKE_BYTES.value, send_len=True)

    def unset_client_connection(self):
        self.client_connection = None
        if get_mqtt():
            get_mqtt().publish_json("game_server/status",{"event_type":"server_disconnected", **self.game_state._state})

    def set_configuration(self):
        self.config = data_handler.ConfigManagement(self.id,self.global_config)

    async def load_gamestate_from_file(self,match_only):
        # TODO: this function needs re-writing if we choose to continue to use it. It isn't used at the moment
        if exists(self.data_file):
            # Reading JSON
            async with aiofiles.open(self.data_file, "r") as f:
                performance_data = json.loads(await f.read())
            if not match_only:
                self.game_state._performance['total_ingame_skipped_frames'] = performance_data['total_ingame_skipped_frames']
            if self.game_state._state['current_match_id'] in performance_data:
                self.game_state._performance.update({'now_ingame_skipped_frames':self.game_state._performance['total_ingame_skipped_frames'] + performance_data[self.game_state._state['current_match_id']]['now_ingame_skipped_frames']})
    
    async def save_gamestate_to_file(self):
        # TODO: this function needs re-writing if we choose to continue to use it. It isn't used at the moment
        current_match_id = str(self.game_state._state['current_match_id'])

        if exists(self.data_file):
            # Reading JSON
            async with aiofiles.open(self.data_file, "r") as f:
                performance_data = json.loads(await f.read())

            performance_data = {
                'total_ingame_skipped_frames':self.game_state._performance['total_ingame_skipped_frames'],
                current_match_id: {
                    'now_ingame_skipped_frames': self.game_state._performance.get('now_ingame_skipped_frames', 0)
                }
            }

        else:
            performance_data = {
                'total_ingame_skipped_frames': 0,
                current_match_id: {
                    'now_ingame_skipped_frames': self.game_state._state['performance'].get('now_ingame_skipped_frames', 0)
                }
            }

        async with aiofiles.open(self.data_file, "w") as f:
            await f.write(json.dumps(performance_data))

    def update(self, game_data):
        self.__dict__.update(game_data)

    def get(self, attribute, default=None):
        return getattr(self, attribute, default)

    def reset_skipped_frames(self):
        self.game_state._performance['now_ingame_skipped_frames'] = 0

    async def start_monitor_skipped_frames(self, threshold=6000, interval_seconds=120):
        """
            This function will monitor the skipped frames in segments and report on it in-game if it breaches a threshold.
        """
        while True:
            self.game_state._performance['monitored_skipped_frames'] = 0
            for _ in range(interval_seconds):
                if stop_event.is_set():
                    break
                await asyncio.sleep(1)
            if self.game_state._performance['monitored_skipped_frames'] > threshold:
                if self.game_state._performance['monitored_skipped_frames'] > 1000:
                    duration = f"{self.game_state._performance['monitored_skipped_frames'] / 1000} seconds"
                else:
                    duration = f"{self.game_state._performance['monitored_skipped_frames']} miliseconds"

                LOGGER.warn(f"GameServer #{self.id} - Server lagged {duration} in the last {interval_seconds} seconds which is above threshold ({threshold}ms).")
                try:
                    await self.manager_event_bus.emit('cmd_message_server', self, f"Server lag detected on {self.global_config['hon_data']['svr_name']}-{self.id}. This is being monitored and will be reported to the administrator if it continues.")
                except Exception:
                    LOGGER.error(traceback.format_exc())
                # Reset the monitored skipped frames to 0, for the next iteration
                self.game_state._performance['monitored_skipped_frames'] = 0

    async def stop_monitor_skipped_frames(self):
        self.stop_task(self.tasks['monitor_skipped_frames'])
        self.game_state._performance['monitored_skipped_frames'] = 0

    async def increment_skipped_frames(self, frames, time):
        if self.get_dict_value('game_phase') in [5,6,7]:  # Only log skipped frames when we're actually in a match (preparation phase, during match, or game ending).
            self.game_state._performance['total_ingame_skipped_frames'] += frames
            self.game_state._performance['now_ingame_skipped_frames'] += frames
            self.game_state._performance['monitored_skipped_frames'] += frames
            self.game_state._performance['skipped_frames_detailed'][time] = frames

            # Remove entries older than one day
            one_day_ago = time - timedelta(days=1).total_seconds()
            self.game_state._performance['skipped_frames_detailed'] = {key: value for key, value in self.game_state._performance['skipped_frames_detailed'].items() if key >= one_day_ago}
            if get_mqtt():
                get_mqtt().publish_json("game_server/lag",{"event_type": "skipped_frame", "skipped_frames": frames, **self.game_state._state})


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
            'Match ID': self.get_dict_value('current_match_id',None),
            'Public Game Port': self.get_public_game_port(),
            'Public Voice Port': self.get_public_voice_port(),
            'Region':self.config.get_local_by_key('svr_location'),
            'Status': 'Unknown',
            'Game Phase': 'Unknown',
            'Connections': self.get_dict_value('num_clients'),
            'Players': 'Unknown',
            'Uptime': 'Unknown',
            'CPU Core': ','.join(MISC.get_server_affinity(self.id, self.global_config['hon_data']['svr_total_per_core'])),
            'Scheduled Shutdown': 'Yes' if self.scheduled_shutdown else 'No',
            'Marked for Deletion': 'Yes' if self.delete_me else 'No',
            'Performance (lag)': {
                'total while in-game':f"{self.get_dict_value('total_ingame_skipped_frames')/1000} seconds",
                'current game':f"{self.get_dict_value('now_ingame_skipped_frames')/1000} seconds"
            },
        }
        if self.get_dict_value('status') == GameStatus.SLEEPING.value: # 0
            temp['Status'] = 'Sleeping'
        elif self.get_dict_value('status') == GameStatus.READY.value: # 1
            temp['Status'] = 'Ready'
        elif self.get_dict_value('status') == GameStatus.OCCUPIED.value: # 3, yes it skipped 2
            temp['Status'] = 'Occupied'
        elif self.get_dict_value('status') == GameStatus.STARTING.value: # 4
            temp['Status'] = 'Starting'
        elif self.get_dict_value('status') == GameStatus.QUEUED.value: # 5
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

    def get_pretty_status_for_webui(self):
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
            'Match ID': self.get_dict_value('current_match_id', None),
            'Local Game Port': self.port,
            'Local Voice Port': self.config.local['params']['svr_proxyLocalVoicePort'],
            'Public Game Port': self.get_public_game_port(),
            'Public Voice Port': self.get_public_voice_port(),
            'Region': self.config.get_local_by_key('svr_location'),
            'Status': 'Unknown',
            'Game Phase': 'Unknown',
            'Match Duration': 'Unknown',  # Initialize with default value
            'Connections': self.get_dict_value('num_clients'),
            'Players': 'Unknown',
            'Uptime': 'Unknown',
            'CPU Core': ','.join(MISC.get_server_affinity(self.id, self.global_config['hon_data']['svr_total_per_core'])),
            'CPU Utilisation': self.get_dict_value('cpu_core_util'),
            'Scheduled Shutdown': 'Yes' if self.scheduled_shutdown else 'No',
            'Marked for Deletion': 'Yes' if self.delete_me else 'No',
            'Proxy Enabled': 'Yes' if self.config.local['params']['man_enableProxy'] else 'No',
            'Performance (lag)': {
                'current game': f"{self.get_dict_value('now_ingame_skipped_frames') / 1000} seconds"
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

        if self.game_state['match_started'] == 1:
            if self.game_state['match_info']['duration']:
                temp['Match Duration'] = format_time(self.game_state['match_info']['duration'])

        temp['Uptime'] = format_time(self.get_dict_value('uptime') / 1000) if self.get_dict_value('uptime') is not None else 'Unknown'

        # for k,v in list(temp.items()):
        #     if v == "Unknown": del temp[k]

        return temp

    def cancel_task(self, task_name):
        task = self.tasks.get(task_name)
        if task is not None:
            task.cancel()

    def get_fork_bytes(self):
        """
            Return the bytearray required to fork this game server from the cowmaster
        """
        return b'\x28' + self.id.to_bytes(1, "little") + self.port.to_bytes(2, "little") + b'\x00'

    def set_server_affinity(self):
        if not self.global_config['hon_data']['svr_override_affinity']:
            return
        affinity = []
        for _ in MISC.get_server_affinity(self.id, self.global_config['hon_data']['svr_total_per_core']):
            affinity.append(int(_))
        self._proc_hook.cpu_affinity(affinity)  # Set CPU affinity


    def get_fork_bytes(self):
        """
            Return the bytearray required to fork this game server from the cowmaster
        """
        return b'\x28' + self.id.to_bytes(1, "little") + self.port.to_bytes(2, "little") + b'\x00'

    def set_server_affinity(self):
        if not self.global_config['hon_data']['svr_override_affinity']:
            return
        affinity = []
        for _ in MISC.get_server_affinity(self.id, self.global_config['hon_data']['svr_total_per_core']):
            affinity.append(int(_))
        self._proc_hook.cpu_affinity(affinity)  # Set CPU affinity


    async def start_server(self, timeout=180):
        self.reset_game_state()
        self.server_closed.clear()

        if await self.get_running_server():
            self.unschedule_shutdown()
            self.enable_server()
            self.started = True
            return True

        free_mem = psutil.virtual_memory().available
        #   HoN server instances use up to 1GM RAM per instance. Check if this is free before starting.
        if free_mem < 1000000000 and not self.global_config['hon_data']['man_use_cowmaster']:
            LOGGER.error((f"GameServer #{self.id} - cannot start as there is not enough free RAM"))
            raise HoNServerError(f"GameServer #{self.id} - cannot start as there is not enough free RAM")
        LOGGER.info(f"GameServer #{self.id} - Starting...")

        coro = self.start_proxy
        self.schedule_task(coro,'proxy_task', coro_bracket=True)

        if self.global_config['hon_data'].get('man_use_cowmaster'):
            await self.manager_event_bus.emit('fork_server_from_cowmaster', self)

        else:
            # params = ';'.join(' '.join((f"Set {key}",str(val))) for (key,val) in self.config.get_local_configuration()['params'].items())
            cmdline_args = MISC.build_commandline_args( self.config.local, self.global_config)

            if MISC.get_os_platform() == "win32":
                # Server instances write files to location dependent on USERPROFILE and APPDATA variables
                os.environ["APPDATA"] = str(self.global_config['hon_data']['hon_artefacts_directory'])
                os.environ["USERPROFILE"] = str(self.global_config['hon_data']['hon_home_directory'])
                DETACHED_PROCESS = 0x00000008
                exe = subprocess.Popen(cmdline_args,close_fds=True, creationflags=DETACHED_PROCESS)

            else: # linux
                exe = subprocess.Popen(cmdline_args,close_fds=True,start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            self._pid = exe.pid
            self._proc = exe
            self._proc_hook = psutil.Process(pid=exe.pid)
            self._proc_owner =self._proc_hook.username()

            if MISC.get_os_platform() == "win32":
                self.set_server_affinity()

        self.scheduled_shutdown = False
        self.game_state.update({'status':GameStatus.STARTING.value})

        self.unschedule_shutdown()
        self.enable_server()
        self.started = True

        try:
            start_time = time.perf_counter()
            status_received_future = asyncio.ensure_future(self.status_received.wait())
            server_closed_future = asyncio.ensure_future(self.server_closed.wait())

            done, pending = await asyncio.wait([status_received_future, server_closed_future], return_when=asyncio.FIRST_COMPLETED, timeout=timeout)


            if len(pending) == 2: # both status_received and server_closed are not completed. This indicates a timeout
                for task in pending:
                    task.cancel()
                LOGGER.error(f"GameServer #{self.id} startup timed out. {timeout} seconds waited for executable to send data. Closing executable. If you believe the server is just slow to start, you can either:\n\t1. Increase the 'svr_startup_timeout' value: setconfig hon_data svr_startup_timeout <new value>.\n\t2. Reduce the svr_max_start_at_once value: setconfig hon_data svr_max_start_at_once <new value>")
                await self.stop_server_exe()
                return False

            if self.status_received.is_set():
                elapsed_time = time.perf_counter() - start_time
                LOGGER.interest(f"GameServer #{self.id} with public ports {self.get_public_game_port()}/{self.get_public_voice_port()} started successfully in {elapsed_time:.2f} seconds.")
                if get_mqtt():
                    get_mqtt().publish_json("game_server/status", {"event_type":"server_started", **self.game_state._state})
                return True
            elif self.server_closed.is_set():
                LOGGER.warn(f"GameServer #{self.id} closed prematurely. Stopped waiting for it.")
                return False
        except Exception as e:
            LOGGER.error(f"GameServer #{self.id} - Unexpected error occurred: {traceback.format_exc()}")
            return False

    def mark_for_deletion(self):
        self.delete_me = True


    async def schedule_shutdown_server(self, delete=False, disable=True):
        self.schedule_shutdown()
        self.delete_me = delete
        if disable:
            self.disable_server()
        if self.game_state['game_phase'] == GamePhase.IDLE.value:
            await self.stop_server_network()
            self.delete_me = False

    async def stop_server_network(self, nice=True):
        if nice:
            if self.game_state["num_clients"] != 0:
                return

        self.status_received.clear()
        self.stop_proxy()
        LOGGER.info(f"GameServer #{self.id} - Stopping")
        self.client_connection.writer.write(GameServerCommands.COMMAND_LEN_BYTES.value)
        self.client_connection.writer.write(GameServerCommands.SHUTDOWN_BYTES.value)
        await self.client_connection.writer.drain()
        self.started = False
        self.unschedule_shutdown()
        self.server_closed.set()
        self.reset_game_state()
        if self.delete_me:
            self.cancel_tasks()
            await self.manager_event_bus.emit('remove_game_server',self)

    async def tail_game_log_then_close(self, wait=60):
        end_time = time.time() + wait
        old_size = 0
        while time.time() < end_time:
            # Find all files matching pattern
            files = glob.glob(os.path.join(self.global_config['hon_data']['hon_logs_directory'], f"Slave{self.id}_*.clog"))
            if not files:
                break

            # If files are found, sort them by modification time, and get the size of the most recent one
            if files:
                latest_file = max(files, key=os.path.getmtime)
                size = os.path.getsize(latest_file)
                if not old_size:
                    old_size = size
                else:
                    if size != old_size:
                        LOGGER.info("match in progress")
                        return

            # Sleep for a while before checking again
            await asyncio.sleep(1)

        # Close the tailing
        await self.stop_server_exe(disable=False)

    async def tail_game_log_then_close(self, wait=60):
        end_time = time.time() + wait
        old_size = 0
        while time.time() < end_time:
            # Find all files matching pattern
            files = glob.glob(os.path.join(self.global_config['hon_data']['hon_logs_directory'], f"Slave{self.id}_*.clog"))
            if not files:
                break

            # If files are found, sort them by modification time, and get the size of the most recent one
            if files:
                latest_file = max(files, key=os.path.getmtime)
                size = os.path.getsize(latest_file)
                if not old_size:
                    old_size = size
                else:
                    if size != old_size:
                        LOGGER.info("match in progress")
                        return

            # Sleep for a while before checking again
            await asyncio.sleep(1)

        # Close the tailing
        await self.stop_server_exe(disable=False)

    async def stop_server_exe(self, disable=True, delete=False, kill=False):
        if disable:
            self.disable_server()
            LOGGER.debug(f"GameServer #{self.id} - Disabled server")
        self.delete_me = delete
        if self._proc:
            LOGGER.debug(f"GameServer #{self.id} - Stopping server executable")
            if disable:
                self.disable_server()
            try:
                if kill:
                    self._proc.kill()
                else:
                    self._proc.terminate()
            except psutil.NoSuchProcess:
                pass # process doesn't exist, probably race condition of something else terminating it.
            self.started = False
            self.status_received.clear()
            self.unschedule_shutdown()
            self.stop_proxy()
            self.server_closed.set()
            self.reset_game_state()
        if self.delete_me:
            self.cancel_tasks()
            await self.manager_event_bus.emit('remove_game_server',self)
            LOGGER.debug(f"GameServer #{self.id} - Removed from game server list")

    async def get_running_server(self,timeout=15):
        """
            Check if existing hon server is running.
        """
        #running_procs = MISC.get_proc(self.config.local['config']['file_name'], slave_id = self.id)
        running_procs = [MISC.get_process_by_port(self.port)]
        if running_procs[0] == None:
            running_procs = []
        last_good_proc = None
        i=0
        while len(running_procs) > 0:
            i+=1
            last_good_proc = None
            for proc in running_procs[:]:
                status = self.get_dict_value('status')
                if status:
                    last_good_proc = proc
                else:
                    if not MISC.check_port(self.config.get_local_configuration()['params']['svr_proxyLocalVoicePort']) and not self.global_config['hon_data'].get('man_use_cowmaster'):
                        proc.terminate()
                        LOGGER.debug(f"Terminated GameServer #{self.id} as it has not started up correctly.")
                        running_procs.remove(proc)
                    else:
                        last_good_proc = proc
            if i >= timeout: break
            if last_good_proc is not None:
                break

        if last_good_proc:
            #   update the process information with the healthy instance PID. Healthy playercount is either -3 (off) or >= 0 (alive)
            self._pid = proc.pid
            self._proc = proc
            self._proc_hook = psutil.Process(pid=proc.pid)
            self._proc_owner = proc.username()
            LOGGER.debug(f"Found process ({self._pid}) for GameServer #{self.id}.")
            try:
                coro = self.start_proxy
                self.schedule_task(coro,'proxy_task', coro_bracket=True)
                return True
            except Exception:
                LOGGER.exception(f"GameServer #{self.id} {traceback.format_exc()}")
        else:
            return False

    async def set_server_priority_reduce(self):
        if not self._proc_hook:
            if not await self.get_running_server():
                LOGGER.warn(f"GameServer #{self.id} - Process not found")
                return
        if sys.platform == "win32":
            self._proc_hook.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            self._proc_hook.nice(20)
        LOGGER.info(f"GameServer #{self.id} - Priority set to Low.")

    async def set_server_priority_increase(self):
        if not self._proc_hook: # This code may not be required, since the "get_running_server" function is called from self.set_client_connection
            if not await self.get_running_server(): #
                LOGGER.warn(f"GameServer #{self.id} - Process not found") #
                return #
        if sys.platform == "win32":
            if self.global_config['hon_data']['svr_priority'] == "REALTIME":
                self._proc_hook.nice(psutil.REALTIME_PRIORITY_CLASS)
            else:
                self._proc_hook.nice(psutil.HIGH_PRIORITY_CLASS)
        else:
            self._proc_hook.nice(-19)
        LOGGER.info(f"GameServer #{self.id} - Priority set to {self.global_config['hon_data']['svr_priority']}.")

    async def create_proxy_config(self):
        config_filename = f"Config{self.id}"
        config_file_path = os.path.join(self.global_config['hon_data']['hon_artefacts_directory'] / "HoNProxyManager", config_filename)

        config_data = f"""redirectIP=127.0.0.1
publicip={self.config.local['params']['svr_ip']}
publicPort={self.config.local['params']['svr_proxyPort']}
redirectPort={self.config.local['params']['svr_port']}
voiceRedirectPort={self.config.local['params']['svr_proxyLocalVoicePort']}
voicePublicPort={self.config.local['params']['svr_proxyRemoteVoicePort']}
region=naeu
"""
        if exists(config_file_path):
            async with aiofiles.open(config_file_path, 'r') as existing_config_file:
                existing_config = await existing_config_file.read()
            if existing_config == config_data:
                return config_file_path, True

        os.makedirs(os.path.dirname(config_file_path), exist_ok=True)
        async with aiofiles.open(config_file_path, "w") as config_file:
            await config_file.write(config_data)
        return config_file_path, False

    async def start_proxy(self):    
        # Define a regular (non-async) function to handle subprocess creation:
        def run_proxy_subprocess(hon_install_directory, proxy_config_path):
            proxy_exe_path = hon_install_directory / "proxy.exe"
            process = subprocess.Popen(
                [proxy_exe_path, proxy_config_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.DETACHED_PROCESS,  # Detach the process from the console on Windows
            )
            return process
        
        if not self.config.local['params']['man_enableProxy']:
            return # proxy isn't enabled
        try:
            if MISC.get_os_platform() == "win32":
                pass
            elif MISC.get_os_platform() == "linux":
                raise HoNCompatibilityError("Using the proxy is currently not supported on Linux.")
            else:
                raise HoNCompatibilityError(f"Unknown OS: {MISC.get_os_platform()}. We cannot run the proxy.")
        except HoNCompatibilityError:
            LOGGER.warn(traceback.format_exc())
            LOGGER.warn(f"GameServer #{self.id} Setting the proxy to OFF.")
            self.config.local['params']['man_enableProxy'] = False
            return

        if not exists(self.global_config['hon_data']['hon_install_directory'] / "proxy.exe"):
            raise HoNInvalidServerBinaries(f"Missing proxy.exe. Please obtain proxy.exe from the wasserver package and copy it into {self.global_config['hon_data']['hon_install_directory']}. https://github.com/wasserver/wasserver")
        proxy_config_path, matches_existing = await self.create_proxy_config()

        if not matches_existing:
            # the config file has changed.
            if self._proxy_process:
                if self._proxy_process.is_running(): self._proxy_process.terminate()
                self._proxy_process = None

        if exists(f"{proxy_config_path}.pid"):
            async with aiofiles.open(f"{proxy_config_path}.pid", 'r') as proxy_pid_file:
                proxy_pid = await proxy_pid_file.read()
            try:
                proxy_pid = int(proxy_pid)
                process = psutil.Process(proxy_pid)
                # Check if the process command line matches the one you're using to start the proxy
                if proxy_config_path in " ".join(process.cmdline()):
                    self._proxy_process = process
                    LOGGER.debug(f"GameServer #{self.id} Proxy process found: {self._proxy_process}")
                else:
                    LOGGER.debug(f"GameServer #{self.id} Proxy pid found however the process description didn't match. Not the right PID, just a collision.")
                    self._proxy_process = None
            except psutil.NoSuchProcess:
                LOGGER.debug(f"GameServer #{self.id} Previous proxy process with PID {proxy_pid} was not found.")
                self._proxy_process = None
                self._proxy_process = MISC.find_process_by_cmdline_keyword(os.path.normpath(proxy_config_path), 'proxy.exe')
                if self._proxy_process: LOGGER.debug(f"GameServer #{self.id} Found existing proxy PID via a proxy process with a matching description.")
            except Exception:
                LOGGER.error(f"An error occurred while loading the PID from the last saved value: {proxy_pid}. {traceback.format_exc()}")
                self._proxy_process = MISC.find_process_by_cmdline_keyword(os.path.normpath(proxy_config_path), 'proxy.exe')
                if self._proxy_process: LOGGER.debug(f"GameServer #{self.id} Found existing proxy PID via a proxy process with a matching description.")

        while not stop_event.is_set() and self.enabled and self.config.local['params']['man_enableProxy']:
            if not self._proxy_process:
                if MISC.get_os_platform() == "win32":
                    try:
                        loop = asyncio.get_running_loop()
                        self._proxy_process = await loop.run_in_executor(
                            None,  # None uses the default executor
                            run_proxy_subprocess,
                            self.global_config['hon_data']['hon_install_directory'],
                            proxy_config_path,
                        )
                    except Exception:
                        LOGGER.error(f"GameServer #{self.id} - Failed to start proxy.exe: {traceback.format_exc()}")
                        self._proxy_process = None
                        await asyncio.sleep(10)
                        continue
                elif MISC.get_os_platform() == "linux":
                    # The code never gets here, because it raises an error for linux before this point.
                    # However, once proxy is supported, you can start it here
                    pass
                else: raise HoNCompatibilityError(f"The OS is unsupported for running honfigurator. OS: {MISC.get_os_platform()}")

                async with aiofiles.open(f"{proxy_config_path}.pid", 'w') as proxy_pid_file:
                    await proxy_pid_file.write(str(self._proxy_process.pid))
                await asyncio.sleep(0.1)
                self._proxy_process = psutil.Process(self._proxy_process.pid)

            # Monitor the process with psutil
            while not stop_event.is_set() and self._proxy_process and self._proxy_process.is_running() and self.enabled:
                await asyncio.sleep(1)  # Check every second

            if self.enabled:
                LOGGER.warn(f"proxy.exe (GameServer #{self.id}) crashed. Restarting...")
                if get_mqtt():
                    get_mqtt().publish_json("game_server/status",{"event_type":"proxy_crashed", **self.game_state._state})
                self._proxy_process = None

    def stop_proxy(self):
        if self._proxy_process:
            try:
                self._proxy_process.terminate()
            except psutil.NoSuchProcess: # it doesn't exist, that's fine
                pass

    async def monitor_process(self):
        LOGGER.debug(f"GameServer #{self.id} Process monitor started")
        try:
            while not stop_event.is_set():
                if self._proc is not None and self._proc_hook is not None:
                    try:
                        status = self._proc_hook.status()  # Get the status of the process
                    except psutil.NoSuchProcess:
                        status = 'stopped'
                    if status in ['zombie', 'stopped'] and self.enabled:  # If the process is defunct or stopped. a "suspended" process will also show as stopped on windows.
                        LOGGER.warn(f"GameServer #{self.id} stopped unexpectedly. (Process ID: {self._proc_hook.pid})")
                        self._proc = None  # Reset the process reference
                        self._proc_hook = None  # Reset the process hook reference
                        self._pid = None
                        self._proc_owner = None
                        self.started = False
                        self.server_closed.set()  # Set the server_closed event
                        if get_mqtt():
                            get_mqtt().publish_json("game_server/status",{"event_type":"server_crashed", **self.game_state._state})
                        if self.get_dict_value('game_phase') in [GamePhase.BANNING_PHASE.value, GamePhase.GAME_ENDING.value, GamePhase.LOADING_INTO_MATCH.value, GamePhase.MATCH_STARTED, GamePhase.PREPERATION_PHASE.value, GamePhase.PICKING_PHASE.value]:
                            LOGGER.warn(f"GameServer #{self.id} crashed while in a match. Restarting server...")
                            await self.manager_event_bus.emit(
                                'notify_discord_admin', 
                                type='crash',
                                time_of_crash=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                instance=self.id,
                                server_name=self.global_config['hon_data']['svr_name'],
                                match_id=self.get_dict_value('current_match_id'),
                                game_phase=GamePhase(self.get_dict_value('game_phase')).name
                            )
                        self.reset_game_state()
                        # the below intentionally does not use self.schedule_task. The manager ends up creating the task.
                        asyncio.create_task(self.manager_event_bus.emit('start_game_servers', [self], service_recovery=False))  # restart the server
                    elif status != 'zombie' and not self.enabled and not self.scheduled_shutdown:
                        #   Schedule a shutdown, otherwise if shutdown is already scheduled, skip over
                        self.schedule_shutdown()

                for _ in range(5):  # Monitor process every 5 seconds
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            LOGGER.debug(f"GameServer #{self.id} Process monitor cancelled")
            # Propagate the cancellation
            raise
        except Exception as e:
            LOGGER.error(f"GameServer #{self.id} Unexpected error in monitor_process: {e}")

    async def heartbeat(self):
        while not stop_event.is_set():
            if self.game_state._state['match_started'] == 0:
                sleep = 60
            else:
                sleep = 20

            # Introduce jitter: sleep for a random duration between 0 to 10 seconds
            jitter = random.uniform(0, 10)
            await asyncio.sleep(jitter)
            
            for _ in range(sleep):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            if get_mqtt():
                get_mqtt().publish_json("game_server/status", {"event_type":"heartbeat", **self.game_state._state})

    def enable_server(self):
        self.enabled = True

    def disable_server(self):
        self.enabled = False

    def schedule_shutdown(self, delete=False):
        self.scheduled_shutdown = True
        # self.delete_me = delete

    def unschedule_shutdown(self):
        self.scheduled_shutdown = False
        # self.delete_me = False
import asyncio

class GameState:
    def __init__(self, id, local_config):
        self._state = {}
        self._performance = {}
        self._listeners = []
        self.id = id
        self.local_config = local_config

    def __getitem__(self, key, dict_to_check="state"):
        target_dict = self._state if dict_to_check == "state" else self._performance
        return target_dict[key]

    def __setitem__(self, key, value, dict_to_check="state"):
        old_value = None
        try:
            old_value = self._state[key]
        except KeyError: # most likely, the game state is just being initialised, so there is no old value
            pass
        if dict_to_check == "state":
            self._state[key] = value
        else:
            self._performance[key] = value
        self._emit_event(key, value, old_value)

    def get_full_key(self, key, current_level, level=None, path=None, dict_to_check="state"):
        if level is None:
            level = self._state if dict_to_check == "state" else self._performance

        if path is None:
            path = []

        if level is current_level:
            path.append(key)
            return ".".join(path)

        for k, v in level.items():
            if isinstance(v, dict):
                new_path = path.copy()
                new_path.append(k)
                result = self.get_full_key(key, current_level, v, new_path, dict_to_check)
                if result:
                    return result

        return None

    def update(self, data, current_level=None, dict_to_check="state"):
        monitored_keys = ["match_started", "match_info.mode", "game_phase", "players", "status"]

        if current_level is None:
            current_level = self._state if dict_to_check == "state" else self._performance

        target_dict = self._state if dict_to_check == "state" else self._performance

        for key, value in data.items():
            if isinstance(value, dict):
                if key not in current_level:
                    current_level[key] = {}
                self.update(value, current_level[key], dict_to_check)
            else:
                full_key = self.get_full_key(key, current_level, dict_to_check=dict_to_check)
                if full_key in monitored_keys and (full_key not in target_dict or self.__getitem__(full_key, dict_to_check) != value):
                    self.__setitem__(full_key, value, dict_to_check)
                else:
                    current_level[key] = value

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _emit_event(self, key, value, old_value):
        for listener in self._listeners:
            asyncio.create_task(listener(key, value, old_value))

    def clear(self, dict_to_check=None):
        if dict_to_check is None or dict_to_check == "state":
            self.update({
                'instance_id':self.id,
                'instance_name': self.local_config['name'],
                'local_game_port': self.local_config['params']['svr_port'],
                'remote_game_port': self.local_config['params']['svr_proxyPort'],
                'local_voice_port': self.local_config['params']['svr_proxyLocalVoicePort'],
                'remote_voice_port': self.local_config['params']['svr_proxyRemoteVoicePort'],
                'proxy_enabled': self.local_config['params']['man_enableProxy'],
                'svr_affinity': self.local_config['params']['host_affinity'],
                'status': -1,
                'uptime': 0,
                'num_clients': 0,
                'match_started': 0,
                'game_phase': -1,
                'current_match_id': 0,
                'players': [],
                'match_info':{
                    'map':None,
                    'mode':None,
                    'name':None,
                    'match_id':None,
                    'start_time': 0,
                    'duration':0
                }
            }, dict_to_check="state")
        if dict_to_check is None or dict_to_check == "performance":
            self.update({
                "now_ingame_skipped_frames": 0,
                "total_ingame_skipped_frames": 0,
                "monitored_skipped_frames": 0,
                'skipped_frames_detailed': {}
            }, dict_to_check="performance")