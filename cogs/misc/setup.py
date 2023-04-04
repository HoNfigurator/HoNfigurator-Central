import os.path, os, sys
from os.path import exists
from pathlib import Path
import subprocess as sp
import psutil
import traceback
import pathlib
import json
from cogs.misc.logging import get_logger, get_home, get_misc
from cogs.misc.utilities import Misc
from cogs.misc.hide_pass import getpass
import copy

ALLOWED_REGIONS = ["AU", "BR", "EU", "RU", "SEA", "TH", "USE", "USW" ]
LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()
pip_requirements = HOME_PATH / 'requirements.txt'

class SetupEnvironment:
    def __init__(self,config_file):
        self.KEYS_NOT_IN_CONFIG_FILE = ['hon_artefacts_directory', 'hon_logs_directory', 'hon_replays_directory']
        self.ALL_PATH_TYPES = ["hon_install_directory","hon_home_directory"] + self.KEYS_NOT_IN_CONFIG_FILE
        self.config_file = config_file
        self.default_configuration = self.get_default_configuration()
        self.hon_data = self.default_configuration['hon_data']
        self.current_data = None

    def get_default_configuration(self):
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
                "hon_install_directory": Path("C:\\Program Files\\Heroes of Newerth x64 - Kongor\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/app/"),
                "hon_home_directory": Path("C:\\ProgramData\\HoN Server Data\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/config/game/"),
                "svr_masterServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_location": "",
                "svr_priority": "HIGH",
                "svr_total": int(MISC.get_cpu_count() / 2),
                "svr_total_per_core": 1,
                "svr_enableProxy": False,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10000,
                "svr_starting_voicePort": 10060,
                "svr_managerPort": 1135,
            }
        }

    def get_existing_configuration(self):
        with open(self.config_file, 'r') as config_file:
            hon_data = json.load(config_file)
        return hon_data

    def validate_hon_data(self, hon_data=None):        
        if hon_data:
            self.hon_data = hon_data
   
        major_issues = []
        minor_issues = []

        default_configuration = self.get_default_configuration()
        default_hon_data = default_configuration['hon_data']

        for key, value in self.hon_data.items():
            default_value = default_hon_data.get(key)
            default_value_type = type(default_value)

            if key in self.ALL_PATH_TYPES:
                # Ensure the path ends with the appropriate separator
                #fixed_path = add_separator_if_missing(value)
                path = Path(value)
                value = path

                if not path.is_dir():
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

            elif default_value_type == bool:
                if not isinstance(value, bool):
                    if value.lower() in ['true', 'false']:
                        try:
                            self.hon_data[key] = value.lower() == 'true'
                            minor_issues.append(f"Resolved: Invalid boolean value for {key}: {value}")
                        except Exception:
                            major_issues.append(f"Invalid boolean value for {key}: {value}")
                    else:
                        major_issues.append(f"Invalid boolean value for {key}: {value}")

            elif default_value_type == str:
                if not isinstance(value, str) or value == '':
                        major_issues.append(f"Invalid string value for {key}: {value}")
                elif key == "svr_region" and value not in ALLOWED_REGIONS:
                    major_issues.append(f"Incorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
            elif default_value_type == pathlib.WindowsPath:
                if not isinstance(value,pathlib.WindowsPath):
                    major_issues.append(f"Invalid path value for {key}: {value}")
            elif default_value_type == pathlib.PosixPath:
                if not isinstance(value,pathlib.WindowsPath):
                    major_issues.append(f"Invalid path value for {key}: {value}")
            else:
                if key in self.KEYS_NOT_IN_CONFIG_FILE:
                    pass
                else:
                    major_issues.append(f"Unexpected key and value type for {key}: {value}")

            if key == "svr_total":
                #if 'svr_total_per_core' not in self.hon_data:
                    #self.hon_data.update({'svr_total_per_core':1})

                total_allowed = MISC.get_total_allowed_servers(self.hon_data['svr_total_per_core'])
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

    def check_configuration(self):
        if not os.path.exists(pathlib.PurePath(self.config_file).parent):
            os.makedirs(pathlib.PurePath(self.config_file).parent)
        if not os.path.exists(self.config_file):
            return self.create_configuration_file()
        else:
            self.hon_data = self.get_existing_configuration()
            self.full_config = self.merge_config()
            if self.validate_hon_data():
                return True
            else: return False

    def create_configuration_file(self):

        print("Configuration file not found. Please provide the following information for the initial setup:\nJust press ENTER if the default value is okay.")

        for key, value in self.hon_data.items():
            while True:
                if key == "svr_password":
                    user_input = getpass(f"\tEnter the value for '{key}': ")
                else:
                    user_input = input("\tEnter the value for '{}'{}: ".format(key, " (default: {})".format(value) if value else ""))
                if user_input:
                    default_value_type = type(value)

                    if default_value_type == int:
                        try:
                            self.hon_data[key] = int(user_input)
                            break
                        except ValueError:
                            print(f"\tInvalid integer value entered for {key}. Using the default value: {value}")
                    elif default_value_type == bool:
                        self.hon_data[key] = user_input.lower() == 'true'
                        break
                    elif default_value_type == str:
                        if key == "svr_region":
                            if user_input not in ALLOWED_REGIONS:
                                print(f"\tIncorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
                                continue
                            else:
                                self.hon_data[key] = user_input
                                break
                        else:
                            self.hon_data[key] = user_input
                            break
                    else:
                        print("\tUnexpected value type for {key}. Skipping this key.")
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

        hon_data_to_save = {key: value for key, value in self.hon_data.items() if key not in self.KEYS_NOT_IN_CONFIG_FILE}

        if Path(self.config_file).exists():
            if are_dicts_equal_with_types(self.get_existing_configuration(), hon_data_to_save):
                return False
        
        hon_data_to_save['hon_home_directory'] = str(hon_data_to_save['hon_home_directory'])
        hon_data_to_save['hon_install_directory'] = str(hon_data_to_save['hon_install_directory'])

        with open(self.config_file, 'w') as config_file:
            json.dump(hon_data_to_save, config_file, indent=4)

        return True

    def merge_config(self):
        config = self.get_default_configuration()
        config['system_data'] = self.add_miscellaneous_data()
        config['hon_data'].update(self.hon_data)
        return config

    def add_runtime_data(self):
        if MISC.get_os_platform() == "win32":
            hon_artefacts_directory = Path(self.hon_data['hon_home_directory']) / "Documents" / "Heroes of Newerth x64"
            hon_replays_directory = hon_artefacts_directory / "game" / "replays"
            hon_logs_directory = hon_artefacts_directory / "game" / "logs"
        else:
            hon_artefacts_directory = Path(self.hon_data["hon_home_directory"])
            hon_replays_directory = hon_artefacts_directory / "replays"
            hon_logs_directory = hon_artefacts_directory / "logs"
        self.hon_data['hon_artefacts_directory'] = str(hon_artefacts_directory)
        self.hon_data['hon_replays_directory'] = str(hon_replays_directory)
        self.hon_data['hon_logs_directory'] = str(hon_logs_directory)

    def add_miscellaneous_data(self):
        return (
            {
                "system_data" : {
                    "cpu_count": MISC.get_cpu_count(),
                    "cpu_name": MISC.get_cpu_name(),
                    "total_ram": MISC.get_total_ram(),
                    'server_total_allowed': MISC.get_total_allowed_servers(self.hon_data['svr_total_per_core'])
                }
            }
        )

    def get_final_configuration(self):
        self.add_runtime_data()
        if self.validate_hon_data():
            return self.merge_config()
        else:
            return False


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
