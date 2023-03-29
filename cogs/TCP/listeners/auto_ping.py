import socket
import asyncio
import traceback
from cogs.misc.logging import get_logger

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

    def __init__(self, port, server_name, game_version):
        self.port = port
        self.game_version = game_version
        self.server_name = server_name
        self.server_address = '0.0.0.0'
        self.transport = None

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
            elif data[43] != 0xCA:
                LOGGER.warn("Unknown message - 43")
                return
            else:
                # Prepare the response
                response = bytearray(46)
                response[42] = 0x01  # unreliable flag
                response[43] = 0x66  # pong message type
                response.extend(self.server_name.encode())
                for i in range(4):  # 4 zeroes between name and version
                    response.append(0)
                response.extend(self.game_version.encode())
                for i in range(19):  # 19 zeroes after version
                    response.append(0)

                # Write the challenge. Set values in the response to something expected by the server.
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