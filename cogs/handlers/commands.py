import nest_asyncio
nest_asyncio.apply()
import traceback
import asyncio
import inspect
import re
from cogs.misc.logger import get_logger, get_script_dir, flatten_dict, print_formatted_text, get_home, get_misc
from cogs.misc.setup import SetupEnvironment
from cogs.handlers.events import stop_event
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.history import FileHistory
from columnar import columnar

script_dir = get_script_dir(__file__)
LOGGER = get_logger()
MISC = get_misc()
HOME_PATH = get_home()
CONFIG_FILE = HOME_PATH / "config" / "config.json"

def compute_sub_command_path(sub_commands, target_sub_command):
    if not target_sub_command:
        return []
    elif not sub_commands:
        return None
    else:
        for key, value in sub_commands.items():
            if key == target_sub_command[0]:
                sub_command_path = compute_sub_command_path(sub_commands[key], target_sub_command[1:])
                if sub_command_path is not None:
                    return [key] + sub_command_path
        return None

def compute_sub_command_depth(sub_commands, target_sub_command):
    if not sub_commands:
        return 0
    elif sub_commands == target_sub_command:
        return 1
    else:
        depths = []
        for key, value in sub_commands.items():
            if isinstance(value, dict):
                sub_command_depth = compute_sub_command_depth(value, target_sub_command)
                if sub_command_depth > 0:
                    depths.append(1 + sub_command_depth)
            elif value == target_sub_command:
                depths.append(1)
        if depths:
            return max(depths)
        else:
            return 0

def get_value_from_nested_dict(nested_dict, keys):
    current_dict = nested_dict
    for key in keys:
        if key in current_dict:
            current_dict = current_dict[key]
        else:
            return None
    return current_dict

def build_subcommands_with_help(subcommands, help_dict):
    result = {}
    for key, value in subcommands.items():
        if callable(value):
            result[key] = value
            result[key].help = help_dict.get(key, "No help available")
        elif isinstance(value, dict):
            result[key] = build_subcommands_with_help(value, help_dict.get(key, {}))
    return result

CONFIG_HELP = {
    "token": "Set the Discord bot token",
    "admin_username": "Set the admin username",
    "all": "test"
    # Add more help texts for other config keys
}


class Command:
    def __init__(self, name, usage, description, function=None, sub_commands=None, args=None, aliases=None):
        self.name = name
        self.usage = usage
        self.description = description
        self.function = function
        self.sub_commands = sub_commands or {}
        self.args = args or []
        self.aliases = aliases or []

    def get(self, key, default=None):
        return super().get(key, default)

