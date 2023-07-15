import traceback
import asyncio
import inspect
import struct
from enum import Enum
import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)
from cogs.TCP.packet_parser import ClientChatParser

class ChatServerHandler:
    def __init__(self,
                chat_address,
                chat_port,
                external_ip,
                cookie="",
                account_id = 0,
                session_auth_hash = "",
                chat_protocol_version = 68,
                operating_system = 129,
                os_major_version = 6,
                os_minor_version = 2,
                os_micro_version = 0,
                os_build_code = "wac",
                os_architecture = "x86_64",
                client_version_major = 4,
                client_version_minor = 10,
                client_version_micro = 8,
                client_version_hotfix = 0,
                last_known_client_state = 0,
                client_chat_mode_state = 0,
                client_region = "en",
                client_language = "en"):
        self.chat_address = chat_address
        self.chat_port = chat_port
        self.external_ip = external_ip
        self.cookie = cookie
        self.account_id = account_id
        self.session_auth_hash = session_auth_hash
        self.chat_protocol_version = chat_protocol_version
        self.operating_system = operating_system
        self.os_major_version = os_major_version
        self.os_minor_version = os_minor_version
        self.os_micro_version = os_micro_version
        self.os_build_code = os_build_code
        self.os_architecture = os_architecture
        self.client_version_major = client_version_major
        self.client_version_minor = client_version_minor
        self.client_version_micro = client_version_micro
        self.client_version_hotfix = client_version_hotfix
        self.last_known_client_state = last_known_client_state
        self.client_chat_mode_state = client_chat_mode_state
        self.client_region = client_region
        self.client_language = client_language
        
        self.server = None
        self.reader = None
        self.writer = None
        self.keepalive_task = None
        self.client_chat_parser = ClientChatParser()
        self.chat_connection_lost_event = asyncio.Event()

        self.replay_status = 0
        self.authenticated = False
        self.authentication_response_received = False
    
    def get_headers(self, data):
        """
        Extract 
        """
        msg_len = int.from_bytes(data[0:2], byteorder='little')
        msg_type = int.from_bytes(data[2:4], byteorder='little')
        return msg_len, msg_type, data
    
    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.chat_address, self.chat_port)

            # Connect to chat server
            handshake_packet = self.create_handshake_packet()
            await self.send_packet(handshake_packet)

            # The authentication response will now be handled by the handle_packets function
            return True
        except ConnectionRefusedError:
            print("Connection refused by the chat server.")
        except OSError as e:
            print(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")


    async def handle_packets(self):
        """
        Wait here and receive packets from the chat server
        """
        while not self.reader:
            await asyncio.sleep(0.1)

        # Handle packets until the connection is closed
        while not self.reader.at_eof():
            try:
                msg_len_data = await self.reader.read(2)
                if len(msg_len_data) < 2:
                    print("Connection closed by the chat server. For status updates check https://discord.com/channels/991034716360687637/1034679496990789692")
                    break
                msg_len = int.from_bytes(msg_len_data, byteorder='little')

                data = bytearray()
                while len(data) < msg_len:
                    chunk = await self.reader.read(msg_len - len(data))
                    if len(chunk) == 0:
                        print("Connection closed by the chat server. For status updates check https://discord.com/channels/991034716360687637/1034679496990789692")
                        break
                    data.extend(chunk)
                else:
                    msg_type = int.from_bytes(data[:2], byteorder='little')
                    await self.handle_received_packet(msg_len, msg_type, bytes(data))
            except asyncio.IncompleteReadError:
                print(f"IncompleteReadError: {traceback.format_exc()}")
            except ConnectionResetError:
                print("Connection reset by the server.")
                break

    def create_handshake_packet(self):
        msg_type = 0xC00
        # Start with the message type as a 2-byte integer (0xc00)
        packet_data = struct.pack('<H', msg_type)

        # Add the rest of the fields from the connect_request dictionary
        packet_data += int.to_bytes(self.account_id, 4, byteorder='little')
        packet_data += self.cookie.encode('utf-8') + b'\x00'
        packet_data += self.external_ip.encode('utf-8') + b'\x00'
        packet_data += self.session_auth_hash.encode('utf-8') + b'\x00'
        packet_data += int.to_bytes(self.chat_protocol_version, 4, byteorder='little')
        packet_data += self.operating_system.to_bytes(1, byteorder='little')
        packet_data += self.os_major_version.to_bytes(1, byteorder='little')
        packet_data += self.os_minor_version.to_bytes(1, byteorder='little')
        packet_data += self.os_micro_version.to_bytes(1, byteorder='little')
        packet_data += self.os_build_code.encode('utf-8') + b'\x00'
        packet_data += self.os_architecture.encode('utf-8') + b'\x00'
        packet_data += self.client_version_major.to_bytes(1, byteorder='little')
        packet_data += self.client_version_minor.to_bytes(1, byteorder='little')
        packet_data += self.client_version_micro.to_bytes(1, byteorder='little')
        packet_data += self.client_version_hotfix.to_bytes(1, byteorder='little')
        packet_data += self.last_known_client_state.to_bytes(1, byteorder='little')
        packet_data += self.client_chat_mode_state.to_bytes(1, byteorder='little')
        packet_data += self.client_region.encode('utf-8') + b'\x00'
        packet_data += self.client_language.encode('utf-8') + b'\x00'

        packet_len = len(packet_data)
        packet_data = struct.pack('<H', packet_len) + packet_data

        return packet_data

    async def create_client_replay_request_packet(self, replay_request):
        """
        Create a client replay request packet.
        """
        msg_type = 0xbe
        packet_data = struct.pack('<H', msg_type)  

        # Add the rest of the fields from the replay_request dictionary
        packet_data += int.to_bytes(replay_request['match_id'], 4, byteorder='little')
        packet_data += replay_request['file_format'].encode('utf-8') + b'\x00'

        packet_len = len(packet_data)
        packet_data = struct.pack('<H', packet_len) + packet_data

        self.replay_status = 0 # set this back to 0

        await self.send_packet(packet_data)

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
        parsed = await self.client_chat_parser.handle_packet(msg_type,msg_len,data,"receiving")
        if msg_type == 0xbf:
            self.replay_status = parsed['status']
        elif msg_type == 0x1c00:
            self.authenticated = True
            self.authentication_response_received = True
            print(f"Authenticated to chat server with status: {parsed}")
        elif msg_type == 0x1c01:
            self.authenticated = False
            self.authentication_response_received = True
            print(f"Failed to authenticate to chat server with status: {parsed}")


    async def send_packet(self,packet_data):
        try:
            await self.client_chat_parser.handle_packet(int.from_bytes(packet_data[2:4], byteorder='little'),packet_data[:2],packet_data[2:],"sending")
            self.writer.write(packet_data)
            await self.writer.drain()
            return True
        except ConnectionResetError:
            print("error", f"Failed to send request due to ConnectionReset")
            return False

    def close(self):
        if self.server:
            self.server.close()
