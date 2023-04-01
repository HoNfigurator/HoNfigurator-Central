#   This must be first, to initialise logging which all other classes rely on.
from cogs.misc.logging import get_script_dir,get_logger,set_logger,set_home,print_formatted_text
HOME_PATH = get_script_dir(__file__)
set_home(HOME_PATH)
set_logger()


import cogs.handlers.data_handler as data_handler
import traceback, sys, os.path
import asyncio
from cogs.misc.exceptions import ServerConnectionError, AuthenticationError, ConfigError
from cogs.misc.setup import SetupEnvironment, PrepareDependencies
from cogs.game.game_server_manager import GameServerManager

LOGGER = get_logger()
CONFIG_FILE = f"{HOME_PATH}\\config\\config.json"

def show_exception_and_exit(exc_type, exc_value, tb):
    """
        Exception hook to catch any errors and prevent the window from closing
    """
    traceback.print_exception(exc_type, exc_value, tb)
    raw_input = input(f"Due to the above error, HoNfigurator has failed to launch.")
    sys.exit()
sys.excepthook = show_exception_and_exit

async def main():

    requirements_check = PrepareDependencies()
    requirements_check.update_dependencies()

    setup = SetupEnvironment(CONFIG_FILE)
    config = setup.check_configuration()
    if config:
        global_config = setup.get_final_configuration()
    else:
        LOGGER.exception(f"{traceback.format_exc()}")
        raise ConfigError(f"There are unresolved issues in the configuration file. Please address these manually in {CONFIG_FILE}")


    #global_config = data_handler.get_global_configuration(CONFIG_FILE)

    host = "127.0.0.1"
    game_server_to_mgr_port = 1135
    # TODO: Put this back to -1 when done
    udp_ping_responder_port = global_config['hon_data']['svr_starting_gamePort'] - 2

    # launch game servers
    game_server_manager = GameServerManager(global_config)

    try:
        auth_task = asyncio.create_task(game_server_manager.authenticate_to_masterserver(udp_ping_responder_port))
    except AuthenticationError as e:
        LOGGER.exception(f"{traceback.format_exc()}")
    except ServerConnectionError as e:
        LOGGER.exception(f"{traceback.format_exc()}")

    #   Start listeners
    game_server_listener_task = asyncio.create_task(game_server_manager.start_game_server_listener(host,game_server_to_mgr_port))
    auto_ping_listener_task = asyncio.create_task(game_server_manager.start_autoping_listener(udp_ping_responder_port))

    #   Print config overview
    print_formatted_text("\nConfiguration Overview")
    for key,value in global_config['hon_data'].items():
        if key == "svr_password": print_formatted_text(f"\t{key}: ***********")
        else: print_formatted_text(f"\t{key}: {value}")

    #   Start GameServers
    start_task = asyncio.create_task(game_server_manager.start_game_servers())

    await asyncio.gather(auth_task, game_server_listener_task, auto_ping_listener_task, start_task)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("KeyBoardInterrupt: Manager shutting down...")
