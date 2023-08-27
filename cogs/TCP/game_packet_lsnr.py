import traceback
import asyncio
import inspect
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
        self.cowmaster = None
        self.game_server_manager = game_server_manager
        self.closed = False
        self.id = None

    def set_game_server(self,game_server=None, cowmaster = None):
        self.game_server = game_server
        self.cowmaster = cowmaster
        if self.game_server:
            self.id = game_server.id
        else:
            self.id = cowmaster.id

    async def receive_packet(self, timeout=30):
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

        except ValueError as e:
            LOGGER.error(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            return None

    async def run(self, game_server=None, cowmaster=None, timeout=60):
        self.game_server = game_server
        self.cowmaster = cowmaster
        while not stop_event.is_set():
            try:
                packet = await self.receive_packet(timeout=timeout)

                if packet is None:
                    # Handle the case where the packet is incomplete
                    LOGGER.warn(f"Client #{self.id} Incomplete packet: {packet}. Closing connection..")
                    await self.close() # if packet is None (indicating an incomplete packet), log a warning, close the connection, and then return from the function
                    return

            except ConnectionResetError as e:
                LOGGER.error(f"Client #{self.id} Connection reset. The GameServer has disconnected from the Manager.")
                break # exit the loop and continue to the post loop actions (clear game state, close connection, etc)

            except asyncio.CancelledError as e:
                LOGGER.exception(f"Client #{self.id} Operation was cancelled while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                return

            except (asyncio.TimeoutError, TimeoutError) as e:
                LOGGER.error(f"Client #{self.id} Timeout. The connection has timed out between the GameServer and the Manager. {timeout} seconds without receiving any data. Shutting down Game Server.")
                if self.game_server:
                    # await self.game_server.schedule_task(self.game_server.tail_game_log_then_close(), 'orphan_game_server_disconnect')
                    await game_server.stop_server_exe(disable=False, kill=True)
                    await self.close()
                    await self.game_server_manager.start_game_servers([game_server], service_recovery=True)

                return # exit the loop and continue to the post loop actions (clear game state, close connection, etc)

            except asyncio.exceptions.IncompleteReadError:
                LOGGER.warn(f"Client #{self.id} Incomplete packet received. Closing connection..")
                await self.close()
                return # if packet is None (indicating an incomplete packet), log a warning, close the connection, and then return from the function

            except Exception as e:
                LOGGER.exception(f"Client #{self.id} An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                break # exit the loop and continue to the post loop actions (clear game state, close connection, etc)
            
            if self.game_server:
                await self.game_server.game_manager_parser.handle_packet(packet,game_server=self.game_server)
            else:
                await self.cowmaster.game_manager_parser.handle_packet(packet,cowmaster=self.cowmaster)

            # Add a small delay to allow other clients to send packets
            await asyncio.sleep(0.001)
        
        if self.game_server:
            self.game_server.reset_game_state() # clear the game server state object to indicate we've lost comms from this server.
        else:
            self.cowmaster.reset_cowmaster_state()
        await self.close()

    async def send_packet(self, packet, send_len=False):
        try:
            if not self.writer.is_closing():
                data = bytes(packet)
                if send_len:
                    length = len(data)
                    length_bytes = length.to_bytes(2, byteorder='little')
                    self.writer.write(length_bytes)
                self.writer.write(data)
                await self.writer.drain()
        except Exception as e:
            LOGGER.exception(f"Client #{self.id} An error occurred while sending a packet: {traceback.format_exc()}")

    async def close(self):
        if not self.closed:
            self.closed = True
            LOGGER.warn(f"Terminating client #{self.id}..")
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception as e:
                pass # it doesnt seem that wait_closed always works when called. We don't care as long as it's closed.

        try:
            if self.game_server or self.cowmaster:
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

        cowmaster = None
        game_server = None

        if packets is None:
            # Handle the case where the packet is incomplete
            LOGGER.warn(f"Incomplete packet received from {client_addr[0]}:{client_addr[1]}")
            return

        if packets[1][0] != 0x40:
            LOGGER.info(f"Waiting for server hello from {client_addr[0]}:{client_addr[1]}...")
            return

        # Process the server hello packet
        game_server_port = await GameManagerParser.server_announce(None,packets[1])

        # check if the connection is for the cowmaster
        if game_server_port == game_server_manager.cowmaster.get_port():
            cowmaster = game_server_manager.cowmaster
        
        else:
            # Get or create the game server
            game_server = game_server_manager.get_game_server_by_port(game_server_port)
            
            if game_server is None:
                # TODO: CowServer may not be in the game_servers dictionary, and be created here as game server
                # this shouldn't happen tho
                if game_server_port == game_server_manager.cowmaster.get_port():
                    LOGGER.error("CowMaster has connected or a server using CowMaster port")
                game_server = game_server_manager.create_game_server(game_server_port)

        # register the client connection in the game server manager
        await game_server_manager.add_client_connection(client_connection,game_server_port)

        # register the game server in the client connection and run the client connection coroutine
        if game_server:
            client_connection.set_game_server(game_server=game_server)
            await client_connection.run(game_server=game_server)
        elif cowmaster:
            client_connection.set_game_server(cowmaster=cowmaster)
            await client_connection.run(cowmaster=cowmaster)
        else:
            LOGGER.warn("Incoming connection is neither GameServer nor CowMaster")        

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
