import traceback
import sys
import code
def show_exception_and_exit(exc_type, exc_value, tb):
    """
        Exception hook to catch any errors and prevent the window from closing
    """
    traceback.print_exception(exc_type, exc_value, tb)
    raw_input = input(f"Due to the above error, HoNfigurator has failed to launch.")
    sys.exit()
# sys.excepthook = show_exception_and_exit

#import cogs.db_broker as db_broker
import os,psutil,subprocess,ctypes,json,time,cogs.behemothHeart as heart,asyncio,cogs.data_handler as data_handler,cogs.server_controller as GameServer_Controller
from threading import Thread
from concurrent.futures import ProcessPoolExecutor
from columnar import columnar
from enum import Enum
from cogs import socket_lsnr4

# check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if not is_admin():
    raise PermissionError("Please launch as administrator.")

class HealthChecks(Enum):
    """
        Define some health check Enums
    """
    public_ip_healthcheck = 1
    general_healthcheck = 2
    lag_healthcheck = 3

def choose_health_check(type):
    for health_check in HealthChecks:
        if type.lower() == health_check.name.lower():
            return health_check
    # TODO: Return error? no matching health check, log it out or test what happens
    return None

class Manager:
    def __init__(self):
        self.servers = {}
        self.healthcheck_timers = {}
        self.healthcheck_timers.update(gbl_config['application_data']['timers']['manager']['health_checks'])
        return
    def register(self,id):
        self.servers.update({id:GameServer(id)})
    def register_all(self):
        for id in range (1,gbl_config['hon_data']['server_total']+1):
            self.register(id)
    def start(self):
        return
    async def start_all(self):
        tasks = []
        for server in self.servers.values():
            tasks.append(asyncio.create_task(server.game_server_control.start_server()))
            tasks.append(asyncio.create_task(server.heartbeat()))
        return tasks
    def stop(self):
        self.server = GameServer(self.id)
        return
    async def get_status(self):
        server_lines = [['Manager',self.healthcheck_timers,'','']]
        for server in self.servers.values():
            await server.get_status()
            server_lines.append([server.id,server.healthcheck_timers,server.game_server_control.get_player_count(),await server.game_server_control.get_state()])
        headers = ['Server', 'Time Until HealthCheck', 'Players', 'Status']
        table = columnar(server_lines, headers, no_borders=True)
        print(table)
    async def interactive_shell(self):
        while True:
            choice = input(">")
            if choice.lower() == "status": await self.get_status()
    async def master_poller(self):
        while True:
            await asyncio.sleep(gbl_config['application_data']['timers']['manager']['heartbeat_frequency'])
            for timer in self.healthcheck_timers:
                self.healthcheck_timers[timer] -= gbl_config['application_data']['timers']['manager']['heartbeat_frequency']
                if self.healthcheck_timers[timer] <= 0:
                    self.healthcheck_timers[timer] = gbl_config['application_data']['timers']['manager']['health_checks'][timer]
                    print(f"[Manager] performing health check: {timer}")
                    self.run_health_checks(choose_health_check(timer))
    async def my_async_function(self):
        """An asynchronous function that prints a message every second."""
        while True:
            print("Hello, world!")
            await asyncio.sleep(1)
    async def start_async_thread(self):
        """Start a new thread that runs an async event loop."""
        await asyncio.to_thread(self.run_async_function)
    def run_async_function(self):
        """Run the my_async_function() coroutine in an event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.interactive_shell())
    def run_health_checks(self,type):
        if type == HealthChecks.public_ip_healthcheck:
            print("checking public IP")


class GameServer:
    def __init__(self,id):
        self.id = id
        self.set_configuration()
        self.set_controller()
        self.status = {
            'now':'pending'
        }
        self.healthcheck_timers = {}
        self.healthcheck_timers.update(gbl_config['application_data']['timers']['game_server']['health_checks'])
    def start(self):
        """
            Take a GameServer dictionary, and spawn a GameServer Object?
        """
        self.game_server_control.start_server()
    async def heartbeat(self):
        try:
            self.game_server_control.get_current_match_id()
        except Exception: print(traceback.format_exc())
        while True:
            await asyncio.sleep(gbl_config['application_data']['timers']['game_server']['heartbeat_frequency'])
            for timer in self.healthcheck_timers:
                self.healthcheck_timers[timer] -= gbl_config['application_data']['timers']['game_server']['heartbeat_frequency']
                if self.healthcheck_timers[timer] <= 0:
                    self.healthcheck_timers[timer] = gbl_config['application_data']['timers']['game_server']['health_checks'][timer]
                    print(f"[Game Server {self.id}] performing health check: {timer}")
                    self.run_health_checks(choose_health_check(timer))
            try:
                self.player_count = self.game_server_control.get_player_count()
            except Exception: print(traceback.format_exc())
    def get_player_count(self):
        return self.game_server_control.get_player_count()
    async def get_status(self):
        await self.game_server_control.get_running_server()
    def set_heartbeat(self):
        self.heart = heart.heartbeat(self)
    def set_configuration(self):
        self.config = data_handler.ConfigManagement(self.id)
    def set_controller(self):
        self.game_server_control = GameServer_Controller.honCMD(self.id)
        self.game_server_control.set_global_config(gbl_config)
        self.game_server_control.set_local_config(self.config.get_local_configuration())
    def run_health_checks(self,type):
        if type == HealthChecks.lag_healthcheck:
            return
        elif type == HealthChecks.general_healthcheck:
            return

async def main():
    global gbl_config

    gbl_config = data_handler.global_config

    manager = Manager()
    manager.register_all()
    tasks = await manager.start_all()
    tasks.append(asyncio.create_task(manager.master_poller()))
    await manager.start_async_thread()
    

if __name__ == "__main__":
    game_servers = {}
    tasks = []
    threads = []
    asyncio.run(main())