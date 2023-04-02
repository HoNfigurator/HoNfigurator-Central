import os.path, os, sys
from os.path import exists
from pathlib import Path
import subprocess as sp
import psutil
import traceback
import json
from cogs.misc.logging import get_logger, get_home
from cogs.misc.utilities import Misc
from cogs.misc.hide_pass import getpass
import copy

ALLOWED_REGIONS = ["AU", "BR", "EU", "RU", "SEA", "TH", "USE", "USW" ]
LOGGER = get_logger()
HOME_PATH = Path(get_home())

class SetupEnvironment:
    def __init__(self,config_file):
        self.config_file = config_file
        self.misc = Misc()
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
                "hon_install_directory": "C:\\Program Files\\Heroes of Newerth x64 - Kongor\\" if self.misc.os_platform.lower().startswith("win") else "/opt/hon/",
                "hon_home_directory": "C:\\ProgramData\\HoN Server Data\\" if self.misc.os_platform.lower().startswith("win") else "/opt/hon_server_data/",
                "svr_masterServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_location": "",
                "svr_priority": "HIGH",
                "svr_total": int(self.misc.get_cpu_count() / 2),     # total logical cores in half.
                "svr_total_per_core": 1,
                "svr_enableProxy": True,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10000,
                "svr_starting_voicePort": 10060,
                "svr_managerPort": 1135
            }
        }

    def get_existing_configuration(self):
        with open(self.config_file, 'r') as config_file:
            hon_data = json.load(config_file)
        return hon_data

    def validate_hon_data(self, hon_data=dict):
        
        def add_separator_if_missing(path):
            separator = os.path.sep
            if not str(path).endswith(separator):
                path = path + separator
            return path
   
        major_issues = []
        minor_issues = []

        default_configuration = self.get_default_configuration()
        default_hon_data = default_configuration['hon_data']

        for key, value in hon_data.items():
            default_value = default_hon_data.get(key)
            default_value_type = type(default_value)

            if default_value_type == int:
                if not isinstance(value, int):
                    try:
                        hon_data[key] = int(value)
                        minor_issues.append("Resolved: Converted string integer to real integer for {}: {}".format(key, value))
                    except ValueError:
                        major_issues.append("Invalid integer value for {}: {}".format(key, value))

            elif default_value_type == bool:
                if not isinstance(value, bool):
                    if value.lower() in ['true', 'false']:
                        try:
                            hon_data[key] = value.lower() == 'true'
                            minor_issues.append("Resolved: Invalid boolean value for {}: {}".format(key, value))
                        except Exception:
                            major_issues.append("Invalid boolean value for {}: {}".format(key, value))
                    else:
                        major_issues.append("Invalid boolean value for {}: {}".format(key, value))

            elif default_value_type == str:
                if not isinstance(value, str) or value == '':
                    major_issues.append("Invalid string value for {}: {}".format(key, value))
                elif key == "svr_region" and value not in ALLOWED_REGIONS:
                    major_issues.append("Incorrect region. Can only be one of {}".format((',').join(ALLOWED_REGIONS)))
            else:
                major_issues.append("Unexpected key and value type for {}: {}".format(key, value))

            if key in ["hon_install_directory", "hon_home_directory"]:
                # Ensure the path ends with the appropriate separator
                fixed_path = add_separator_if_missing(value)

                if not Path(fixed_path).is_dir():
                    try:
                        Path(fixed_path).mkdir(parents=True, exist_ok=True)
                        minor_issues.append(f"Resolved: Path did not exist for {key}.")
                    except Exception:
                        major_issues.append("Invalid path for {}: {}".format(key, fixed_path))
                hon_data[key] = str(fixed_path)
            elif key == "svr_total":
                #if 'svr_total_per_core' not in hon_data:
                    #hon_data.update({'svr_total_per_core':1})

                total_allowed = self.misc.get_total_allowed_servers(hon_data['svr_total_per_core'])
                if value > total_allowed:
                    hon_data[key] = int(total_allowed)
                    minor_issues.append("Resolved: total server count reduced to total allowed. This is based on CPU analysis. More than this will provide a bad experience to players")

            
            
                    

        if major_issues:
            error_message = "Configuration file validation issues:\n" + "\n".join(major_issues)
            raise ValueError(error_message)

        if minor_issues:
            print("\n".join(minor_issues))

        self.save_configuration_file(hon_data)

        return True


    def check_configuration(self):
        config_path = HOME_PATH / 'config'
        if not config_path.exists():
            config_path.mkdir(parents=True)
        if not Path(self.config_file).exists():
            return self.create_configuration_file()
        else:
            hon_data = self.get_existing_configuration()
            full_config = self.merge_config(hon_data)
            if self.validate_hon_data(full_config['hon_data']):
                return True
            else: return False

    def create_configuration_file(self):

        print("Configuration file not found. Please provide the following information for the initial setup:\nJust press ENTER if the default value is okay.")

        for key, value in self.hon_data.items():
            while True:
                if key == "svr_password":
                    user_input = getpass("\tEnter the value for '{}': ".format(key))
                else:
                    user_input = input("\tEnter the value for '{}'{}: ".format(key, " (default: {})".format(value) if value else ""))
                if user_input:
                    default_value_type = type(value)

                    if default_value_type == int:
                        try:
                            self.hon_data[key] = int(user_input)
                            break
                        except ValueError:
                            print("\tInvalid integer value entered for {}. Using the default value: {}".format(key, value))
                    elif default_value_type == bool:
                        self.hon_data[key] = user_input.lower() == 'true'
                        break
                    elif default_value_type == str:
                        if key == "svr_region":
                            if user_input not in ALLOWED_REGIONS:
                                print("\tIncorrect region. Can only be one of {}".format((',').join(ALLOWED_REGIONS)))
                                continue
                            else:
                                self.hon_data[key] = user_input
                                break
                        else:
                            self.hon_data[key] = user_input
                            break
                    else:
                        print("\tUnexpected value type for {}. Skipping this key.".format(key))
                else:
                    break
        if self.validate_hon_data(self.hon_data):
            return True
        return False

    def save_configuration_file(self,hon_data):
        def are_dicts_equal_with_types(d1, d2):
            if d1.keys() != d2.keys():
                return False

            for key in d1:
                if type(d1[key]) != type(d2[key]) or d1[key] != d2[key]:
                    return False

            return True
        if Path(self.config_file).exists():
            if are_dicts_equal_with_types(self.get_existing_configuration(),hon_data):
                return False
        with open(self.config_file, 'w') as config_file:
            json.dump(hon_data, config_file, indent=4)
        return True

    def merge_config(self,hon_data):
        config = self.get_default_configuration()
        config['system_data'] = self.add_miscellaneous_data()
        config['hon_data'].update(hon_data)
        return config

    def add_miscellaneous_data(self):
        return (
            {
                "system_data" : {
                    "cpu_count": self.misc.get_cpu_count(),
                    "cpu_name": self.misc.get_cpu_name(),
                    "total_ram": self.misc.get_total_ram()
                }
            }        
        )

    def get_final_configuration(self):
        return self.merge_config(self.get_existing_configuration())


class PrepareDependencies:
    def __init__(self):
        pass
    def get_required_packages(self):
        try:
            with open(f"{HOME_PATH}\\requirements.txt") as f:
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
            if missing:
                python_path = sp.getoutput('where python').split("\n")[0]
                result = sp.run([python_path, '-m', 'pip', 'install', *missing])
                if result.returncode == 0:
                    LOGGER.info(f"SUCCESS, upgraded the following packages: {', '.join(missing)}")
                    python_path = sys.executable
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
