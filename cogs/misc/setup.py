import os.path
import os
from datetime import datetime
from pathlib import Path
import pathlib
import json
import requests
import re
import shutil
import traceback
from cogs.misc.logger import get_logger, get_home, get_misc, get_discord_username, set_discord_username
from utilities.filebeat import get_discord_user_id_from_api
from cogs.db.roles_db_connector import RolesDatabase
from cogs.misc.hide_pass import getpass

ALLOWED_REGIONS = ["AU", "BR", "EU", "RU",
                   "SEA", "TH", "USE", "USW", "NEWERTH", "TEST"]
LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()
pip_requirements = HOME_PATH / 'requirements.txt'


class SetupEnvironment:
    def __init__(self, config_file_hon):
        self.PATH_KEYS_IN_APP_DATA_CONFIG_FILE = [
            "location"
        ]
        self.PATH_KEYS_IN_HON_DATA_CONFIG_FILE = [
            "hon_install_directory", "hon_home_directory"]
        self.PATH_KEYS_NOT_IN_HON_DATA_CONFIG_FILE = [
            'hon_artefacts_directory', 'hon_logs_directory', 'hon_replays_directory', 'hon_executable_path']
        self.ALL_PATH_TYPES = self.PATH_KEYS_IN_HON_DATA_CONFIG_FILE + \
            self.PATH_KEYS_NOT_IN_HON_DATA_CONFIG_FILE
        self.OTHER_CONFIG_EXCLUSIONS = ["svr_ip", "svr_version", "hon_executable",
                                        'architecture', 'hon_executable_name', 'autoping_responder_port']
        self.WINDOWS_SPECIFIC_CONFIG_ITEMS = [
            'svr_noConsole', 'svr_override_affinity', 'man_enableProxy']
        self.LINUX_SPECIFIC_CONFIG_ITEMS = ['man_use_cowmaster']
        self.config_file_hon = config_file_hon
        self.config_file_logging = HOME_PATH / "config" / "logging.json"
        self.default_configuration = self.get_default_hon_configuration()
        self.hon_data = self.default_configuration['hon_data']
        self.application_data = self.default_configuration['application_data']
        self.current_data = None
        self.server_name_generated = False

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
            "hon_data": {
                "hon_install_directory": Path("C:\\Program Files\\Heroes of Newerth x64 - CLEAN\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/app/"),
                "hon_home_directory": Path("C:\\ProgramData\\HoN Server Data\\") if MISC.get_os_platform() == "win32" else Path("/opt/hon/config/"),
                "svr_masterServer": "api.kongor.online",
                "svr_patchServer": "api.kongor.online",
                "svr_login": "",
                "svr_password": "",
                "svr_name": "",
                "svr_override_suffix": False,
                "svr_suffix": "",
                "svr_override_state": False,
                "svr_state": "",
                "svr_location": self.get_server_region(),
                "svr_priority": "HIGH",
                "svr_total": int(MISC.get_cpu_count() / 2),
                "svr_total_per_core": 1.0,
                "man_enableProxy": True if MISC.get_os_platform() == "win32" else False,
                "svr_noConsole": False,
                "svr_enableBotMatch": True,
                "svr_start_on_launch": True,
                "svr_override_affinity": False,
                "svr_max_start_at_once": 5,
                "svr_starting_gamePort": 10001,
                "svr_starting_voicePort": 10061,
                "svr_managerPort": 1134,
                "svr_startup_timeout": 180,
                "svr_api_port": 5000,
                "man_use_cowmaster": False,
                "svr_restart_between_games": False,
                "svr_beta_mode": False,
            },
            "application_data": {
                "timers": {
                    "manager": {
                        "public_ip_healthcheck": 1800,
                        "general_healthcheck": 60,
                        "lag_healthcheck": 120,
                        "check_for_hon_update": 120,
                        "check_for_honfigurator_update": 60,
                        "resubmit_match_stats": 20,
                        "filebeat_verification": 10800
                    },
                    "replay_cleaner": {
                        "active": False,
                        "max_replay_age_days": 0,
                        "max_temp_files_age_days": 1,
                        "max_temp_folders_age_days": 1,
                        "max_clog_age_days": 0,
                        "scheduled_time": "00:20"
                    }
                },
                "longterm_storage": {
                    "active": False,
                    "location": ""
                },
                "filebeat": {
                    "send_diagnostics_data": True
                },
                "discord": {
                    "owner_id": 0
                },
            }
        }

    def get_server_region(self):
        try:
            public_ip = MISC.get_public_ip()
            response = requests.get(
                f"http://ip-api.com/json/{public_ip}")
            data = response.json()
            country_code = data['countryCode']
            longitude = float(data['lon'])
        except Exception as e:
            print(f"Failed to get IP geolocation: {e}")
            return None

        # Determine US region based on longitude
        if country_code == 'US':
            if longitude < -98.5795:  # Approximate center longitude of the US
                return 'USW'
            else:
                return 'USE'

        # Map other country codes to server regions
        mapping = {
            'AU': 'AU', 'NZ': 'AU', 'JP': 'AU', 'KR': 'AU', 'IN': 'AU',
            'EU': 'EU', 'GB': 'EU', 'DE': 'EU', 'FR': 'EU', 'ES': 'EU', 'IT': 'EU', 'TR': 'EU', 'IL': 'EU',
            'TH': 'TH',
            'SEA': 'SEA', 'SG': 'SEA', 'MY': 'SEA', 'ID': 'SEA', 'PH': 'SEA', 'VN': 'SEA',
            'BR': 'BR', 'AR': 'BR', 'CL': 'BR', 'CO': 'BR', 'PE': 'BR',
            'RU': 'RU', 'UA': 'RU', 'KZ': 'RU', 'BY': 'RU',
            # Add more regions as needed
        }

        # default to 'USE' if country code not found
        return mapping.get(country_code, "USE")

    def get_existing_configuration(self):
        with open(self.config_file_hon, 'r') as config_file_hon:
            hon_data = json.load(config_file_hon)
        return hon_data
    
    async def generate_server_name(self):
        # Get the city
        if 'svr_override_state' in self.hon_data and self.hon_data['svr_override_state']:
            state_code = self.hon_data['svr_state']
        else:
            state_code = self.resolve_state_code(MISC.get_public_ip())
        
        if 'svr_override_suffix' in self.hon_data and self.hon_data['svr_override_suffix']:
            suffix = self.hon_data['svr_suffix']
            suffix = self.format_discord_username(suffix)
        else:
            # Get the discord username
            suffix = get_discord_username()

            # Resolve the username from the discord ID
            if not suffix:
                try:
                    if not get_discord_username():
                        suffix = await get_discord_user_id_from_api(self.database.get_discord_owner_id())
                except Exception:
                    LOGGER.error(f"Failed to resolve the discord username, are you sure this discord ID is correct? {self.application_data['discord']['owner_id']}\n{traceback.format_exc()}")
            
            if not suffix:
                suffix = "Unknown"

            # Format the discord username
            suffix = self.format_discord_username(suffix)

        # Generate the server name
        state = state_code.split('-')
        if len(state) > 1:
            state = state[1]
        else:
            state = state[0]
        
        server_name = f"{self.hon_data['svr_location']}-{state} {suffix}"

        return server_name

    async def validate_hon_data(self, hon_data=None, application_data=None):
        if hon_data:
            self.hon_data = hon_data

        if application_data:
            self.application_data = application_data
        
        
        # Since TH has over 10 servers hosted by a single person, we need to do more testing first on what the impact would be of having the same server names. So excluding from autogen for now.
        if self.hon_data['svr_location'] != "TH" and not self.server_name_generated:
            self.hon_data['svr_name'] = await self.generate_server_name()

        major_issues = []
        minor_issues = []

        default_configuration = self.get_default_hon_configuration()
        default_hon_data = default_configuration['hon_data']
        default_application_data = default_configuration['application_data']

        def validate_paths(key, value):
            path = Path(value)
            if not os.path.isabs(str(path)):
                major_issues.append(
                    f"The provided path for {key} is not a fully qualified path: {path}")
                return False
            try:
                path.relative_to(HOME_PATH)
                # If the path is relative to HOME_PATH, raise a major issue
                major_issues.append(
                    f"The provided path for {key} should not be beneath the home path of HoNfigurator: {path}")
                return False
            except ValueError:
                # If it raises a ValueError, the path is not under HOME_PATH, so this is what we want
                pass
            return path

        def handle_path(key, value):
            value = validate_paths(key, value)
            if not value:
                return None

            if not value.is_dir() and not value.is_file():
                try:
                    value.mkdir(parents=True, exist_ok=True)
                    minor_issues.append(
                        f"Resolved: Path did not exist for {key}.")
                except Exception:
                    major_issues.append(f"Invalid path for {key}: {value}")
                    return None
            return value

        def is_valid_time_format(time_str):
            try:
                datetime.strptime(time_str, "%H:%M")
                return True
            except ValueError:
                return False

        def check_type_and_convert(key, value, expected_type):
            if key == "scheduled_time" and not is_valid_time_format(value):
                return None
            elif expected_type == int:
                return handle_int(key, value)
            elif expected_type == bool:
                return handle_bool(key, value)
            elif expected_type == str:
                return handle_str(key, value)
            elif expected_type == float:
                return handle_float(key, value)
            elif expected_type in [pathlib.PosixPath, pathlib.WindowsPath]:
                return handle_path(key, value)
            else:
                return value

        def handle_float(key, value):
            if not isinstance(value, float):
                try:
                    return float(value)
                except ValueError:
                    return None
            return value

        def handle_int(key, value):
            if not isinstance(value, int):
                try:
                    return int(value)
                except ValueError:
                    return None
            return value

        def handle_bool(key, value):
            if not isinstance(value, bool):
                if str(value).lower() in ['true', 'false']:
                    return str(value).lower() == 'true'
                elif str(value) in ['0', '1']:
                    return str(value) == '1'
                else:
                    return None
            return value

        def handle_str(key, value):
            if not isinstance(value, str) or value == '':
                if key in ["location", "svr_state", "svr_suffix"] and value == '':
                    return value
                else:
                    return None
            return value

        def iterate_over_app_data(app_dict, default_dict):
            keys_to_remove = []
            for key, value in app_dict.items():
                default_value = default_dict.get(key)
                default_value_type = type(default_value)

                if default_value is None:
                    keys_to_remove.append(key)
                    minor_issues.append(
                        f"Resolved: Removed unknown configuration item: {key}")
                elif isinstance(value, dict) and isinstance(default_value, dict):
                    iterate_over_app_data(value, default_value)
                else:
                    new_value = check_type_and_convert(
                        key, value, default_value_type)
                    if new_value is None:
                        major_issues.append(
                            f"Invalid value for {key}: {value}")
                    elif new_value != value:
                        minor_issues.append(
                            f"Resolved: Converted {key} to appropriate type")
                    app_dict[key] = new_value

            for key in keys_to_remove:
                del app_dict[key]

            for key, default_value in default_dict.items():
                if key not in app_dict:
                    app_dict[key] = default_value
                    minor_issues.append(
                        f"Resolved: Added missing configuration item: {key} with default value: {default_value}")

            # Extra logic for the "location" key
            if 'location' in app_dict and self.application_data['longterm_storage']['active']:
                value = handle_path('location', app_dict['location'])
                if value is not None:
                    app_dict['location'] = value
            
        iterate_over_app_data(self.application_data, default_application_data)

        for key, value in list(self.hon_data.items()):
            default_value = default_hon_data.get(key)
            default_value_type = type(default_value)

            if key in self.ALL_PATH_TYPES:
                value = handle_path(key, value)
                if value is not None:
                    self.hon_data[key] = value
            else:
                new_value = check_type_and_convert(
                    key, value, default_value_type)
                if new_value is None:
                    major_issues.append(f"Invalid value for {key}: {value}")
                elif new_value is not value:
                    minor_issues.append(
                        f"Resolved: Converted {key} to appropriate type")
                self.hon_data[key] = new_value

                # Additional validation for some specific keys
                if key == "svr_starting_gamePort" and new_value < 10001:
                    self.hon_data[key] = 10001
                    minor_issues.append(
                        f"Resolved: Starting game port reassigned to {self.hon_data[key]}. Must start from 10001 one onwards.")
                elif key == "svr_starting_voicePort":
                    if new_value < 10061:
                        self.hon_data[key] = 10061
                        minor_issues.append(
                            f"Resolved: Starting voice port reassigned to {self.hon_data[key]}. Must be greater than 10061.")
                    if self.hon_data[key] - self.hon_data['svr_total'] < self.hon_data['svr_starting_gamePort']:
                        self.hon_data[key] = self.hon_data['svr_starting_gamePort'] + \
                            self.hon_data['svr_total']
                        minor_issues.append(
                            f"Resolved: Starting voice port reassigned to {self.hon_data[key]}. Must be at least {self.hon_data['svr_total']} (svr_total) higher than the starting game port.")
                elif key == "svr_location" and new_value not in ALLOWED_REGIONS:
                    major_issues.append(
                        f"Incorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
                elif key == "svr_total":
                    total_allowed = int(MISC.get_total_allowed_servers(
                        float(self.hon_data['svr_total_per_core'])))
                    if new_value > total_allowed:
                        self.hon_data[key] = total_allowed
                        minor_issues.append(
                            "Resolved: total server count reduced to total allowed. This is based on CPU analysis. More than this will provide a bad experience to players")

            if key in self.PATH_KEYS_NOT_IN_HON_DATA_CONFIG_FILE or key in self.OTHER_CONFIG_EXCLUSIONS:
                pass
            # this is to resolve a misconfig where svr_enableProxy was used instead of man_enableProxy by accident.
            elif key == "svr_enableProxy":
                self.hon_data["man_enableProxy"] = self.hon_data[key]
                del self.hon_data[key]
            elif key == "hon_home_directory":
                hon_home_directory = str(self.hon_data["hon_home_directory"])
                if hon_home_directory.endswith('/KONGOR'):
                    hon_home_directory = hon_home_directory.rstrip('/KONGOR')
                self.hon_data["hon_home_directory"] = Path(hon_home_directory)
            elif default_value_type is type(None):
                del self.hon_data[key]
                minor_issues.append(
                    f"Resolved: Removed unknown configuration item: {key}")
            elif key == "man_use_cowmaster" and MISC.get_os_platform() != "linux":
                if self.hon_data[key]:
                    self.hon_data[key] = False
                    minor_issues.append(
                        "Resolved: CowMaster is reserved for linux use only. Setting this value to false.")

        if major_issues:
            error_message = "Configuration file validation issues:\n" + \
                "\n".join(major_issues)
            raise ValueError(error_message)

        if minor_issues:
            print("\n".join(minor_issues))

        self.save_configuration_file()

        return True

    async def check_configuration(self, args):
        if not os.path.exists(Path('game_states')):
            os.makedirs(Path('game_states'))
        if not os.path.exists(pathlib.PurePath(self.config_file_hon).parent):
            os.makedirs(pathlib.PurePath(self.config_file_hon).parent)
        if not os.path.exists(self.config_file_logging):
            self.create_logging_configuration_file()
        
        self.database = RolesDatabase()

        if not self.database.add_default_data():
            agree = input("Welcome to HoNfigurator. By using our software, you agree to these terms and conditions.\
                        \n1. To ensure the legitimacy and effective administration of game servers, server administrators are required to authenticate using their Discord account.\
                        \n2. You may receive alerts or notifications via Discord from the HoNfigurator bot regarding the status of your game servers.\
                        \n3. The hosting of dedicated servers through HoNfigurator requires the use of HoN server binaries. Users acknowledge that these binaries are not owned or maintained by the author of HoNfigurator.\
                        \n4. In order to monitor server performance and maintain game integrity, the following diagnostic data will be collected:\
                        \n\t- This server's public IP address.\
                        \n\t- Server administrator's Discord ID.\
                        \n\t- Game server logs, including in-game events and chat logs.\
                        \n\t- Player account names and public IP addresses.\
                        \n   This data is essential for the effective operation of the server and for ensuring a fair gaming environment.\
                        \n\n6. Game replays will be stored on the server and can be requested by players in-game. Server administrators may manage these replays using the provided HoNfigurator settings. We recommend retaining replays for a minimum of 60 days for player review and quality assurance purposes.\
                        \n\nIn summary, by using HoNfigurator, users agree to:\
                        \n\t- Properly manage and administer their game server.\
                        \n\t- Ensure the privacy and security of collected data.\
                        \n\t- Retain game replays for a minimum of 30 days (if practical).\
                        \n\t- Not tamper with, or modify the game state in any way that may negatively affect the outcome of a match in progress.\
                        \n\nDo you agree to these terms and conditions? (y/n): ")
            if agree in ['y', 'Y']:
                pass
            else:
                LOGGER.fatal("You must agree to the terms and conditions to use HoNfigurator. If there are any questions, you may reach out to me on Discord (https://discordapp.com/users/197967989964800000).")
                input("Press ENTER to exit.")
                exit()
            while True:
                value = input(
                    "\n\t43 second guide: https://www.youtube.com/watch?v=ZPROrf4Fe3Q\n\tPlease provide your discord user ID: ")
                try:
                    discord_id = int(value)
                    if len(str(discord_id)) < 10:
                        raise ValueError
                    self.database.add_default_data(discord_id=discord_id)
                    if "discord" in self.application_data:
                        self.application_data["discord"]["owner_id"] = discord_id
                    break
                except ValueError:
                    print(
                        "Value must be a more than 10 digits.")

        if not os.path.exists(self.config_file_hon):
            if args:
                if args.hon_install_directory:
                    self.hon_data["hon_install_directory"] = Path(
                        args.hon_install_directory)
            await self.create_hon_configuration_file(
                detected="hon_install_directory")
                    
        # Load configuration from config file
        try:
            self.hon_data = self.get_existing_configuration()['hon_data']
            self.application_data = self.get_existing_configuration()[
                'application_data']
        except KeyError:  # using old config format
            self.hon_data = self.get_existing_configuration()
        
        if "discord" in self.application_data:
            if int(self.database.get_discord_owner_id()) != self.application_data["discord"]["owner_id"]:
                if self.application_data["discord"]["owner_id"] == 0:
                    self.application_data["discord"]["owner_id"] = self.database.get_discord_owner_id()
                else:
                    self.database.update_discord_owner_id(self.application_data["discord"]["owner_id"])

        self.full_config = self.merge_config()
        if await self.validate_hon_data(self.full_config['hon_data'], self.full_config['application_data']):
            return True
        else:
            return False

    def create_logging_configuration_file(self):
        with open(str(self.config_file_logging), 'w') as config_file_logging:
            json.dump(self.get_default_logging_configuration(),
                      config_file_logging, indent=4)

    async def create_hon_configuration_file(self, detected=None):
        while True:
            basic = input(
                "\nWould you like to use mostly defaults or complete advanced setup? (y - defaults / n - advanced): ")
            if basic in ['y', 'n', 'Y', 'N']:
                if basic in ['n','N']:
                    print("Please provide the following information for the initial setup:\nJust press ENTER if the default value is okay.")
                break
            print("Please provide 'y' for default settings or 'n' for advanced settings.")

        for key, value in self.hon_data.items():
            if basic in ['y', 'Y'] and (value or value == False):
                continue
            if key == "svr_name" and self.hon_data['svr_location'] != "TH": # skip server name as it's auto generated
                continue
            while True:
                if key == "svr_password":
                    user_input = getpass(
                        f"\tEnter the value for '{key}' (HINT: HoN Password): ")
                elif key == "svr_login":
                    user_input = input(
                        f"\tEnter the value for '{key}' (HINT: HoN Username): ")
                elif detected == key:
                    user_input = input("\tEnter the value for '{}'{}: ".format(
                        key, " (detected: {})".format(value) if value or value == False else ""))
                else:
                    user_input = input("\tEnter the value for '{}'{}: ".format(
                        key, " (default: {})".format(value) if value or value == False else ""))
                if user_input:
                    default_value_type = type(value)
                    new_value_type = type(user_input)

                    if new_value_type == int:
                        try:
                            self.hon_data[key] = int(user_input)
                            break
                        except ValueError:
                            print(
                                f"\tInvalid integer value entered for {key}. Using the default value: {value}")
                    elif new_value_type == bool:
                        self.hon_data[key] = user_input.lower() == 'true'
                        break
                    elif new_value_type == str:
                        if key == "svr_location":
                            if user_input not in ALLOWED_REGIONS:
                                print(
                                    f"\tIncorrect region. Can only be one of {(',').join(ALLOWED_REGIONS)}")
                                continue
                            else:
                                self.hon_data[key] = user_input
                                break
                        elif key in self.PATH_KEYS_IN_HON_DATA_CONFIG_FILE:
                            try:
                                user_input = user_input.replace("\"", "")
                                Path(user_input)
                                self.hon_data[key] = user_input
                                break
                            except Exception:
                                print(
                                    f"\tExpected valid file path. Please try again. Here is an example value: {self.hon_data[key]}")
                        else:
                            self.hon_data[key] = user_input
                            break
                    else:
                        print(
                            f"\tUnexpected value type ({new_value_type}) for {key}. Skipping this key.")
                else:
                    break
        self.hon_data['svr_name'] = await self.generate_server_name()
        self.server_name_generated = True
        if await self.validate_hon_data():
            return True
        return False

    def save_configuration_file(self):
        def update_nested_key_path_value(nested_dict, target_key):
            for key, value in nested_dict.items():
                if key == target_key:
                    # Convert the value to a string and update the dictionary
                    nested_dict[key] = str(value)
                elif isinstance(value, dict):
                    # If the value is a dictionary, search it recursively
                    update_nested_key_path_value(value, target_key)

        def are_dicts_equal_with_types(d1, d2):
            if d1.keys() != d2.keys():
                return False

            for key in d1:
                if type(d1[key]) != type(d2[key]) or d1[key] is not d2[key]:
                    return False

            return True

        hon_data_to_save = {key: value for key, value in self.hon_data.items() if key not in self.PATH_KEYS_NOT_IN_HON_DATA_CONFIG_FILE and key not in self.OTHER_CONFIG_EXCLUSIONS}
        application_data_to_save = self.application_data

        # ensure path objects are
        for path in self.PATH_KEYS_IN_HON_DATA_CONFIG_FILE:
            hon_data_to_save[path] = str(hon_data_to_save[path])
        for path in self.PATH_KEYS_IN_APP_DATA_CONFIG_FILE:
            update_nested_key_path_value(application_data_to_save, path)

        full_data_to_save = {"hon_data": hon_data_to_save,
                             "application_data": application_data_to_save}

        if Path(self.config_file_hon).exists():
            with open(self.config_file_hon, 'r') as config_file_hon:
                existing_config = json.load(config_file_hon)

            if are_dicts_equal_with_types(existing_config, full_data_to_save):
                return False

        with open(self.config_file_hon, 'w') as config_file_hon:
            json.dump(full_data_to_save, config_file_hon, indent=4)

        return True

    def merge_config(self):
        config = self.get_default_hon_configuration()
        config['system_data'] = self.add_miscellaneous_data()
        config['hon_data'].update(self.hon_data)
        config['application_data'].update(self.application_data)
        if MISC.get_os_platform() == "linux":
            for key in self.WINDOWS_SPECIFIC_CONFIG_ITEMS:
                if key in config['hon_data']:
                    del config['hon_data'][key]
        # else:
        #     for key in self.LINUX_SPECIFIC_CONFIG_ITEMS:
        #         if key in config['hon_data']:
        #             del config['hon_data'][key]
        return config

    def add_runtime_data(self):
        if MISC.get_os_platform() == "win32":
            hon_artefacts_directory = Path(
                self.hon_data['hon_home_directory']) / "Documents" / "Heroes of Newerth x64"
            hon_replays_directory = hon_artefacts_directory / "KONGOR" / "replays"
            hon_logs_directory = hon_artefacts_directory / "KONGOR" / "logs"
            executable = f"hon_x64"
            suffix = ".exe"
            file_name = f'{executable}{suffix}'
            architecture = "was-crIac6LASwoafrl8FrOa"
        else:  # this should be "linux"
            hon_artefacts_directory = Path(self.hon_data["hon_home_directory"])
            hon_replays_directory = hon_artefacts_directory / "KONGOR" / "replays"
            hon_logs_directory = hon_artefacts_directory / "KONGOR" / "logs"
            executable = "hon-x86_64-server_KONGOR"
            file_name = executable
            architecture = 'las-crIac6LASwoafrl8FrOa'

        self.hon_data['hon_artefacts_directory'] = hon_artefacts_directory
        self.hon_data['hon_replays_directory'] = hon_replays_directory
        self.hon_data['hon_logs_directory'] = hon_logs_directory
        self.hon_data['svr_ip'] = MISC.get_public_ip()
        self.hon_data['hon_executable_path'] = self.hon_data['hon_install_directory'] / file_name
        self.hon_data['hon_executable_name'] = file_name
        self.hon_data['svr_version'] = MISC.get_svr_version(
            self.hon_data['hon_executable_path'])
        self.hon_data['architecture'] = architecture

    def add_miscellaneous_data(self):
        return (
            {
                "cpu_count": MISC.get_cpu_count(),
                "cpu_name": MISC.get_cpu_name(),
                "total_ram": MISC.get_total_ram(),
                "server_total_allowed": MISC.get_total_allowed_servers(self.hon_data['svr_total_per_core']),
                "github_branch": MISC.get_github_branch()
            }
        )

    async def get_final_configuration(self):
        self.add_runtime_data()
        
        if await self.validate_hon_data():
            return self.merge_config()
        else:
            return False
        
    def resolve_state_code(self, ip_address):
        API_KEY = "6822fd77ae464cafb5ce4f3be425f1ad"
        try:
            response = requests.get(f'https://api.ipgeolocation.io/ipgeo?apiKey={API_KEY}&ip={ip_address}')
            response_data = response.json()

            # Extract the state from the response
            state_code = response_data.get('state_code', 'Unknown')

            if state_code in ['', 'Unknown']:
                state_code = response_data.get('country_name', 'Unknown')

            if not state_code:
                # Fallback: Make a second API call without the IP address as a query parameter
                response = requests.get(f'https://api.ipgeolocation.io/ipgeo?apiKey={API_KEY}')
                response_data = response.json()
                state_code = response_data.get('state_code', 'Unknown')
                if state_code in ['', 'Unknown']:
                    state_code = response_data.get('country_name', 'Unknown')

            return state_code
        except Exception as e:
            LOGGER.error(f"Failed to fetch or process data. Error: {str(e)}")
            return None

    def format_state(self, state):
        if state:
            # Remove whitespace, special characters, and punctuation
            formatted_state = re.sub(r'\W', '', state)
            return formatted_state
        else:
            LOGGER.warning("State information not available.")
            return None
    
    def format_discord_username(self, discord_username):
        # Remove special characters, whitespaces, and numbers
        cleaned_string = re.sub(r'[^A-Za-z]', '', discord_username)

        # Capitalize the first character
        cleaned_string = cleaned_string.capitalize()

        # Truncate the string after the eigth character
        cleaned_string = cleaned_string[:8]

        return cleaned_string
        
