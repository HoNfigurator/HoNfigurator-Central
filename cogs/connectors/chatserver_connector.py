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
    async def connect(self, retry_interval=10, retry_attempts=3, connection_timeout=5):
        attempts = 0
        while attempts < retry_attempts:
            try:
                # Set a timeout for the connection attempt
                conn_task = asyncio.open_connection(self.chat_address, self.chat_port)
                self.reader, self.writer = await asyncio.wait_for(conn_task, timeout=connection_timeout)

                # Send multiple packets at once if needed
                packets = [self.create_handshake_packet(self.session_id, self.server_id)]
                for packet in packets:
                    self.writer.write(packet)
                await self.writer.drain()

                # The authentication response will now be handled by the handle_packets function
                return True

            except asyncio.TimeoutError:
                LOGGER.warn("Connection attempt timed out. Retrying...")
            except ConnectionRefusedError:
                LOGGER.warn("Connection refused by the chat server. Retrying...")
            except OSError as e:
                LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            except Exception:
                LOGGER.exception(f"An unexpected exception occured. {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
            attempts += 1
            await asyncio.sleep(retry_interval)

        return False

    async def handle_packets(self, packet_batch_size=10):
        # Wait until we are connected to the chat server before starting to handle packets
        while not self.reader:
            await asyncio.sleep(0.1)

        # Handle packets until the connection is closed
        while stop_event.is_set() or not self.reader.at_eof():
            try:
                # Read multiple packets at once
                packets = []
                for i in range(packet_batch_size):
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
                        packets.append((msg_len, msg_type, bytes(data)))

                # Handle packets in batches
                for packet in packets:
                    await self.handle_received_packet(*packet)

            except asyncio.IncompleteReadError:
                LOGGER.error(f"IncompleteReadError: {traceback.format_exc()}")
            except ConnectionResetError:
                LOGGER.error("Connection reset by the server.")
                break
            except Exception as e:
                LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")

    def create_handshake_packet(self, session_id, server_id):
        msg_type = 0x1600
        packet_data = struct.pack('<I', server_id) + session_id.encode('utf-8') + b'\x00' + struct.pack('<I', 70)
        packet_len = len(packet_data)
        packet = struct.pack('<H', msg_type) + struct.pack('<H', packet_len) + packet_data

        LOGGER.debug(f">>> [MGR|CHAT] [{hex(msg_type)}] Sending Handshake packet to ChatServer\n\tSession ID: {session_id}\n\tServer ID: {server_id}")
        return packet


    def create_server_info_packet(self, server_id, username, region, server_name, version, ip_addr, udp_ping_responder_port):
        msg_type = 0x1602
        packet_data = (
            int.to_bytes(server_id, 4, byteorder='little') +
            username.encode('utf-8') + b'\x00' +
            region.encode('utf-8') + b'\x00' +
            server_name.encode('utf-8') + b'\x00' +
            version.encode('utf-8') + b'\x00' +
            ip_addr.encode('utf-8') + b'\x00' +
            int.to_bytes(udp_ping_responder_port, 2, byteorder='little') +
            b'\x00'  # 0 = running, 1 = shutting down
        )
        packet_len = len(packet_data)
        packet = struct.pack('<H', msg_type) + struct.pack('<H', packet_len) + packet_data

        LOGGER.debug(f">>> [MGR|CHAT] [{hex(msg_type)}] Sending manager information to chat server\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Address: {ip_addr}\n\tAuto-Ping Port: {udp_ping_responder_port}")
        return packet

    async def create_replay_status_update_packet(self, match_id, account_id, status):
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
        """
        msg_type = 0x1603
        packet_data = (
            struct.pack('<H', msg_type) +
            int.to_bytes(match_id, 4, byteorder='little') +
            int.to_bytes(account_id, 4, byteorder='little') +
            int.to_bytes(status.value, 1, byteorder='little') +
            (b'\x00' if status.name == "UPLOAD_COMPLETE" else b'')
        )
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
                self.writer.write(b'\x03\x00')
                await self.writer.drain()
            except ConnectionResetError:
                pass

            async with self.writer:
                pass

    async def handle_received_packet(self, msg_len, msg_type, data):
        parsed = await self.manager_chat_parser.handle_packet(msg_type, msg_len, data, "receiving")
        handlers = {
            0x1700: self.handle_handshake,
            0x0400: self.handle_shutdown_notice,
            0x1504: self.handle_spectate_request,
            0x1704: self.handle_replay_request,
        }
        handler = handlers.get(msg_type)
        if handler:
            await handler(parsed)

    def close(self):
        if self.server:
            self.server.close()
