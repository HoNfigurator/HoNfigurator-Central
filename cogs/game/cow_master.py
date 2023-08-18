import subprocess
import psutil
import asyncio
import os

from cogs.handlers.data_handler import get_cowmaster_configuration
from cogs.misc.logger import get_logger, get_misc
from cogs.handlers.events import stop_event
from cogs.game.game_server import GameState
from cogs.TCP.packet_parser import GameManagerParser

LOGGER = get_logger()
MISC = get_misc()

class CowMaster:
    def __init__(self, port, global_config):
        self.port = port
        self.id = 0
        self.global_config = global_config

        self.client_connection = None
        self.cowmaster_cmdline = get_cowmaster_configuration(self.global_config.get("hon_data"))

        self.game_manager_parser = GameManagerParser(self.id)
        
        # state variables
        self._started = None
        self._pid = None
        self._proc_hook = None
        self.status_received = asyncio.Event()

        self.game_state = GameState()
        self.reset_game_state()
        self.game_state.add_listener(self.on_game_state_change)
    
    async def fork_new_server(self, game_server):
        if not self.client_connection:
            LOGGER.warn("CowMaster - Not yet established connection to manager.")
            return
        await self.client_connection.send_packet(game_server.get_fork_bytes(), send_len=True)

    async def start_cow_master(self):
        cmdline_args = MISC.build_commandline_args(self.cowmaster_cmdline, self.global_config, cowmaster = True)
        os.environ["APPDATA"] = str(self.global_config['hon_data']['hon_artefacts_directory'])
        os.environ["USERPROFILE"] = str(self.global_config['hon_data']['hon_home_directory'])
        DETACHED_PROCESS = 0x00000008
        exe = subprocess.Popen(cmdline_args,close_fds=True, creationflags=DETACHED_PROCESS)

        self._pid = exe.pid
        self._proc_hook = psutil.Process(pid=self._pid)

    def stop_cow_master(self):
        self._proc_hook.terminate()
    
    def set_client_connection(self, client_connection):
        LOGGER.highlight("CowMaster - Connected to manager.")
        self.client_connection = client_connection

    async def on_game_state_change(self, key, value):
        # do things
        pass

    def get_port(self):
        return self.port

    def reset_game_state(self):
        LOGGER.debug(f"GameServer #{self.id} - Reset state")
        self.status_received.clear()
        self.game_state.clear()
        self.game_in_progress = False