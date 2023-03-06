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

# check if running as admin
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

if not is_admin():
    raise PermissionError("Please launch as administrator.")

class Monitor():
    def __init__(self):
        return
    def poll(self,):
        while True:
            time.sleep(10)
    async def start(self):
        while True:
            print("=================================================")
            lines = []
            for k in game_servers:
                lines.append([game_servers[k].id,game_servers[k].heart.timer,game_servers[k].game_server_control.get_player_count()])
                print(f"[Server {game_servers[k].id}] Players: {game_servers[k].heart.timer}")

            headers = ['Server', 'Healthcheck', 'Player Count', 'Status']
            table = columnar(lines, headers, no_borders=True)
            print(table)

            await asyncio.sleep(2)

all_servers = {}
class Manager:
    def __init__(self):
        self.servers = {}
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
            tasks.append(asyncio.create_task(server.heart.start_heart()))
        return tasks
    def stop(self):
        self.server = GameServer(self.id)
        return
    async def get_status(self):
        lines = []
        for server in self.servers.values():
            await server.get_status()
            lines.append([server.id,server.heart.timer,server.game_server_control.get_player_count(),server.status['now']])
        headers = ['Server', 'Healthcheck', 'Player Count', 'Status']
        table = columnar(lines, headers, no_borders=True)
        print(table)
    async def interactive_shell(self):
        while True:
            choice = input(">")
            if choice.lower() == "status": await self.get_status()
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

class GameServer():
    def __init__(self,id):
        self.id = id
        self.set_configuration()
        self.set_controller()
        self.set_heartbeat()
        self.status = {
            'now':'pending'
        }
        print(self.config.get_local_configuration())
    def start(self):
        """
            Take a GameServer dictionary, and spawn a GameServer Object?
        """
        self.game_server_control.start_server()
    async def heartbeat(self):
        self.heart = heart.heartbeat()
        self.heart.set_server_config(self.data)
        await self.heart.start_heart()
        #self.monitor()
    def get_player_count(self):
        return self.game_server_control.get_player_count()
    async def get_status(self):
        await self.game_server_control.get_running_server()
    def set_heartbeat(self):
        self.heart = heart.heartbeat(self)
    def set_configuration(self):
        self.config = data_handler.ConfigManagement(self.id)
    def set_controller(self):
        self.game_server_control = GameServer_Controller.honCMD(self)
        # self.game_server_control.set_server_id(self.id)
        # self.game_server_control.set_server_config(self.data)
        # self.game_server_control.set_global_config(config.get_global_configuration())

    async def monitor(self):
        asyncio.create_task(self.heart.start_heart())
        while True:
            await asyncio.sleep(5)
            print(f"{self.id}: {self.heart.get_poll_interval()}")

class Poll(GameServer):
    def __init__():
        return

async def main():
    global gbl_config

    gbl_config = data_handler.global_config

    manager = Manager()
    manager.register_all()
    tasks = await manager.start_all()
    #tasks.append(asyncio.create_task(manager.interactive_shell()))
    #await asyncio.gather(*tasks)
    await manager.start_async_thread()
    # for t in tasks:
    #     await asyncio.gather(t)
    

if __name__ == "__main__":
    game_servers = {}
    tasks = []
    threads = []
    asyncio.run(main())




    #   wait for threads to close
    # if len(threads) > 0:
    #     for t in threads:
    #         t.join()
    #   all GameServers are down. Idle
    # while True:
    #     print("idling!")