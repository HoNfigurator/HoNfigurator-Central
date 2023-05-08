#!/usr/bin/env python3
import traceback, sys, os
import time
from os.path import isfile
from pathlib import Path

MISC = None
HOME_PATH = None

def show_exception_and_exit(exc_type, exc_value, tb):
    """
        Exception hook to catch any errors and prevent the window from closing
    """
    traceback.print_exception(exc_type, exc_value, tb)
    if MISC and HOME_PATH:
        if isfile(HOME_PATH / "logs" / ".last_working_branch"):
            with open(HOME_PATH / "logs" / ".last_working_branch", 'r') as f:
                last_working_branch = f.read()
            if MISC.get_current_branch_name() != last_working_branch:
                LOGGER.warn(f"Reverting back to last known working branch ({last_working_branch}).")
                MISC.change_branch(last_working_branch)
            else:
                while True:
                    LOGGER.warn("Attempting to update current repository to a newer version.")
                    # LOGGER.warn("If this has happened without warning, then @FrankTheGodDamnMotherFuckenTank#8426 has probably released a bad update and it will be reverted automatically shortly. Standby.")
                    MISC.update_github_repository()
                    time.sleep(30)
    raw_input = input(f"Due to the above error, HoNfigurator has failed to launch.")
    sys.exit()

sys.excepthook = show_exception_and_exit

HOME_PATH = Path(os.path.dirname(os.path.abspath(__file__)))

# set up dependencies first
from cogs.misc.dependencies_check import PrepareDependencies
requirements_check = PrepareDependencies(HOME_PATH)
requirements_check.update_dependencies()

import asyncio
import argparse

#   This must be first, to initialise logging which all other classes rely on.
from cogs.misc.logger import get_script_dir,get_logger,set_logger,set_home,print_formatted_text,set_misc,set_setup
set_home(HOME_PATH)
set_logger()

from cogs.misc.utilities import Misc
MISC = Misc()
set_misc(MISC)

from cogs.misc.setup import SetupEnvironment
CONFIG_FILE = HOME_PATH / 'config' / 'config.json'
setup = SetupEnvironment(CONFIG_FILE)
set_setup(setup)

from cogs.handlers.events import stop_event
from cogs.misc.exceptions import HoNServerConnectionError, HoNAuthenticationError, HoNConfigError
from cogs.game.game_server_manager import GameServerManager
from cogs.misc.scheduled_tasks import HonfiguratorSchedule, run_continuously

LOGGER = get_logger()

def parse_arguments():
    parser = argparse.ArgumentParser(description="HoNfigurator API and Server Manager")
    parser.add_argument("-hondir", "--hon_install_directory", type=str, help="Path to the HoN install directory")
    # Add other arguments here
    return parser.parse_args()

async def main():

    if sys.platform == "linux":
        if os.getuid() != 0:
            print("---- IMPORTANT ----")
            print("You have to run it as root (at the moment)")
            print("Reason is the priority setting on the game instances.")
            print("---- IMPORTANT ----")
            return

    config = setup.check_configuration(args)
    if config:
        global_config = setup.get_final_configuration()
    else:
        LOGGER.exception(f"{traceback.format_exc()}")
        raise HoNConfigError(f"There are unresolved issues in the configuration file. Please address these manually in {CONFIG_FILE}")
    # check for other HoNfigurator instances.
    check_existing_proc = MISC.get_process_by_port(global_config['hon_data']['svr_managerPort'])
    if check_existing_proc:
        check_existing_proc.terminate()

    # run scheduler
    jobs = HonfiguratorSchedule(global_config)
    jobs.setup_tasks()
    stop_run_continuously = run_continuously()

    host = "127.0.0.1"
    game_server_to_mgr_port = global_config['hon_data']['svr_managerPort']
    udp_ping_responder_port = global_config['hon_data']['svr_starting_gamePort'] - 1

    # instantiate the manager
    game_server_manager = GameServerManager(global_config, setup)
    # Print configuration overview
    print_formatted_text("\nConfiguration Overview")
    for key,value in global_config['hon_data'].items():
        if key == "svr_password": print_formatted_text(f"\t{key}: ***********")
        else: print_formatted_text(f"\t{key}: {value}")

    # create tasks for authenticating to master server, starting game server listener, auto pinger, and starting game server instances.
    try:
        try:
            auth_task = game_server_manager.create_handle_connections_task(udp_ping_responder_port)
        except HoNAuthenticationError as e:
            LOGGER.exception(f"{traceback.format_exc()}")
        except HoNServerConnectionError as e:
            LOGGER.exception(f"{traceback.format_exc()}")
        api_task = game_server_manager.start_api_server()
        game_server_listener_task = game_server_manager.start_game_server_listener_task(host, game_server_to_mgr_port)
        auto_ping_listener_task = game_server_manager.start_autoping_listener_task(udp_ping_responder_port)

        start_task = game_server_manager.start_game_servers_task("all")

        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            [auth_task, api_task, start_task, game_server_listener_task, auto_ping_listener_task, stop_task]
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
        args = parse_arguments()
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.warning("KeyBoardInterrupt: Manager shutting down...")
        stop_event.set()
