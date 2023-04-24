import socket
import asyncio
import traceback
from cogs.misc.logging import get_logger
from cogs.handlers.events import EventBus, stop_event

LOGGER = get_logger()

class AutoPingListener(asyncio.DatagramProtocol):
    """
    An asynchronous protocol that listens for AutoPing messages and sends back a response.
    Used to respond to upstream Master Server ping requests, for allocating the closest server to players.

    Args:
        port (int): The port on which to listen for AutoPing messages.
        server_name (str): The name of the game server.
        game_version (str): The version of the game server.

    Attributes:
        port (int): The port on which to listen for AutoPing messages.
        game_version (str): The version of the game server.
        server_name (str): The name of the game server.
        server_address (str): The IP address to bind the listener to.
        transport (asyncio.transports.DatagramTransport): The transport layer used for sending and receiving data.

    Methods:
        connection_made(transport): Called when the protocol is first connected to a transport layer.
        datagram_received(data, addr): Called when a datagram is received by the protocol.
        start_listener(): Coroutine to start the protocol and listen for incoming datagrams.
    """

    def __init__(self, config, port):
        self.config = config
        self.server_name = config["hon_data"]["svr_name"]
        self.port = port
        self.game_version = config["hon_data"]["svr_version"]
        self.server_address = '0.0.0.0'
        self.transport = None
        self.protocol = None
        self.message_size = 69 + len(self.server_name) + len(self.game_version)
        self.prepared_response = bytearray(self.message_size)
        self.prepared_response[42] = 0x01
        self.prepared_response[43] = 0x66
        self.prepared_response[46: 46 + len(self.server_name)] = self.server_name.encode()
        self.prepared_response[50 + len(self.server_name): 50 + len(self.server_name) + len(self.game_version)] = self.game_version.encode()

    def connection_made(self, transport):
        """
        Called when the protocol is first connected to a transport layer.

        Args:
            transport (asyncio.transports.DatagramTransport): The transport layer used for sending and receiving data.

        Returns:
            None
        """
        self.transport = transport
        LOGGER.info(f"[*] AutoPing Responder - Listening on {self.server_address}:{self.port} (REMOTE)")

    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_datagram_received(data, addr))

    async def handle_datagram_received(self, data, addr):
        """
        Called when a datagram is received by the protocol.

        Args:
            data (bytes): The data received in the datagram.
            addr (tuple): The address of the sender.

        Returns:
            None
        """
        try:
            if len(data) != 46:
                LOGGER.warn("Unknown message - wrong length")
                return
            if data[43] != 0xCA:
                LOGGER.warn("Unknown message - 43")
                return

            response = self.prepared_response.copy()
            response[44] = data[44]
            response[45] = data[45]

            # Send the response
            self.transport.sendto(response, addr)

        except Exception:
            LOGGER.exception(traceback.format_exc())

    async def start_listener(self):
        """
            Coroutine to start the protocol and listen for incoming datagrams.

            Returns:
            None
        """
        loop = asyncio.get_event_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: self,
            local_addr=(self.server_address, self.port)
        )

        while not stop_event.is_set():
            # TODO
            # Should we place a smaller sleep here? To stop "quit" command taking 10 sec
            await asyncio.sleep(10)

        self.transport.close()

    async def stop_listener(self):
        self.transport.close()
        self.event_bus.unsubscribe('datagram_received', self.handle_datagram_received)

