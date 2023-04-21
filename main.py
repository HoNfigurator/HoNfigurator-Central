#!/usr/bin/env python3
import traceback, sys, os
import threading
import asyncio
from pathlib import Path

#   This must be first, to initialise logging which all other classes rely on.
from cogs.misc.logging import get_script_dir,get_logger,set_logger,set_home,print_formatted_text,set_misc
HOME_PATH = Path(get_script_dir(__file__))
set_home(HOME_PATH)
set_logger()

from cogs.misc.utilities import Misc
MISC = Misc()
set_misc(MISC)

from cogs.handlers.events import stop_event
from cogs.misc.exceptions import ServerConnectionError, AuthenticationError, ConfigError
from cogs.misc.setup import SetupEnvironment, PrepareDependencies
from cogs.game.game_server_manager import GameServerManager
from cogs.misc.scheduled_tasks import HonfiguratorSchedule, run_continuously

LOGGER = get_logger()
CONFIG_FILE = HOME_PATH / 'config' / 'config.json'

def show_exception_and_exit(exc_type, exc_value, tb):
    """
        Exception hook to catch any errors and prevent the window from closing
    """
    traceback.print_exception(exc_type, exc_value, tb)
    raw_input = input(f"Due to the above error, HoNfigurator has failed to launch.")
    sys.exit()
sys.excepthook = show_exception_and_exit

async def main():

    if sys.platform == "linux":
        if os.getuid() != 0:
            print("---- IMPORTANT ----")
            print("You have to run it as root (at the moment)")
            print("Reason is the priority setting on the game instances.")
            print("---- IMPORTANT ----")
            return

    requirements_check = PrepareDependencies()
    requirements_check.update_dependencies()

    setup = SetupEnvironment(CONFIG_FILE)
    config = setup.check_configuration()
    if config:
        global_config = setup.get_final_configuration()
    else:
        LOGGER.exception(f"{traceback.format_exc()}")
        raise ConfigError(f"There are unresolved issues in the configuration file. Please address these manually in {CONFIG_FILE}")

    # run scheduler
    stop_run_continuously = run_continuously()

    host = "127.0.0.1"
    game_server_to_mgr_port = global_config['hon_data']['svr_managerPort']
    udp_ping_responder_port = global_config['hon_data']['svr_starting_gamePort'] - 1

    # instantiate the manager
    game_server_manager = GameServerManager(global_config)
    # Print configuration overview
    print_formatted_text("\nConfiguration Overview")
    for key,value in global_config['hon_data'].items():
        if key == "svr_password": print_formatted_text(f"\t{key}: ***********")
        else: print_formatted_text(f"\t{key}: {value}")

    # create tasks for authenticating to master server, starting game server listener, auto pinger, and starting game server instances.
    try:
        try:
            auth_task = game_server_manager.create_handle_connections_task(udp_ping_responder_port)
        except AuthenticationError as e:
            LOGGER.exception(f"{traceback.format_exc()}")
        except ServerConnectionError as e:
            LOGGER.exception(f"{traceback.format_exc()}")
        api_task = game_server_manager.start_api_server()
        game_server_listener_task = game_server_manager.start_game_server_listener_task(host, game_server_to_mgr_port)
        auto_ping_listener_task = game_server_manager.start_autoping_listener_task(udp_ping_responder_port)

        start_task = game_server_manager.start_game_servers_task("all")

        stop_task = asyncio.create_task(stop_event.wait())
        LOGGER.info("Received stop task")

        done, pending = await asyncio.wait(
            [auth_task, api_task, game_server_listener_task, auto_ping_listener_task, start_task, stop_task]
        )
        for task in pending:
            LOGGER.warning(f"Task: {task} needs to be shut down by force..")
            task.cancel()

    except asyncio.CancelledError:
        LOGGER.info("Tasks cancelled due to stop_event being set.")
    finally:
        LOGGER.info("Stopping background job for scheduler")
        stop_run_continuously.set()
        LOGGER.info("Everything shut. Good bye!")
        LOGGER.info("You can CTRL + C now..")
        return


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.warning("KeyBoardInterrupt: Manager shutting down...")
        stop_event.set()
