import struct
import asyncio
import traceback
import inspect
from cogs.misc.logging import get_logger

LOGGER = get_logger()

class ChatServerHandler:
    def __init__(self, chat_address, chat_port, session_id, server_id, udp_ping_responder_port):
        self.chat_address = chat_address
        self.chat_port = chat_port
        self.session_id = session_id
        self.server_id = server_id
        self.udp_ping_responder_port = udp_ping_responder_port
        self.server = None
        self.reader = None
        self.writer = None
        self.keepalive_task = None

    async def connect(self):
            try:
                self.reader, self.writer = await asyncio.open_connection(self.chat_address, self.chat_port)

                # Send handshake packet with session ID
                handshake_packet = self.create_handshake_packet(self.session_id, self.server_id)
                self.writer.write(handshake_packet)
                await self.writer.drain()

                # Receive response
                auth_response = await self.reader.read(1024)
                msg_len, msg_type, packet_data = self.parse_packet(auth_response)
                auth_result = await self.handle_received_packet(msg_len, msg_type, auth_response)
                return auth_result

            except ConnectionRefusedError:
                LOGGER.warn("Connection refused by the chat server. Retrying in 10 seconds...")
                await asyncio.sleep(10)
            except OSError as e:
                LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    async def handle_packets(self):
        # Wait until we are connected to the chat server before starting to handle packets
        while not self.reader:
            await asyncio.sleep(0.1)

        # Handle packets until the connection is closed
        while not self.reader.at_eof():
            data = await self.reader.read(4096)
            if len(data) == 0:
                LOGGER.warn("Connection closed by the server.")
                break

            msg_len, msg_type, packet_data = self.parse_packet(data)
            await self.handle_received_packet(msg_len, msg_type, packet_data)

    def create_handshake_packet(self, session_id, server_id):
        msg_type = 0x1600
        packet = struct.pack('<H', msg_type) + struct.pack('<I', self.server_id) + self.session_id.encode('utf-8') + b'\x00' + struct.pack('<I', 70)
        msg_len = len(packet)
        packet = struct.pack('<H', msg_len) + packet

        LOGGER.debug(f">>> Sending Handshake packet to ChatServer\n\tSession ID: {session_id}\n\tServer ID: {server_id}")
        return packet
    
    def create_server_info_packet(self, server_id, username, region, server_name, version, ip_addr, udp_ping_responder_port):
        msg_type = 0x1602
        packet_data = struct.pack('<H', msg_type)
        packet_data += int.to_bytes(server_id,4,byteorder='little')
        packet_data += username.encode('utf-8') + b'\x00'
        packet_data += region.encode('utf-8') + b'\x00'
        packet_data += server_name.encode('utf-8') + b'\x00'
        packet_data += version.encode('utf-8') + b'\x00'
        packet_data += ip_addr.encode('utf-8') + b'\x00'
        packet_data += int.to_bytes(udp_ping_responder_port,2,byteorder='little')
        packet_data += b'\x00' #    0 = running, 1 = shutting down
        packet_len = len(packet_data)
        len_packet = struct.pack('<H', packet_len)
        LOGGER.debug(f">>> Sending manager information to chat server\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Address: {ip_addr}\n\tAuto-Ping Port: {udp_ping_responder_port}")
        return len_packet, packet_data
    
    def parse_packet(self, data):
        msg_len = int.from_bytes(data[0:2], byteorder='little')
        msg_type = int.from_bytes(data[2:4], byteorder='little')
        if len(data) > 4:
            data = data[4:]
        return msg_len, msg_type, data

    async def close_connection(self):
        if self.writer:
            try:
                #   TODO: Check correct termination message
                self.writer.write(b'\x03\x00')
                await self.writer.drain()
            except ConnectionResetError:
                pass
            finally:
                self.writer.close()
                await self.writer.wait_closed()


    async def receive_packets(self):
        while True:
            try:
                data = await self.reader.read(4096)
                if len(data) == 0:
                    LOGGER.error("Connection closed by the server.")
                    break

                msg_len, msg_type, packet_data = self.parse_packet(data)
                await self.handle_received_packet(msg_len, msg_type, packet_data)

            except asyncio.CancelledError:
                LOGGER.error("Packet receiving task cancelled.")
                break
            except Exception:
                LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
                break

    async def handle_received_packet(self, msg_len, msg_type, data):
        if msg_type == 0x1700:
            LOGGER.debug(f"<<< Handshake accepted by the chat server.")
            len, server_info_packet = self.create_server_info_packet(self.server_id, "AUSFRANKHOST:", "NEWERTH", "T4NK 0", "4.10.6.0", "103.193.80.121", self.udp_ping_responder_port)
            self.writer.write(len)
            await self.writer.drain()
            self.writer.write(server_info_packet)
            await self.writer.drain()

            # start a timer to send two packets every 15 seconds
            async def send_keepalive():
                while True:
                    try:
                        await asyncio.sleep(15)
                        self.writer.write(b'\x02\x00')
                        await self.writer.drain()
                        self.writer.write(b'\x00*')
                        await self.writer.drain()
                    except ConnectionResetError:
                        break

            asyncio.create_task(send_keepalive())
            return True
        elif msg_type == 0x2a01:
            pass
        elif msg_type == 0x0400:
            LOGGER.debug("<<< Received chat server shutdown notice.")
            asyncio.create_task(self.close_connection())


    def close(self):
        if self.server:
            self.server.close()