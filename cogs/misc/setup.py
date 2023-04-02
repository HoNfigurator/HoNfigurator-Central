import os.path, os, sys
import subprocess as sp
import traceback
import pathlib
import json
from cogs.misc.logging import get_logger, get_home
from cogs.misc.hide_pass import getpass

ALLOWED_REGIONS = ["AU", "BR", "EU", "RU", "SEA", "TH", "USE", "USW" ]
LOGGER = get_logger()
HOME_PATH = get_home()
pip_requirements = pathlib.Path.cwd() / 'requirements.txt'

class SetupEnvironment:
    def __init__(self,config_file):
        self.config_file = config_file


    def get_default_configuration(self):
        if sys.platform == "win32":
            return self.get_default_configuration_windows()
        else:
            return self.get_default_configuration_linux()

    def get_default_configuration_linux(self):
        return {
            "discord_data": {
                "token": "asdfasd",
                "admin_username": "frank"
            },
            "application_data": {
                "timers": {
                    "game_server": {
                        "health_checks": {
                            "lag_healthcheck": 300,
                            "general_healthcheck": 120
                        },
                        "heartbeat_frequency": 5,
                        "ingame_check": 5,
                        "lobby_check": 5,
                        "leftover_game": 180,
                        "replay_wait": 330
                    },
                    "manager": {
                        "health_checks": {
                            "public_ip_healthcheck": 1800
                        },
                        "heartbeat_frequency": 10
                    }
                }
            },
            "hon_data": {
                "hon_install_directory": "/opt/hon/app/",
                "hon_home_directory": "/opt/hon/config/game/",
                "svr_masterServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_location": "",
                "svr_priority": "HIGH",
                "svr_total": 0,
                "svr_enableProxy": False,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10000,
                "svr_starting_voicePort": 10060
            }
        }

    def get_default_configuration_windows(self):
        return {
            "discord_data": {
                "token": "asdfasd",
                "admin_username": "frank"
            },
            "application_data": {
                "timers": {
                    "game_server": {
                        "health_checks": {
                            "lag_healthcheck": 300,
                            "general_healthcheck": 120
                        },
                        "heartbeat_frequency": 5,
                        "ingame_check": 5,
                        "lobby_check": 5,
                        "leftover_game": 180,
                        "replay_wait": 330
                    },
                    "manager": {
                        "health_checks": {
                            "public_ip_healthcheck": 1800
                        },
                        "heartbeat_frequency": 10
                    }
                }
            },
            "hon_data": {
                "hon_install_directory": "C:\\Program Files\\Heroes of Newerth x64 - Kongor\\",
                "hon_home_directory": "C:\\ProgramData\\HoN Server Data\\",
                "svr_masterServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_location": "",
                "svr_priority": "HIGH",
                "svr_total": 0,
                "svr_enableProxy": True,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10000,
                "svr_starting_voicePort": 10060
            }
        }

    def get_existing_configuration(self):
        with open(self.config_file, 'r') as config_file:
            hon_data = json.load(config_file)
        return hon_data

    def validate_hon_data(self, hon_data):
        major_issues = []
        minor_issues = []

        for key, value in hon_data.items():
            if key in ["hon_install_directory", "hon_home_directory"]:
                if not os.path.isdir(value):
                    try:
                        os.makedirs(value)
                    except Exception:
                        major_issues.append("Invalid path for {}: {}".format(key, value))
                elif not value.endswith("\\") and sys.platform == "win32":
                    hon_data[key] = value + "\\"
                    minor_issues.append("Resolved: Missing trailing backslash for {}: {}".format(key, value))

            elif key in ["svr_total", "svr_max_start_at_once", "svr_starting_gamePort", "svr_starting_voicePort"]:
                if not isinstance(value, int):
                    try:
                        hon_data[key] = int(value)
                        minor_issues.append("Resolved: Converted string integer to real integer for {}: {}".format(key, value))
                    except ValueError:
                        major_issues.append("Invalid integer value for {}: {}".format(key, value))

            elif key in ["svr_enableProxy"]:
                if not isinstance(value, bool):
                    if value.lower() in ['true','false']:
                        try:
                            hon_data[key] = value.lower() == value.lower()
                            minor_issues.append("Resolved: Invalid boolean value for {}: {}".format(key, value))
                        except Exception:
                            major_issues.append("Invalid boolean value for {}: {}".format(key, value))
                    else:
                        major_issues.append("Invalid boolean value for {}: {}".format(key, value))

            elif key in ["svr_region"]:
                if not isinstance(value, str):
                    major_issues.append("Invalid string value for {}: {}".format(key,value))
                elif value not in ALLOWED_REGIONS:
                    major_issues.append("Incorrect region. Can only be one of {}".format((',').join(ALLOWED_REGIONS)))

            else:
                if not isinstance(value, str):
                    major_issues.append("Invalid string value for {}: {}".format(key, value))

        if major_issues:
            error_message = "Configuration file validation issues:\n" + "\n".join(major_issues)
            raise ValueError(error_message)

        if minor_issues:
            print("\n".join(minor_issues))
            self.save_configuration_file(hon_data)

        return True

    def check_configuration(self):
        if not os.path.exists(pathlib.PurePath(self.config_file).parent):
            os.makedirs(pathlib.PurePath(self.config_file).parent)
        if not os.path.exists(self.config_file):
            return self.create_configuration_file()
        else:
            hon_data = self.get_existing_configuration()
            if self.validate_hon_data(hon_data):
                return True
            else: return False

    def save_configuration_file(self,hon_data):
        with open(self.config_file, 'w') as config_file:
            json.dump(hon_data, config_file, indent=4)

    def create_configuration_file(self):
        default_config = self.get_default_configuration()
        hon_data = default_config['hon_data']

        print("Configuration file not found. Please provide the following information for the initial setup:\nJust press ENTER if the default value is okay.")

        for key, value in hon_data.items():
            while True:
                if key == "svr_password":
                    user_input = getpass("\tEnter the value for '{}': ".format(key))
                else:
                    user_input = input("\tEnter the value for '{}'{}: ".format(key, " (default: {})".format(value) if value else ""))
                if user_input:
                    if key in ["svr_total", "svr_max_start_at_once", "svr_starting_gamePort", "svr_starting_voicePort"]:
                        try:
                            hon_data[key] = int(user_input)
                        except ValueError:
                            print("\tInvalid integer value entered for {}. Using the default value: {}".format(key, value.lower()))
                    elif key == "svr_enableProxy":
                        hon_data[key] = user_input.lower() == 'true'
                    elif key == "svr_region":
                        if user_input not in ALLOWED_REGIONS:
                            print("\tIncorrect region. Can only be one of {}".format((',').join(ALLOWED_REGIONS)))
                            continue
                        else:
                            hon_data[key] = user_input
                    else:
                        hon_data[key] = user_input
                break

        self.save_configuration_file(hon_data)

        print("Configuration file created: {}".format(self.config_file))

    def merge_config(self,hon_data):
        config = self.get_default_configuration()
        config['hon_data'] = hon_data
        return config

    def get_final_configuration(self):
        return self.merge_config(self.get_existing_configuration())

class PrepareDependencies:
    def __init__(self):
        pass
    def get_required_packages(self):
        try:
            with open(pip_requirements) as f:
                required_packages = f.read().splitlines()
            return required_packages
        except Exception:
            LOGGER.error(traceback.format_exc())
            return []

    def update_dependencies(self):
        try:
            required = self.get_required_packages()
            if len(required) == 0:
                LOGGER.warn("Unable to get contents of requirements.txt file")
                return False
            installed_packages = sp.run(['pip', 'freeze'], stdout=sp.PIPE, text=True)
            installed_packages_list = installed_packages.stdout.split('\n')
            missing = set(required) - set(installed_packages_list)
            python_path = sys.executable
            if missing:
                result = sp.run([python_path, '-m', 'pip', 'install', *missing])
                if result.returncode == 0:
                    LOGGER.info(f"SUCCESS, upgraded the following packages: {', '.join(missing)}")
                    return result
                else:
                    LOGGER.error(f"Error updating packages: {missing}\n error {result.stderr}")
                    return result
            else:
                LOGGER.info("Packages OK.")
                return True
        except Exception:
            LOGGER.exception(traceback.format_exc())
            return False