class Commands:
    async def shutdown_subcommands(self):
        return self.generate_subcommands(self.cmd_shutdown_server)

    async def wake_subcommands(self):
        return self.generate_subcommands(self.cmd_wake_server)

    async def sleep_subcommands(self):
        return self.generate_subcommands(self.cmd_sleep_server)

    async def message_subcommands(self):
        return self.generate_subcommands(self.cmd_message_server)

    async def disconnect_subcommands(self):
        return self.generate_subcommands(self.disconnect)

    async def startup_servers_subcommands(self):
        return self.generate_subcommands(self.startup_servers)
    
    async def add_servers_subcommands(self):
        return self.generate_subcommands(self.add_servers)
    
    async def cow_subcommands(self):
        return self.generate_subcommands(self.cmd_cowmaster_fork)

    async def custom_command_subcommands(self):
        return self.generate_subcommands(self.cmd_custom_cmd)

    async def update_subcommands(self):
        branch_names = MISC.get_all_branch_names()
        sub_commands = {}
        for branch in branch_names:
            sub_commands[branch] = (lambda br: (lambda *cmd_args: asyncio.create_task(self.update_and_change_branch(br, *cmd_args))))(branch)
        return sub_commands

    async def config_commands(self):
        return self.generate_config_subcommands(self.global_config, self.set_config)

    def __init__(self, game_servers, client_connections, global_config, manager_event_bus, cowmaster):
        self.manager_event_bus = manager_event_bus
        self.game_servers = game_servers
        self.client_connections = client_connections
        self.global_config = global_config
        self.commands = {}
        self.setup = SetupEnvironment(CONFIG_FILE)
        self.cowmaster = cowmaster

    async def initialise_commands(self):
        self.commands = {
            "shutdown": Command("shutdown", description="Schedule shutdown one or ALL GameServers", usage="shutdown <GameServer# / ALL>", function=None, sub_commands=await self.shutdown_subcommands(), args=["force"], aliases=["shut"]),
            "wake": Command("wake", description="Wake up a GameServer", usage="wake <GameServer#>", function=None, sub_commands=await self.wake_subcommands()),
            "sleep": Command("sleep", description="Put a GameServer to sleep", usage="sleep <GameServer#>", function=None, sub_commands=await self.sleep_subcommands()),
            "message": Command("message", description="Send a message to a GameServer", usage="message <GameServer# / ALL> <message>", function=None, sub_commands=await self.message_subcommands(),args=["<type your message>"]),
            "command": Command("command", description="Initiate a command on a GameServer as if you were typing into the console.", usage="command <GameServer# / ALL> <command>", function=None, sub_commands=await self.custom_command_subcommands()),
            "startup": Command("startup", description="Start 1 or more game servers", usage="startup <GameServer# / ALL>", function=None, sub_commands=await self.startup_servers_subcommands()),
            "addservers": Command("addservers", description="Add 1 or more game servers", usage="add <Num / ALL>", function=None, sub_commands=await self.add_servers_subcommands()),
            "status": Command("status", description="Show status of connected GameServers", usage="status", function=self.status, sub_commands={}),
            "reconnect": Command("reconnect", description="Close all GameServer connections, forcing them to reconnect", usage="reconnect", function=self.reconnect, sub_commands={}),
            "disconnect": Command("disconnect", description="Disconnect the specified GameServer. This only closes the network communication between the manager and game server, not shutdown.", usage="disconnect <GameServer# / ALL>", function=None, sub_commands=await self.disconnect_subcommands()),
            "setconfig": Command("setconfig", description="Set a configuration value for the server", usage="set config <config key> <config value>", function=None, sub_commands=await self.config_commands(),args=["force"]),
            "quit": Command("quit", description="Exit this program. Servers may terminate when they are no longer in a game.", usage="quit", function=self.quit),
            "help": Command("help", description="Show this help text", usage="help", function=self.help, sub_commands={}),
            "update": Command("update", description="Update this program from the upstream git repository.", usage="update", function=self.update, sub_commands=await self.update_subcommands()),
        }
    def generate_subcommands(self, command_coro):
        command_type = command_coro.__name__
        sub_commands = {"all": (lambda *cmd_args: asyncio.create_task(command_coro("all", *cmd_args)))}
        if command_type == "startup_servers":
            for game_server in list(self.game_servers.values()):
                if game_server.port not in list(self.client_connections):
                    sub_commands[str(game_server.id)] = (lambda gs: (lambda *cmd_args: asyncio.create_task(command_coro(gs, *cmd_args))))(game_server)
        else:
            for game_server in list(self.game_servers.values()):
                if game_server.port in list(self.client_connections):
                    sub_commands[str(game_server.id)] = (lambda gs: (lambda *cmd_args: asyncio.create_task(command_coro(gs, *cmd_args))))(game_server)
        sub_commands_with_help = build_subcommands_with_help(sub_commands, CONFIG_HELP)
        return sub_commands

    def generate_config_subcommands(self, config_dict, command_coro):
        sub_commands = {}

        for key, value in config_dict.items():
            if isinstance(value, dict):
                if key == "application_data" or key == "hon_data":
                    sub_commands[key] = self.generate_config_subcommands(value, command_coro)
                else:
                    continue
            else:
                if key == "application_data" or key == "hon_data":
                    continue
                sub_commands[key] = lambda *cmd_args: asyncio.ensure_future(command_coro(*cmd_args))
                sub_commands[key].current_value = value

        sub_commands_with_help = build_subcommands_with_help(sub_commands, CONFIG_HELP)
        return sub_commands_with_help


    async def generate_args_for_set_config(self, key, value, current_path=None):
        if current_path is None:
            current_path = []

        args_list = []
        new_path = current_path + [key]
        if isinstance(value, dict):
            args_list.extend(await self.generate_args_for_set_config(value, new_path))
        else:
            args_list.append(new_path + [value])

        return args_list

    async def set_config(self, args):
        keys = args[:-1]
        value = args[-1]

        current_dict = self.global_config
        for key in keys[:-1]:
            if key not in current_dict:
                print_formatted_text(f"Key '{key}' not found in the current dictionary")
            current_dict = current_dict.setdefault(key, {})

        last_key = keys[-1]
        if last_key not in current_dict:
            print_formatted_text(f"Key '{last_key}' not found in the current dictionary")

        old_value = current_dict.get(last_key)
        current_dict[last_key] = value

        # Update the current_value attribute for the corresponding sub_command
        sub_command = self.commands["setconfig"].sub_commands
        for key in keys:
            sub_command = sub_command[key]
        sub_command.current_value = value

        if await self.setup.validate_hon_data(self.global_config['hon_data']):
            print_formatted_text(f"Value for key '{last_key}' changed from {old_value} to {value}")
            LOGGER.info("Saved local configuration")
            # TODO: If command line arguments change, then schedule restart..
            LOGGER.info("Scheduling restart of servers to apply new configuration")
            if last_key == "svr_total":
                await self.manager_event_bus.emit('balance_game_server_count')
            elif last_key =="svr_max_start_at_once":
                await self.manager_event_bus.emit('update_server_start_semaphore')
            await self.manager_event_bus.emit('check_for_restart_required')
    async def update_and_change_branch(self, branch_name=None, *cmd_args):
        if branch_name:
            MISC.change_branch(branch_name)
        else:
            MISC.update_github_repository()

    async def handle_input(self):
        self.subcommands_changed = asyncio.Event()
        await self.initialise_commands()
        print_formatted_text("""    __  __      _   _______                        __
   / / / /___  / | / / __(_)___ ___  ___________ _/ /_____  _____
  / /_/ / __ \/  |/ / /_/ / __ `/ / / / ___/ __ `/ __/ __ \/ ___/
 / __  / /_/ / /|  / __/ / /_/ / /_/ / /  / /_/ / /_/ /_/ / /
/_/ /_/\____/_/ |_/_/ /_/\__, /\__,_/_/   \__,_/\__/\____/_/
                        /____/                                   """)
        await self.help()

        self.command_completer = CustomCommandCompleter(command_handlers=self.commands)
        self.history = FileHistory('.command_history')

        async def read_user_input(prompt, completer):
            session = PromptSession(completer=completer, history=self.history)
            return await session.prompt_async(prompt)


        while not stop_event.is_set():
            try:
                self.cmd_name = None
                command = None
                self.subcommands_changed.clear()

                prompt = '> '
                completer = self.command_completer

                input_future = asyncio.ensure_future(read_user_input(prompt, completer))
                subcommands_changed_future = asyncio.ensure_future(self.subcommands_changed.wait())
                done, pending = await asyncio.wait([input_future, subcommands_changed_future], return_when=asyncio.FIRST_COMPLETED)

                if input_future in done:
                    command = input_future.result()
                    print_formatted_text(f"Command received: {command}")
                    command_parts = command.strip().split()

                    if command_parts:
                        self.cmd_name = command_parts[0].lower()
                        cmd_args = command_parts[1:]

                        if self.cmd_name in self.commands:
                            command_obj = self.commands[self.cmd_name]

                            if cmd_args and cmd_args[0] in command_obj.sub_commands:
                                if self.cmd_name == "setconfig":
                                    handler = get_value_from_nested_dict(command_obj.sub_commands,cmd_args[:-1])
                                elif self.cmd_name == "message" or self.cmd_name == "command":
                                    handler = get_value_from_nested_dict(command_obj.sub_commands,cmd_args[:1])
                                else:
                                    handler = get_value_from_nested_dict(command_obj.sub_commands,cmd_args)
                            else:
                                handler = command_obj.function

                            try:
                                if handler:
                                    if self.cmd_name == "message" or self.cmd_name == "command" :
                                        # Pass the entire command_parts list as arguments to the handler
                                        future = handler(command_parts[2:])
                                    elif self.cmd_name == "setconfig":
                                        future = handler(command_parts[1:])
                                    else:
                                        future = handler()
                                    await future
                                elif command_obj.function is None:
                                    print_formatted_text("You must provide a subcommand for:", self.cmd_name)
                                else:
                                    print_formatted_text("Unknown subcommand:", cmd_args[0] if cmd_args else "")
                                await asyncio.sleep(0.05)
                                print_formatted_text()
                            except Exception as e:
                                error_message = f"Error: {traceback.format_exc()}"
                                print_formatted_text(error_message)
                                print_formatted_text("Command so far: " + command)

                # If subcommands_changed event is set, update the command completer with the new command handlers
                if self.subcommands_changed.is_set():
                    # await self.initialise_commands()
                    self.command_completer.update_command_handlers(self.commands)
            except Exception:
                print_formatted_text(traceback.format_exc())

        input_future.cancel()
        try:
            await input_future
        except asyncio.CancelledError:
            pass

    async def quit(self):
        stop_event.set()

    async def cmd_shutdown_server(self, game_server=None, force=False):
        try:
            if game_server is None: return
            elif game_server == "all":
                for game_server in list(self.game_servers.values()):
                    await self.manager_event_bus.emit('cmd_shutdown_server', game_server)
            else:
                await self.manager_event_bus.emit('cmd_shutdown_server', game_server)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, game_server=None):
        try:
            if game_server is None: return

            elif game_server == "all":
                for game_server in list(self.game_servers.values()):
                    await self.manager_event_bus.emit('cmd_wake_server', game_server)
            else:
                await self.manager_event_bus.emit('cmd_wake_server', game_server)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, game_server=None, force=False):
        try:
            if game_server is None: return

            elif game_server == "all":
                for game_server in list(self.game_servers.values()):
                    await self.manager_event_bus.emit('cmd_sleep_server', game_server)
            else:
                await self.manager_event_bus.emit('cmd_sleep_server', game_server)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_message_server(self, game_server=None, message=None):
        try:
            if game_server is None or message is None:
                print_formatted_text("Usage: message <GameServer#> <message>")
                return

            if game_server == "all":
                for game_server in list(self.game_servers.values()):
                    await self.manager_event_bus.emit('cmd_message_server', game_server, message)
            else:
                await self.manager_event_bus.emit('cmd_message_server', game_server, message)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_custom_cmd(self, game_server=None, command=None):
        try:
            if game_server is None or command is None:
                print_formatted_text("Usage: command <GameServer#> <command>")
                return
            
            if isinstance(command[0],str) and command[0].lower() not in ['message','terminateplayer','serverreset','flushserverlogs', 'givegold', 'giveexp']:
                LOGGER.warn("Command disallowed")
                return
            if game_server == "all":
                for game_server in list(self.game_servers.values()):
                    await self.manager_event_bus.emit('cmd_custom_command', game_server, command)
                return

            await self.manager_event_bus.emit('cmd_custom_command', game_server, command)

        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def cmd_cowmaster_fork(self, num="all"):
        # TODO: Change above back to num=none
        if num == "none":
            LOGGER.warn(self.commands['cowmaster-forkserver']['usage'])
        if num == "all":
            # logic to fork all servers
            LOGGER.info("Forking all available servers")
            await self.manager_event_bus.emit('start_gameserver_from_cowmaster', num)
        else:
            # logic to fork specific number of servers
            num_servers = int(num)
            LOGGER.info(f"Forking {num_servers} servers...")
            await self.manager_event_bus.emit('start_gameserver_from_cowmaster', num)
        # Add your actual logic to fork the servers here

    async def disconnect(self, *cmd_args):
        try:
            if len(cmd_args) < 1:
                print_formatted_text("Usage: disconnect <GameServer#>")
                return
            game_server =next((gs for gs in list(self.game_servers.values()) if gs.id == int(cmd_args[0])), None)
            client_connection = self.client_connections[game_server.port]
            await client_connection.close()
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def startup_servers(self,game_server):
        if game_server == "all":
            await self.manager_event_bus.emit('start_game_servers', 'all')
        else:
            await self.manager_event_bus.emit('start_game_servers', [game_server])
    
    async def add_servers(self,game_server):
        if game_server == "all":
            await self.manager_event_bus.emit('balance_game_server_count', 'all')
        else:
            LOGGER.info("not yet implemented")

    async def shutdown_servers(self,game_server):
        if game_server == "all":
            for game_server in list(self.game_servers.values()):
                await game_server.disable_server()
        else:
            await game_server.disable_server()

    async def status(self):
        try:
            if self.global_config['hon_data'].get('man_use_cowmaster') and self.cowmaster:
                if self.cowmaster.client_connection:
                    print_formatted_text("Cowmaster is in use. Cowmaster connected.")
                else:
                    print_formatted_text("Cowmaster is in use. Cowmaster NOT connected.")
            if len(self.game_servers) == 0:
                print_formatted_text("No GameServers connected.")
                return

            headers = []
            rows = []
            for game_server in list(self.game_servers.values()):
                status = game_server.get_pretty_status()
                flattened_status = status
                data = []
                for k, v in flattened_status.items():
                    if k not in headers:
                        headers.append(k)
                    if isinstance(v, dict):
                        # Flatten nested dict into a string
                        v = '\n'.join([f'{sub_k}: {sub_v}' for sub_k, sub_v in v.items()])
                    data.append(v)
                rows.append(data)

            table = columnar(rows, headers=headers)
            print_formatted_text(table)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")


    async def reconnect(self):
        try:

            for connection in list(self.client_connections.values()):
                await connection.close()
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def help(self):
        try:
            headers = ["Command", "Description"]
            rows = []
            for command in self.commands.values():
                rows.append([command.usage,command.description])
            table = columnar(rows, headers=headers)
            print_formatted_text(table)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def update(self):
        await self.manager_event_bus.emit('update')


