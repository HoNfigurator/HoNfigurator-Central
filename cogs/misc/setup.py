import os.path, os, sys
from os.path import exists
from pathlib import Path
import subprocess as sp
import psutil
import traceback
import pathlib
import json
from cogs.misc.logger import get_logger, get_home, get_misc
from cogs.db.roles_db_connector import RolesDatabase
from cogs.misc.utilities import Misc
from cogs.misc.hide_pass import getpass
import copy

ALLOWED_REGIONS = ["AU", "BR", "EU", "RU", "SEA", "TH", "USE", "USW", "NEWERTH"]
LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()
pip_requirements = HOME_PATH / 'requirements.txt'

class SetupEnvironment:
    def __init__(self,config_file_hon):
        self.PATH_KEYS_IN_CONFIG_FILE = ["hon_install_directory","hon_home_directory"]
        self.PATH_KEYS_NOT_IN_CONFIG_FILE = ['hon_artefacts_directory', 'hon_logs_directory', 'hon_replays_directory', 'hon_executable_path']
        self.ALL_PATH_TYPES = self.PATH_KEYS_IN_CONFIG_FILE + self.PATH_KEYS_NOT_IN_CONFIG_FILE
        self.OTHER_CONFIG_EXCLUSIONS = ["svr_ip","svr_version","hon_executable", 'architecture','hon_executable_name', 'autoping_responder_port']
        self.config_file_hon = config_file_hon
        self.config_file_logging = HOME_PATH / "config" / "logging.json"
        self.default_configuration = self.get_default_hon_configuration()
        self.hon_data = self.default_configuration['hon_data']
        self.current_data = None

    def get_default_logging_configuration(self):
        return {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
                },
                "simple": {
                    "format": "%(asctime)s - %(levelname)s - %(message)s"
                }
            },
            "handlers": {
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "maxBytes": 10485760,
                    "backupCount": 5,
                    "formatter": "default",
                    "level": "INFO"
                },
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "simple",
                    "level": "INFO"
                }
            },
            "loggers": {
                "Server": {
                    "handlers": [
                        "file",
                        "console"
                    ],
                    "propagate": False,
                    "level": "INFO"
                }
            }
        }



    def get_default_hon_configuration(self):
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
                    },
                    "replay_cleaner" : {
                        "active" : False,
                        "max_replay_age_days" : 30,
                        "max_temp_files_age_days" : 1,
                        "max_temp_folders_age_days" : 1,
                        "max_clog_age_days" : 0
                    }
                }
            },
            "hon_data": {
                "hon_install_directory": Path("C:\\Program Files\\Heroes of Newerth x64 - Kongor\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/app/"),
                "hon_home_directory": Path("C:\\ProgramData\\HoN Server Data\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/config/KONGOR/"),
                "svr_masterServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_location": "",
                "svr_priority": "HIGH",
                "svr_total": int(MISC.get_cpu_count() / 2),
                "svr_total_per_core": 1,
                "man_enableProxy": False,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10001,
                "svr_starting_voicePort": 10061,
                "svr_managerPort": 1134,
                "svr_startup_timeout": 180,
                "svr_api_port": 5000
            }
        }

    def get_existing_configuration(self):
        with open(self.config_file_hon, 'r') as config_file_hon:
            hon_data = json.load(config_file_hon)
        return hon_data

    def validate_hon_data(self, hon_data=None):
        if hon_data:
            self.hon_data = hon_data

        major_issues = []
        minor_issues = []

        default_configuration = self.get_default_hon_configuration()
        default_hon_data = default_configuration['hon_data']

        for key, value in list(self.hon_data.items()):
            default_value = default_hon_data.get(key)
            default_value_type = type(default_value)

            if key in self.ALL_PATH_TYPES:
                # Ensure the path ends with the appropriate separator
                #fixed_path = add_separator_if_missing(value)
                path = Path(value)
                value = path

                if not path.is_dir() and not path.is_file():
                    try:
                        path.mkdir(parents=True, exist_ok=True)
                        minor_issues.append(f"Resolved: Path did not exist for {key}.")
                    except Exception:
                        major_issues.append(f"Invalid path for {key}: {path}")
                self.hon_data[key] = path

            if default_value_type == int:
                if not isinstance(value, int):
                    try:
                        self.hon_data[key] = int(value)
                        value = int(value)
                        minor_issues.append(f"Resolved: Converted string integer to real integer for {key}: {value}")
                    except ValueError:
                        major_issues.append("Invalid integer value for {}: {}".format(key, value))
                else:
                    if key == "svr_starting_gamePort" and value < 10001:
                        self.hon_data[key] = 10001
                        minor_issues.append(f"Resolved: Starting game port reassigned to {self.hon_data[key]}. Must start from 10001 one onwards.")
                    elif key == "svr_starting_voicePort":
                        if value < 10061:
                            self.hon_data[key] = 10061
                            minor_issues.append(f"Resolved: Starting voice port reassigned to {self.hon_data[key]}. Must be greater than 10061.")
                        if self.hon_data[key] - self.hon_data['svr_total'] < self.hon_data['svr_starting_gamePort']:
                            self.hon_data[key] = self.hon_data['svr_starting_gamePort'] + self.hon_data['svr_total']
                            minor_issues.append(f"Resolved: Starting voice port reassigned to {self.hon_data[key]}. Must be at least {self.hon_data['svr_total']} (svr_total) higher than the starting game port.")

            elif default_value_type == bool:
                if not isinstance(value, bool):
                    if value.lower() in ['true', 'false']:
                        try:
                            self.hon_data[key] = value.lower() == 'true'
                            minor_issues.append(f"Resolved: Invalid boolean value for {key}: {value}")
                        except Exception:
                            major_issues.append(f"Invalid boolean value for {key}: {value}")
                    elif value in ['0', '1']:
                        if value == '0':
                            self.hon_data[key] = False
                        elif value == '1':
                            self.hon_data[key] = True
                    else:
                        major_issues.append(f"Invalid boolean value for {key}: {value}")

            elif default_value_type == str:
                if not isinstance(value, str) or value == '':
                        major_issues.append(f"Invalid string value for {key}: {value}")
                elif key == "svr_location" and value not in ALLOWED_REGIONS:
                    major_issues.append(f"Incorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
            elif default_value_type == pathlib.WindowsPath:
                if not isinstance(value,pathlib.WindowsPath):
                    major_issues.append(f"Invalid path value for {key}: {value}")
            elif default_value_type == pathlib.PosixPath:
                if not isinstance(value,pathlib.PosixPath):
                    major_issues.append(f"Invalid path value for {key}: {value}")
            else:
                if key in self.PATH_KEYS_NOT_IN_CONFIG_FILE or key in self.OTHER_CONFIG_EXCLUSIONS:
                    pass
                else:
                    if key == "svr_enableProxy": # this is here to revert an issue I created when I mispelt the proxy setting.
                        self.hon_data["man_enableProxy"] = self.hon_data[key]
                        del self.hon_data[key]
                    else:
                        major_issues.append(f"Unexpected key and value type for {key}: {value}")

            if key == "svr_total":
                total_allowed = MISC.get_total_allowed_servers(int(self.hon_data['svr_total_per_core']))
                if value > total_allowed:
                    self.hon_data[key] = int(total_allowed)
                    minor_issues.append("Resolved: total server count reduced to total allowed. This is based on CPU analysis. More than this will provide a bad experience to players")

        if major_issues:
            error_message = "Configuration file validation issues:\n" + "\n".join(major_issues)
            raise ValueError(error_message)

        if minor_issues:
            print("\n".join(minor_issues))

        self.save_configuration_file()

        return True

    def check_configuration(self, args):
        if not os.path.exists(Path('game_states')):
            os.makedirs(Path('game_states'))
        if not os.path.exists(pathlib.PurePath(self.config_file_hon).parent):
            os.makedirs(pathlib.PurePath(self.config_file_hon).parent)
        if not os.path.exists(self.config_file_logging):
            self.create_logging_configuration_file()
        if not os.path.exists(self.config_file_hon):
            if args:
                if args.hon_install_directory:
                    self.hon_data["hon_install_directory"] = Path(args.hon_install_directory)
            self.create_hon_configuration_file(detected="hon_install_directory")
        database = RolesDatabase()
        if not database.add_default_data():
            while True:
                value = input("\tPlease provide your discord user ID. This is a 10 digit number:")
                try:
                    discord_id = int(value)
                    if len(str(discord_id)) < 10:
                        raise ValueError
                    database.add_default_data(discord_id=discord_id)
                    break
                except ValueError:
                    print("Value must be a 10 digit number. Here is a guide to find your discord user ID. https://www.youtube.com/watch?v=ZPROrf4Fe3Q")
        # else:
        self.hon_data = self.get_existing_configuration()
        self.full_config = self.merge_config()
        if self.validate_hon_data(self.full_config['hon_data']):
            return True
        else: return False

    def create_logging_configuration_file(self):
        with open(str(self.config_file_logging), 'w') as config_file_logging:
            json.dump(self.get_default_logging_configuration(), config_file_logging, indent=4)

    def create_hon_configuration_file(self,detected=None):

        print("\n\nConfiguration file not found. Please provide the following information for the initial setup:\nJust press ENTER if the default value is okay.")

        for key, value in self.hon_data.items():
            while True:
                if key == "svr_password":
                    user_input = getpass(f"\tEnter the value for '{key}': ")
                elif detected == key:
                    user_input = input("\tEnter the value for '{}'{}: ".format(key, " (detected: {})".format(value) if value or value == False else ""))
                else:
                    user_input = input("\tEnter the value for '{}'{}: ".format(key, " (default: {})".format(value) if value or value == False else ""))
                if user_input:
                    default_value_type = type(value)
                    new_value_type = type(user_input)

                    if new_value_type == int:
                        try:
                            self.hon_data[key] = int(user_input)
                            break
                        except ValueError:
                            print(f"\tInvalid integer value entered for {key}. Using the default value: {value}")
                    elif new_value_type == bool:
                        self.hon_data[key] = user_input.lower() == 'true'
                        break
                    elif new_value_type == str:
                        if key == "svr_location":
                            if user_input not in ALLOWED_REGIONS:
                                print(f"\tIncorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
                                continue
                            else:
                                self.hon_data[key] = user_input
                                break
                        elif key in self.PATH_KEYS_IN_CONFIG_FILE:
                            try:
                                user_input = user_input.replace("\"","")
                                Path(user_input)
                                self.hon_data[key] = user_input
                                break
                            except Exception:
                                print(f"\tExpected valid file path. Please try again. Here is an example value: {self.hon_data[key]}")
                        else:
                            self.hon_data[key] = user_input
                            break
                    else:
                        print(f"\tUnexpected value type ({new_value_type}) for {key}. Skipping this key.")
                else:
                    break
        if self.validate_hon_data():
            return True
        return False

    def save_configuration_file(self):
        def are_dicts_equal_with_types(d1, d2):
            if d1.keys() != d2.keys():
                return False

            for key in d1:
                if type(d1[key]) != type(d2[key]) or d1[key] != d2[key]:
                    return False

            return True

        hon_data_to_save = {key: value for key, value in self.hon_data.items() if key not in self.PATH_KEYS_NOT_IN_CONFIG_FILE and key not in self.OTHER_CONFIG_EXCLUSIONS}
        # ensure path objects are
        for path in self.PATH_KEYS_IN_CONFIG_FILE:
            hon_data_to_save[path] = str(hon_data_to_save[path])

        if Path(self.config_file_hon).exists():
            if are_dicts_equal_with_types(self.get_existing_configuration(), hon_data_to_save):
                return False

        with open(self.config_file_hon, 'w') as config_file_hon:
            json.dump(hon_data_to_save, config_file_hon, indent=4)

        return True

    def merge_config(self):
        config = self.get_default_hon_configuration()
        config['system_data'] = self.add_miscellaneous_data()
        config['hon_data'].update(self.hon_data)
        return config

    def add_runtime_data(self):
        if MISC.get_os_platform() == "win32":
            hon_artefacts_directory = Path(self.hon_data['hon_home_directory']) / "Documents" / "Heroes of Newerth x64"
            hon_replays_directory = hon_artefacts_directory / "KONGOR" / "replays"
            hon_logs_directory = hon_artefacts_directory / "KONGOR" / "logs"
            executable = f"hon_x64"
            suffix = ".exe"
            file_name = f'{executable}{suffix}'
            architecture = "was-crIac6LASwoafrl8FrOa"
        else: # this should be "linux"
            hon_artefacts_directory = Path(self.hon_data["hon_home_directory"])
            hon_replays_directory = hon_artefacts_directory / "replays"
            hon_logs_directory = hon_artefacts_directory / "logs"
            executable = "hon-x86_64-server"
            file_name = executable
            architecture = 'las-crIac6LASwoafrl8FrOa'

        self.hon_data['hon_artefacts_directory'] = hon_artefacts_directory
        self.hon_data['hon_replays_directory'] = hon_replays_directory
        self.hon_data['hon_logs_directory'] = hon_logs_directory
        self.hon_data['svr_ip'] = MISC.get_public_ip()
        self.hon_data['hon_executable_path'] = self.hon_data['hon_install_directory'] / file_name
        self.hon_data['hon_executable_name'] = file_name
        self.hon_data['svr_version'] = MISC.get_svr_version(self.hon_data['hon_executable_path'])
        self.hon_data['architecture'] = architecture

    def add_miscellaneous_data(self):
        return (
            {
                "system_data" : {
                    "cpu_count": MISC.get_cpu_count(),
                    "cpu_name": MISC.get_cpu_name(),
                    "total_ram": MISC.get_total_ram(),
                    "server_total_allowed": MISC.get_total_allowed_servers(self.hon_data['svr_total_per_core']),
                }
            }
        )

    def get_final_configuration(self):
        self.add_runtime_data()
        if self.validate_hon_data():
            return self.merge_config()
        else:
            return False
