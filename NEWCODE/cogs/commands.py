import aioconsole
from cogs.custom_print import my_print, logger, get_script_dir, flatten_dict
import inspect
import traceback
import re
from columnar import columnar

script_dir = get_script_dir(__file__)

class Commands:
    def __init__(self,game_servers,client_connections,send_svr_command_callback):
        self.game_servers = game_servers
        self.client_connections = client_connections
        self.send_svr_command_callback = send_svr_command_callback
        self.command_handlers = {
            "shutdown": self.cmd_shutdown_server,
            "wake": self.cmd_wake_server,
            "sleep": self.cmd_sleep_server,
            "message": self.cmd_server_message,
            "cmd": self.cmd_custom_cmd,
            "status": self.status,
            "reconnect": self.reconnect,
            "disconnect": self.disconnect,
            "help": self.help
        }
    async def handle_input(self, stop_event):
        while not stop_event.is_set():
            command = await aioconsole.ainput("> ")
            try:
                # Split the input into command name and arguments
                command_parts = command.strip().split()
                if not command_parts:
                    print("> ", end="")
                    continue  # Skip if command is empty
                self.cmd_name = command_parts[0].lower()
                cmd_args = command_parts[1:]

                if self.cmd_name == "quit":
                    stop_event.set()
                    break
                elif self.cmd_name in self.command_handlers:
                    handler = self.command_handlers[self.cmd_name]
                    await handler(*cmd_args)
                else:
                    my_print("Unknown command:", self.cmd_name)

            except Exception as e:
                logger.exception("An error occurred while handling the command: %s", e)
    
    async def cmd_shutdown_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                my_print("Usage: shutdown <GameServer#>")
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            length_bytes = b'\x01\x00'
            message_bytes = b'"'
            packets=(length_bytes,message_bytes)
            await self.send_svr_command_callback(self.cmd_name, client.port, (length_bytes,message_bytes))
            #await self.send_svr_command_callback(client.port, (length_bytes,message_bytes))
            my_print(f"Shutdown packet sent to GameServer #{client.id}. Scheduled.")

        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_wake_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                my_print("Usage: wake <GameServer#>")
                return
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            length_bytes = b'\x01\x00'
            message_bytes = b'!'
            await self.send_svr_command_callback(self.cmd_name, client.port, (length_bytes,message_bytes))
            my_print(f"Wake packet sent to GameServer #{client.id}")
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_sleep_server(self, *cmd_args):
        try:
            if len(cmd_args) != 1:
                my_print("Usage: sleep <GameServer#>")
                return
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            length_bytes = b'\x01\x00'
            message_bytes = b' '
            await self.send_svr_command_callback(self.cmd_name, client.port, (length_bytes,message_bytes))
            my_print(f"Sleep packet sent to GameServer #{client.id}")
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def cmd_server_message(self, *cmd_args):
        try:
            if len(cmd_args) < 2:
                my_print("Usage: message <GameServer#> <message>")
                return
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            message = ' '.join(cmd_args[1:])
            message_bytes = b'$' + message.encode('ascii') + b'\x00'
            length = len(message_bytes)
            length_bytes = length.to_bytes(2, byteorder='little')
            await self.send_svr_command_callback(self.cmd_name, client.port, (length_bytes,message_bytes))
            my_print(f"Message packet sent to GameServer #{client.id}")
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def cmd_custom_cmd(self, *cmd_args):
        try:
            if len(cmd_args) < 2:
                my_print("Usage: cmd <GameServer#> <data>")
                return
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            data = b''
            for part in cmd_args[1:]:
                if re.fullmatch(r'[0-9a-fA-F]+', part):
                    data += bytes.fromhex(part)
                else:
                    data += part.encode('ascii')
            await self.send_svr_command_callback(self.cmd_name, client.port, (data))
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
    async def disconnect(self, *cmd_args):
        try:
            if len(cmd_args) < 1:
                my_print("Usage: disconnect <GameServer#>")
                return
            client = next((gs for gs in self.game_servers.values() if gs.id == int(cmd_args[0])), None)
            client_connection = self.client_connections[client.port]
            await client_connection.close()
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def status(self):
        try:
            # Print status of all connected clients
            if len(self.game_servers) == 0:
                my_print("No GameServers connected.")
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
                    data.append(v)
                rows.append(data)

            table = columnar(rows, headers=headers)
            my_print(table)
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def reconnect(self):
        try:
            # Close all client connections, forcing them to reconnect
            for connection in list(self.client_connections.values()):
                await connection.close()
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
    
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
                ["shutdown <GameServer#>", "Shutdown a GameServer"],
                ["reconnect", "Close all GameServer connections, forcing them to reconnect"],
                ["disconnect <GameServer#>", "Disconnect the specified GameServer.\nThis only closes the network communication between the manager and game server, not shutdown."],
                ["quit", "Quit the manager server. This may cause game servers to shutdown when they are out-of-game."],
                ["help", "Show this help text"],
            ]
            table = columnar(rows, headers=headers)
            my_print(table)
        except Exception as e:
            logger.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")