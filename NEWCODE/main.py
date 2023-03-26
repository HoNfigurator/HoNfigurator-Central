import asyncio
from game_server_manager import GameServerManager
from cogs.exceptions import ServerConnectionError, AuthenticationError
from cogs.custom_print import my_print, logger
import traceback, sys
import cogs.data_handler as data_handler


def show_exception_and_exit(exc_type, exc_value, tb):
    """
        Exception hook to catch any errors and prevent the window from closing
    """
    traceback.print_exception(exc_type, exc_value, tb)
    raw_input = input(f"Due to the above error, HoNfigurator has failed to launch.")
    sys.exit()
# sys.excepthook = show_exception_and_exit

async def main():

    host = "127.0.0.1"
    game_server_to_mgr_port = 1135
    udp_ping_responder_port = 9999
    
    global_config = data_handler.get_global_configuration()
    # launch game servers
    game_server_manager = GameServerManager(global_config)

    try:
        auth_task = asyncio.create_task(game_server_manager.authenticate_to_masterserver(udp_ping_responder_port))
    except AuthenticationError as e:
        print(str(e))
        logger.error(e)
    except ServerConnectionError as e:
        print(str(e))
        logger.error(e)

    listener_task = asyncio.create_task(game_server_manager.start_game_server_listener(host,game_server_to_mgr_port))
    start_task = asyncio.create_task(game_server_manager.start_game_servers())

    await asyncio.gather(auth_task, listener_task, start_task)
    
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        my_print("Server shutting down...")