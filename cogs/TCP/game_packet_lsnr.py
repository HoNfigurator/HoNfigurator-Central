import traceback
import asyncio
import inspect
import struct
import socket
from cogs.TCP.packet_parser import GameManagerParser
from cogs.handlers.events import stop_event
from cogs.misc.logger import get_logger

LOGGER = get_logger()

class ClientConnection:
    def __init__(self, reader, writer, addr, game_server_manager):
        self.reader = reader
        self.writer = writer
        self.addr = addr
        self.game_server = None
        self.game_server_manager = game_server_manager
        self.closed = False
        self.id = None

        # Set TCP keepalive on the socket
        sock = self.writer.get_extra_info('socket')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

    def set_game_server(self,game_server):
        self.game_server = game_server
        self.id = game_server.id

    async def receive_packet(self, timeout=600):
        try:
            # Try to read up to 2 bytes for the length field
            length_bytes = await asyncio.wait_for(self.reader.readexactly(2), timeout)

            # If we didn't receive exactly 2 bytes, return None
            if len(length_bytes) != 2:
                LOGGER.warn(f"Client #{self.id} Incomplete packet length: {length_bytes} received.")
                return None

            # Otherwise, proceed to read the rest of the packet
            length = int.from_bytes(length_bytes, byteorder='little')
            # Wait for the next `length` bytes to get the packet data
            data = await asyncio.wait_for(self.reader.readexactly(length), timeout)

            packet = (length, data)
            return packet

        except asyncio.TimeoutError as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            # Raise a timeout error if the packet did not arrive within the specified timeout
            raise TimeoutError("Packet reception timed out")

        except ConnectionResetError as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

            # Check if the writer object is not None before closing it
            if self.writer != None:
                await self.writer.close()

        except ValueError as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            return None

    async def run(self, game_server):
        self.game_server = game_server
        while not stop_event.is_set():
            try:
                packet = await self.receive_packet()

                if packet is None:
                    # Handle the case where the packet is incomplete
                    LOGGER.warn(f"Client #{self.id} Incomplete packet: {packet}. Closing connection..")
                    await self.close()
                    return

            except TimeoutError as e:
                LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                # Packet reception timed out
                LOGGER.info(f"{self.id} Packet reception timed out")
                continue
            except asyncio.exceptions.IncompleteReadError:
                LOGGER.warn(f"Client #{self.id} Incomplete packet received. Closing connection..")
                await self.close()
                return
            except Exception as e:
                LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                break

            await self.game_server.game_manager_parser.handle_packet(packet,self.game_server)

            # Add a small delay to allow other clients to send packets
            await asyncio.sleep(0.01)
        await self.close()

    async def send_packet(self, packet):
        try:
            if not self.writer.is_closing():
                data = bytes(packet)
                self.writer.write(data)
                await self.writer.drain()
        except Exception as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while sending a packet: {traceback.format_exc()}")

    async def close(self):
        if not self.closed:
            self.closed = True
            LOGGER.warn(f"Terminating client #{self.id}..")
            self.writer.close()
            await self.writer.wait_closed()

        try:
            if self.game_server is not None:
                self.game_server.save_gamestate_to_file()
                await self.game_server_manager.remove_client_connection(self)
        except Exception as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
async def handle_client_connection(client_reader, client_writer, game_server_manager):
    # Get the client address
    client_addr = client_writer.get_extra_info("peername")

    LOGGER.debug(f"Client connected from {client_addr[0]}:{client_addr[1]}")

    # Create a new ClientConnection object to handle this client
    client_connection = ClientConnection(client_reader, client_writer, client_addr, game_server_manager)

    try:
        # Wait for the server hello packet
        packets = await client_connection.receive_packet()

        if packets is None:
            # Handle the case where the packet is incomplete
            LOGGER.warn(f"Incomplete packet received from {client_addr[0]}:{client_addr[1]}")
            return

        if packets[1][0] != 0x40:
            LOGGER.info(f"Waiting for server hello from {client_addr[0]}:{client_addr[1]}...")
            return

        # Process the server hello packet
        game_server_port = await GameManagerParser.server_announce(None,packets[1])

        # Get or create the game server
        game_server = game_server_manager.get_game_server_by_port(game_server_port)
        if game_server is None:
            game_server = game_server_manager.create_game_server(game_server_port)
            await game_server.get_running_server()

        # register the client connection in the game server manager
        await game_server_manager.add_client_connection(client_connection,game_server_port)

        # register the game server in the client connection
        client_connection.set_game_server(game_server)

        # Run the client connection coroutine
        await client_connection.run(game_server)

    except (ConnectionResetError, asyncio.exceptions.IncompleteReadError, asyncio.CancelledError) as e:
        LOGGER.exception(f"Client #{client_connection.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
        # Connection closed by client, server, or incomplete packet received

    finally:
        # Don't forget to unregister the client connection in the `finally` block
        # if a server doesn't send a server hello, then the connection will also be removed.
        await game_server_manager.remove_client_connection(client_connection)
        await client_connection.close()

async def handle_clients(client_reader, client_writer, game_server_manager):
     try:
         await handle_client_connection(client_reader, client_writer, game_server_manager)
     except Exception as e:
         LOGGER.exception(f"An error occurred in the task for client {client_writer.get_extra_info('peername')}: {e}")
