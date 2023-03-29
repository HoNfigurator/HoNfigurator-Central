import asyncio
import nest_asyncio
nest_asyncio.apply()
from cogs.misc.logging import get_logger, get_script_dir, flatten_dict, print_formatted_text
import inspect
import traceback
import re
from columnar import columnar
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.shortcuts import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

script_dir = get_script_dir(__file__)
LOGGER = get_logger()

class Commands:
    def __init__(self,game_servers,client_connections,global_config,send_svr_command_callback):
        self.game_servers = game_servers
        self.client_connections = client_connections
        self.send_svr_command_callback = send_svr_command_callback
        self.global_config = global_config
        self.command_handlers = {
            "shutdown": {
                "function": self.cmd_shutdown_server,
                "help": "Schedule shutdown one or ALL GameServers",
                "subcommands": {
                    "all": {
                        "function": self.cmd_shutdown_server,
                        "help": "Shutdown all GameServers"
                    },
                    # dynamically generate a list of sub commands based on the total number of game_servers
                    "<game server id>": {
                        "function": self.cmd_shutdown_server,
                        "help": "Shutdown a specific GameServer by ID"
                    },
                }
            },
            "wake": {
                "function": self.cmd_wake_server,
                "help": "Wake up a GameServer",
                "subcommands": {
                    "<game server id>": {"function": self.cmd_wake_server, "help": "Wake up a specific GameServer by ID"},
                }
            },
            "sleep": {
                "function": self.cmd_sleep_server,
                "help": "Put a GameServer to sleep",
                "subcommands": {
                    "<game server id>": {"function": self.cmd_sleep_server, "help": "Put a specific GameServer to sleep by ID"},
                }
            },
            "message": {
                "function": self.cmd_server_message,
                "help": "Send a message to a GameServer",
                "subcommands": {
                    "<game server id>": {"function": self.cmd_server_message, "help": "Send a message to a specific GameServer by ID"},
                    "<message>": {"function": self.cmd_server_message, "help": "The message to send to the GameServer"},
                }
            },
            "cmd": {
                "function": self.cmd_custom_cmd,
                "help": "Send data to a GameServer",
                "subcommands": {
                    "<game server id>": {"function": self.cmd_custom_cmd, "help": "Send data to a specific GameServer by ID"},
                    "<data>": {"function": self.cmd_custom_cmd, "help": "The data to send to the GameServer"},
                }
            },
            "status": {
                "function": self.status,
                "help": "Show status of connected GameServers",
                "subcommands": {}
            },
            "reconnect": {
                "function": self.reconnect,
                "help": "Close all GameServer connections, forcing them to reconnect",
                "subcommands": {}
            },
            "disconnect": {
                "function": self.disconnect,
                "help": "Disconnect the specified GameServer. This only closes the network communication between the manager and game server, not shutdown.",
                "subcommands": {
                    "<game server id>": {"function": self.disconnect, "help": "Disconnect a specific GameServer by ID"},
                }
            },
            "help": {
                "function": self.help,
                "help": "Show this help text",
                "subcommands": {}
            },
        }
        # Set up command completer and history
        self.command_completer = CustomCommandCompleter(command_handlers=self.command_handlers)
        self.history = FileHistory('.command_history')
    
    async def handle_input(self, stop_event):
        print_formatted_text(r'''    __  __           _   __    ____    _                                     __                
   / / / /  ____    / | / /   / __/   (_)   ____ _  __  __   _____  ____ _  / /_  ____    _____
  / /_/ /  / __ \  /  |/ /   / /_    / /   / __ `/ / / / /  / ___/ / __ `/ / __/ / __ \  / ___/
 / __  /  / /_/ / / /|  /   / __/   / /   / /_/ / / /_/ /  / /    / /_/ / / /_  / /_/ / / /    
/_/ /_/   \____/ /_/ |_/   /_/     /_/    \__, /  \__,_/  /_/     \__,_/  \__/  \____/ /_/     
                                         /____/                                                
''')
        await self.help()
        while not stop_event.is_set():
            # Create custom key bindings
            bindings = KeyBindings()

            @bindings.add(Keys.Backspace)
            def _(event):
                if event.current_buffer.text:
                    event.current_buffer.delete_before_cursor()
            # Use prompt_toolkit to get user input
            session = PromptSession("> ", completer=self.command_completer, complete_while_typing=True, history=self.history)
            command = await asyncio.get_event_loop().run_in_executor(None, session.prompt)
            try:
                # Split the input into command name and arguments
                command_parts = command.strip().split()
                if not command_parts:
                    # print_formatted_text("> ", end="")
                    continue  # Skip if command is empty
                self.cmd_name = command_parts[0].lower()
                cmd_args = command_parts[1:]

                if self.cmd_name == "quit":
                    stop_event.set()
                    break
                elif self.cmd_name in self.command_handlers:
                    handler = self.command_handlers[self.cmd_name]["function"]
                    await handler(*cmd_args)
                else:
                    print_formatted_text("Unknown command:", self.cmd_name)

            except Exception as e:
                LOGGER.exception("An error occurred while handling the command: %s", e)
    
    async def cmd_shutdown_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                print_formatted_text("Usage: shutdown <GameServer# / ALL>")
                return

            length_bytes = b'\x01\x00'
            message_bytes = b'"'
            packets=(length_bytes,message_bytes)
            if cmd_args[0].lower() == "all":
                for game_server in list(self.game_servers.values()):
                    await self.send_svr_command_callback(self.cmd_name, game_server.port, (length_bytes,message_bytes))             
                    LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
            else:
                game_server =next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
                await self.send_svr_command_callback(self.cmd_name, game_server.port, (length_bytes,message_bytes))
                LOGGER.info(f"Command - Shutdown packet sent to GameServer #{game_server.id}. Scheduled.")
            #await self.send_svr_command_callback(game_server.port, (length_bytes,message_bytes))

        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                print_formatted_text("Usage: wake <GameServer#>")
                return
            game_server =next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            length_bytes = b'\x01\x00'
            message_bytes = b'!'
            await self.send_svr_command_callback(self.cmd_name, game_server.port, (length_bytes,message_bytes))
            LOGGER.info(f"Command - Wake packet sent to GameServer #{game_server.id}")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                print_formatted_text("Usage: sleep <GameServer#>")
                return
            game_server =next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            length_bytes = b'\x01\x00'
            message_bytes = b' '
            await self.send_svr_command_callback(self.cmd_name, game_server.port, (length_bytes,message_bytes))
            LOGGER.info(f"Command - Sleep packet sent to GameServer #{game_server.id}")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_server_message(self, *cmd_args):
        try:
            if len(cmd_args) < 2:
                print_formatted_text("Usage: message <GameServer#> <message>")
                return
            game_server =next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            message = ' '.join(cmd_args[1:])
            message_bytes = b'$' + message.encode('ascii') + b'\x00'
            length = len(message_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')
            await self.send_svr_command_callback(self.cmd_name, game_server.port, (length_bytes,message_bytes))
            LOGGER.info(f"Command - Message packet sent to GameServer #{game_server.id}")
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def cmd_custom_cmd(self, *cmd_args):
        try:
            if len(cmd_args) < 2:
                print_formatted_text("Usage: cmd <GameServer#> <data>")
                return
            game_server = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            data = b''
            for part in cmd_args[1:]:
                if re.fullmatch(r'[0-9a-fA-F]+', part):
                    data += bytes.fromhex(part)
                else:
                    data += part.encode('ascii')
            await self.send_svr_command_callback(self.cmd_name, game_server.port, (data))
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def disconnect(self, *cmd_args):
        try:
            if len(cmd_args) < 1:
                print_formatted_text("Usage: disconnect <GameServer#>")
                return
            game_server =next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            client_connection = self.client_connections[game_server.port]
            await client_connection.close()
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def status(self):
        try:
            # Print status of all connected clients
            if len(self.game_servers) == 0:
                print_formatted_text("No GameServers connected.")
                return
            headers = []
            rows = []
            for game_server in self.game_servers.values():
                status = game_server.get_pretty_status()
                flattened_status = flatten_dict(status)
                data = []
                for k, v in flattened_status.items():
                    if k not in headers:
                        headers.append(k)
                    if k == "players":
                        # Split the list of players into chunks of 5 and join them with a new line character
                        players_chunks = [v[i:i+5] for i in range(0, len(v), 5)]
                        formatted_players = "\n".join(map(str, players_chunks))
                        data.append(formatted_players)
                    else:
                        data.append(v)
                rows.append(data)

            table = columnar(rows, headers=headers)
            print_formatted_text(table)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def reconnect(self):
        try:
            # Close all client connections, forcing them to reconnect
            for connection in list(self.client_connections.values()):
                await connection.close()
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def help(self):
        try:
            headers = ["Command", "Description"]
            rows = [
                ["list", "Show list of connected GameServers"],
                ["status", "Show status of connected GameServers"],
                ["sleep <GameServer#>", "Put a GameServer to sleep"],
                ["wake <GameServer#>", "Wake up a GameServer"],
                ["send <GameServer#> <data>", "Send data to a GameServer"],
                ["message <GameServer#> <message>", "Send a message to a GameServer"],
                ["shutdown <GameServer# / ALL>", "Schedule shutdown one or ALL GameServers"],
                ["reconnect", "Close all GameServer connections, forcing them to reconnect"],
                ["disconnect <GameServer#>", "Disconnect the specified GameServer.\nThis only closes the network communication between the manager and game server, not shutdown."],
                ["quit", "Quit the manager server. This may cause game servers to shutdown when they are out-of-game."],
                ["help", "Show this help text"],
            ]
            table = columnar(rows, headers=headers)
            print_formatted_text(table)
        except Exception as e:
            LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")


class CustomCommandCompleter(WordCompleter):
    def __init__(self, command_handlers, **kwargs):
        self.command_handlers = command_handlers
        words = self.extract_words_from_command_handlers()
        super().__init__(words, **kwargs)

    def extract_words_from_command_handlers(self):
        words = []

        for command, handler in self.command_handlers.items():
            words.append(command)

            subcommands = handler.get('subcommands', {})
            for subcommand in subcommands.keys():
                words.append(subcommand)

            arg_suggestions = handler.get('args', [])
            for suggestion in arg_suggestions:
                words.append(suggestion)

        return words

    def get_completions(self, document, complete_event):
        words = document.text_before_cursor.lower().split()
        current_word = document.get_word_before_cursor()

        if not words:
            for command in self.command_handlers.keys():
                yield Completion(command, start_position=-len(current_word))
        else:
            command = words[0]
            if command in self.command_handlers:
                subcommand_handlers = self.command_handlers[command].get('subcommands', {})
                if len(words) == 1 and current_word == '':
                    for subcommand in subcommand_handlers.keys():
                        yield Completion(subcommand, start_position=-len(current_word))
                else:
                    subcommand = words[1] if len(words) > 1 else current_word
                    if subcommand in subcommand_handlers:
                        arg_suggestions = subcommand_handlers[subcommand].get('args', [])
                        for suggestion in arg_suggestions:
                            if suggestion.lower().startswith(current_word.lower()):
                                yield Completion(suggestion, start_position=-len(current_word))
                    else:
                        for subcommand in subcommand_handlers.keys():
                            if subcommand.lower().startswith(current_word.lower()):
                                yield Completion(subcommand, start_position=-len(current_word))
            else:
                for completion in super().get_completions(document, complete_event):
                    yield completion