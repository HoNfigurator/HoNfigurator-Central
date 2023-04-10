import traceback
import asyncio
import inspect
import struct
from enum import Enum
from cogs.misc.logging import get_logger
from cogs.handlers.events import stop_event
from cogs.TCP.packet_parser import ManagerChatParser

LOGGER = get_logger()

class ChatServerHandler:
    def __init__(self, chat_address, chat_port, session_id, server_id, username, version, region, server_name, ip_addr, udp_ping_responder_port, event_bus):
        self.manager_event_bus = event_bus
        self.manager_event_bus.subscribe('replay_status_update', self.create_replay_status_update_packet)
        self.chat_address = chat_address
        self.chat_port = chat_port
        self.session_id = session_id
        self.server_id = server_id
        self.username = f"{username}:"
        self.version = version
        self.region = region
        self.server_name = f"{server_name} 0"
        self.ip_addr = ip_addr
        self.udp_ping_responder_port = udp_ping_responder_port
        self.server = None
        self.reader = None
        self.writer = None
        self.keepalive_task = None
        self.manager_chat_parser = ManagerChatParser(LOGGER)

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.chat_address, self.chat_port)

            # Send handshake packet with session ID
            handshake_packet = self.create_handshake_packet(self.session_id, self.server_id)
            self.writer.write(handshake_packet)
            await self.writer.drain()

            # The authentication response will now be handled by the handle_packets function
            return True

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
        while stop_event.is_set() or not self.reader.at_eof():
            try:
                msg_len_data = await self.reader.read(2)
                if len(msg_len_data) < 2:
                    LOGGER.warn("Connection closed by the server.")
                    break
                msg_len = int.from_bytes(msg_len_data, byteorder='little')

                data = bytearray()
                while len(data) < msg_len:
                    chunk = await self.reader.read(msg_len - len(data))
                    if len(chunk) == 0:
                        LOGGER.warn("Connection closed by the server.")
                        break
                    data.extend(chunk)
                else:
                    msg_type = int.from_bytes(data[:2], byteorder='little')
                    await self.handle_received_packet(msg_len, msg_type, bytes(data))
            except asyncio.IncompleteReadError:
                LOGGER.error(f"IncompleteReadError: {traceback.format_exc()}")
            except ConnectionResetError:
                LOGGER.error("Connection reset by the server.")
                break

    def create_handshake_packet(self, session_id, server_id):
        msg_type = 0x1600
        packet = struct.pack('<H', msg_type) + struct.pack('<I', self.server_id) + self.session_id.encode('utf-8') + b'\x00' + struct.pack('<I', 70)
        msg_len = len(packet)
        packet = struct.pack('<H', msg_len) + packet

        LOGGER.debug(f">>> [MGR|CHAT] [{hex(msg_type)}] Sending Handshake packet to ChatServer\n\tSession ID: {session_id}\n\tServer ID: {server_id}")
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
        LOGGER.debug(f">>> [MGR|CHAT] [{hex(msg_type)}] Sending manager information to chat server\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Address: {ip_addr}\n\tAuto-Ping Port: {udp_ping_responder_port}")
        return len_packet, packet_data

    async def create_replay_status_update_packet(self,match_id,account_id,status):
        """
        int matchId = ReadInt(data, offset, out offset);
        int accountId = ReadInt(data, offset, out offset);
        UploadStatus status = (UploadStatus)ReadByte(data, offset, out offset);
        string? downloadLink = status switch
        {
            UploadStatus.AlreadyUploaded => ReadString(data, offset, out offset),
            UploadStatus.UploadComplete => ReadString(data, offset, out offset),
            _ => null
        };
        	b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x05'	- OK I have the replay
            b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x06'	- Uploading..
            b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x07\x00' - finished uploading
            

            b'\x0b\x00\x03\x16ac\x1c\x00\x80\x03\x00\x00\x01' - mine (for not found)
            b'\x0b\x00\x03\x16/\x9a\x1a\x00\x80\x03\x00\x00\x01' - working (for not found)
        """
        msg_type = 0x1603
        packet_data = struct.pack('<H', msg_type)
        packet_data += int.to_bytes(match_id,4,byteorder='little')
        packet_data += int.to_bytes(account_id,4,byteorder='little')
        packet_data += int.to_bytes(status.value,1,byteorder='little')
        if status.name == "UPLOAD_COMPLETE":
            packet_data = packet_data + b'\x00'
        msg_len = len(packet_data)
        packet_data = struct.pack('<H', msg_len) + packet_data
        try:
            # Send the packet to the chat server
            self.writer.write(packet_data)
            await self.writer.drain()
        except ConnectionResetError:
            LOGGER.error("Connection reset by the server.")
        

    def get_headers(self, data):
        msg_len = int.from_bytes(data[0:2], byteorder='little')
        msg_type = int.from_bytes(data[2:4], byteorder='little')
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

    async def handle_received_packet(self, msg_len, msg_type, data):
        parsed = await self.manager_chat_parser.handle_packet(msg_type,msg_len,data,"receiving")

        print_prefix = f"<<< [CHAT|MGR] - [{hex(msg_type)}] "
        if msg_type == 0x1700:
            LOGGER.debug(f"{print_prefix}Handshake accepted by the chat server.")
            len, server_info_packet = self.create_server_info_packet(self.server_id, username=self.username, region=self.region, server_name=self.server_name, version=self.version, ip_addr=self.ip_addr, udp_ping_responder_port=self.udp_ping_responder_port)
            self.writer.write(len)
            await self.writer.drain()
            self.writer.write(server_info_packet)
            await self.writer.drain()

            # start a timer to send two packets every 15 seconds
            async def send_keepalive():
                while not stop_event.is_set():
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
        elif msg_type == 0x0400:
            # shutdown notice
            asyncio.create_task(self.close_connection())
        elif msg_type == 0x1504:
            pass
        elif msg_type == 0x1704:
            # replay request
            await self.manager_event_bus.emit('handle_replay_request', parsed['match_id'], parsed['extension'], parsed['account_id'])


    def close(self):
        if self.server:
            self.server.close()
