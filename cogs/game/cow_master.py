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
        self.reset_cowmaster_state()
        self.game_state.add_listener(self.on_game_state_change)
    
    async def fork_new_server(self, game_server):
        if not self.client_connection:
            LOGGER.warn("CowMaster - Not yet established connection to manager.")
            return
        await self.client_connection.send_packet(game_server.get_fork_bytes(), send_len=True)

    async def start_cow_master(self):
        """
            Linux only feature, the cow master is used to preload resources for each available map type.
            The cow master can then be commanded to "fork" new game servers, off existing resources and RAM.
            This results in instant server startup times and some significantly less RAM usage overall 
        """
        cmdline_args = MISC.build_commandline_args(self.cowmaster_cmdline, self.global_config, cowmaster = True)
        exe = subprocess.Popen(cmdline_args,close_fds=True,start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        self._pid = exe.pid
        self._proc_hook = psutil.Process(pid=self._pid)

    def stop_cow_master(self):
        self._proc_hook.terminate()
    
    async def set_client_connection(self, client_connection):
        LOGGER.highlight("CowMaster - Connected to manager.")
        self.client_connection = client_connection

    async def on_game_state_change(self, key, value):
        # do things
        pass

    def get_port(self):
        return self.port
    
    def reset_cowmaster_state(self):
        LOGGER.debug(f"CowMaster #{self.id} - Reset state")
        self.status_received.clear()
        self.game_state.clear()