from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI

class CustomCommandCompleter(Completer):
    def __init__(self, command_handlers, **kwargs):
        self.commands = command_handlers
        self.last_sub_commands = []
        super().__init__(**kwargs)

    def update_command_handlers(self, command_handlers):
        self.commands = command_handlers

    def get_completions(self, document, complete_event):
        try:
            words = document.text_before_cursor.lower().split()
            current_word = document.get_word_before_cursor()

            if '?' in current_word:
                # If "?" is present, return all possible commands
                for cmd_name, cmd_obj in self.commands.items():
                    yield Completion(cmd_name, start_position=-len(current_word), display_meta=cmd_obj.usage)
                return

            if len(words) > 1 or (current_word == '' and len(words) > 0):
                current_command = self.commands.get(words[0], None)
                if current_command is not None:
                    sub_command = current_command.sub_commands
                    if current_word == '':
                        self.last_sub_commands = []
                        for word in words[1:]:
                            if isinstance(sub_command, dict) and word in sub_command:
                                sub_command = sub_command[word]
                                self.last_sub_commands.append(word)
                            elif callable(sub_command) and word in current_command.args:
                                sub_command = None
                                break
                            else:
                                sub_command = None
                                break

                    if sub_command is not None:
                        if current_word.strip() == '':
                            if isinstance(sub_command, dict):
                                for subcommand in sub_command.keys():
                                    yield Completion(subcommand, start_position=0)
                            elif callable(sub_command):
                                if current_command.name == "setconfig":
                                    yield Completion(f"<current value: {sub_command.current_value}>", start_position=-len(current_word))
                                    yield Completion(f"<enter new value>", start_position=-len(current_word))
                                elif current_command.name == "shutdown":
                                    for arg in current_command.args:
                                        yield Completion(arg, start_position=-len(current_word))
                                    yield Completion(f"<default behaviour: schedule>",start_position=-len(current_word))
                                else:
                                    yield Completion(' -'.join(current_command.args), start_position=-len(current_word))
                        else:
                            temp_sub_command = sub_command
                            for prev_sub_command in self.last_sub_commands:
                                if isinstance(temp_sub_command, dict) and prev_sub_command in temp_sub_command:
                                    temp_sub_command = temp_sub_command[prev_sub_command]
                                else:
                                    temp_sub_command = None
                                    break
                            if temp_sub_command is not None:
                                if isinstance(temp_sub_command,dict):
                                    for subcommand in temp_sub_command.keys():
                                        if subcommand.lower().startswith(current_word.lower()):
                                            yield Completion(subcommand, start_position=-len(current_word))

                                elif callable(temp_sub_command):
                                    for arg in current_command.args:
                                        if arg.lower().startswith(current_word.lower()):
                                            yield Completion(arg, start_position=-len(current_word))

            # suggest top-level commands
            elif len(words) == 1 and current_word != '':
                if any(cmd_name.lower().startswith(current_word.lower()) for cmd_name in self.commands.keys()):
                    for cmd_name, cmd_obj in self.commands.items():
                        if cmd_name.lower().startswith(current_word.lower()):
                            yield Completion(cmd_name, start_position=-len(current_word), display_meta=cmd_obj.usage)
            else:
                self.last_sub_commands = []
        except Exception:
            LOGGER.exception(traceback.format_exc())
