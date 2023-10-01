#!/usr/bin/env python3
import traceback, sys, os
import time
from os.path import isfile
from pathlib import Path
import subprocess

os.system('')

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
                formatted_exception = "".join(traceback.format_exception(exc_type, exc_value, tb))
                while True:
                    LOGGER.warn(f"Attempting to update current repository to a newer version. This is because of the following error\n{formatted_exception}")
                    # LOGGER.warn("If this has happened without warning, then @FrankTheGodDamnMotherFuckenTank#8426 has probably released a bad update and it will be reverted automatically shortly. Standby.")
                    MISC.update_github_repository()
                    for i in range(30):
                        if stop_event.is_set():
                            return
                        time.sleep(1)
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
from cogs.misc.logger import get_logger,set_logger,set_home,print_formatted_text,set_misc,set_setup,set_mqtt,get_mqtt
set_home(HOME_PATH)
set_logger()

from cogs.misc.utilities import Misc
MISC = Misc()
set_misc(MISC)

# check for update at launch
MISC.update_github_repository()

from cogs.misc.setup import SetupEnvironment
CONFIG_FILE = HOME_PATH / 'config' / 'config.json'
setup = SetupEnvironment(CONFIG_FILE)
set_setup(setup)

from cogs.handlers.events import stop_event
from cogs.misc.exceptions import HoNConfigError
from cogs.game.game_server_manager import GameServerManager
from cogs.misc.scheduled_tasks import HonfiguratorSchedule
from cogs.handlers.mqtt import MQTTHandler

LOGGER = get_logger()

def parse_arguments():
    parser = argparse.ArgumentParser(description="HoNfigurator API and Server Manager")
    parser.add_argument("-hondir", "--hon_install_directory", type=str, help="Path to the HoN install directory")
    # Add other arguments here
    return parser.parse_args()

async def main():
    if sys.platform == "linux":
        if os.getuid() != 0:
            LOGGER.warn("---- IMPORTANT ----\nYou have to run it as root (at the moment)\nReason is the priority setting on the game instances.\n---- IMPORTANT ----")
            return

    config = setup.check_configuration(args)
    if config:
        global_config = setup.get_final_configuration()
    else:
        LOGGER.exception(f"{traceback.format_exc()}")
        raise HoNConfigError(f"There are unresolved issues in the configuration file. Please address these manually in {CONFIG_FILE}")
    # check for other HoNfigurator instances.
    check_existing_proc = MISC.get_process_by_port(global_config['hon_data']['svr_managerPort'], protocol='tcp4')
    if check_existing_proc:
        LOGGER.critical(f"A manager is already running on port {global_config['hon_data']['svr_managerPort']}. This may prevent the manager from operating correctly.")

    # run scheduler
    jobs = HonfiguratorSchedule(global_config)
    jobs.setup_tasks()

    # initialise MQTT
    mqtt = MQTTHandler(global_config = global_config)
    mqtt.connect()
    set_mqtt(mqtt)

    host = "127.0.0.1"
    game_server_to_mgr_port = global_config['hon_data']['svr_managerPort']

    # The autoping responder port is set to be 1 less than the public game port. This is to keep ports grouped together for convenience.
    udp_ping_responder_port = global_config['hon_data']['svr_starting_gamePort'] - 1 + 10000 if 'man_enableProxy' in global_config['hon_data'] and global_config['hon_data']['man_enableProxy'] else global_config['hon_data']['svr_starting_gamePort'] - 1

    global_config['hon_data']['autoping_responder_port'] = udp_ping_responder_port

    # instantiate the manager
    game_server_manager = GameServerManager(global_config, setup)

    print_formatted_text("\nConfiguration Overview")
    for key,value in global_config['hon_data'].items():
        if key == "svr_password": print_formatted_text(f"\t{key}: ***********")
        else: print_formatted_text(f"\t{key}: {value}")
    # create tasks for authenticating to master server, starting game server listener, auto pinger, and starting game server instances.
    tasks = []

    try:
        auth_coro = game_server_manager.manage_upstream_connections(udp_ping_responder_port)
        auth_task = game_server_manager.schedule_task(auth_coro, 'authentication_handler')
        tasks.append(auth_task)

        start_coro = game_server_manager.start_game_servers("all", launch=True)
        start_task = game_server_manager.schedule_task(start_coro, 'gameserver_startup')
        tasks.append(start_task)

        api_coro = game_server_manager.start_api_server()
        api_task = game_server_manager.schedule_task(api_coro, 'api_server')
        tasks.append(api_task)

        game_server_listener_coro = game_server_manager.start_game_server_listener(host, game_server_to_mgr_port)
        game_server_listener_task = game_server_manager.schedule_task(game_server_listener_coro, 'gameserver_listener')
        tasks.append(game_server_listener_task)

        auto_ping_listener_coro = game_server_manager.start_autoping_listener()
        auto_ping_listener_task = game_server_manager.schedule_task(auto_ping_listener_coro, 'autoping_listener')
        tasks.append(auto_ping_listener_task)

        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        LOGGER.info("Tasks cancelled due to stop_event being set.")
    finally:
        # Cancel all remaining tasks
        for task in tasks:
            if not task.done():
                task.cancel()
        LOGGER.info("Everything shut. Goodbye!")


if __name__ == "__main__":
    try:
        args = parse_arguments()
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.warn("KeyBoardInterrupt: Manager shutting down...")
        stop_event.set()
    except asyncio.CancelledError:
        pass

    if get_mqtt():
        get_mqtt().publish_json("manager/admin",{"event_type":"shutdown", "message": "Manager shutting down"})
        get_mqtt().disconnect()

    if MISC.get_os_platform() == "linux": subprocess.run(["reset"])
    sys.exit(0)
