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
        self.enabled = False

        self.client_connection = None
        self.cowmaster_cmdline = get_cowmaster_configuration(self.global_config.get("hon_data"))

        self.game_manager_parser = GameManagerParser(self.id, logger = LOGGER)
        
        # state variables
        self._started = None
        self._pid = None
        self._proc_hook = None
        self.status_received = asyncio.Event()

        self.game_state = GameState()
        self.reset_cowmaster_state()
        self.game_state.add_listener(self.on_game_state_change)

        asyncio.create_task(self.monitor_process())
    
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
        self.enabled = True

    def stop_cow_master(self, disable=True):
        if self._proc_hook:
            self._proc_hook.terminate()
            self.enabled = disable
            self._pid = None
            self._proc_hook = None
    
    async def set_client_connection(self, client_connection):
        LOGGER.highlight("CowMaster - Connected to manager.")
        self.client_connection = client_connection
        self._proc_hook = MISC.get_client_pid_by_tcp_source_port(self.global_config['hon_data']['svr_managerPort'], client_connection.addr[1])
        self._pid = self._proc_hook.pid
    
    def unset_client_connection(self):
        self.client_connection = None
        self._pid = None
        self._proc_hook = None

    async def on_game_state_change(self, key, value):
        # do things
        pass

    def get_port(self):
        return self.port
    
    def reset_cowmaster_state(self):
        LOGGER.debug(f"CowMaster - Reset state")
        self.status_received.clear()
        self.game_state.clear()
    
    async def monitor_process(self):
        LOGGER.debug(f"CowMaster - Process monitor started")
        try:
            while not stop_event.is_set():
                if self._proc_hook is not None:
                    try:
                        status = self._proc_hook.status()  # Get the status of the process
                    except psutil.NoSuchProcess:
                        status = 'stopped'
                    if status in ['zombie', 'stopped'] and self.enabled:  # If the process is defunct or stopped. a "suspended" process will also show as stopped on windows.
                        LOGGER.warn(f"CowMaster stopped unexpectedly")
                        self._proc_hook = None  # Reset the process hook reference
                        self._pid = None
                        self._proc_owner = None
                        self.reset_cowmaster_state()
                        # the below intentionally does not use self.schedule_task. The manager ends up creating the task.
                        await self.start_cow_master()
                    elif status != 'zombie' and not self.enabled:
                        #   Schedule a shutdown, otherwise if shutdown is already scheduled, skip over
                        self.stop_cow_master()

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