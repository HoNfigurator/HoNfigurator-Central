import traceback
import inspect
import re
import asyncio
import struct
import datetime

def read_int(data, offset):
    val = int.from_bytes(data[offset:offset+4], byteorder='little')
    offset += 4
    return val, offset

def read_byte(data, offset):
    val = data[offset]
    offset += 1
    return val, offset

def read_string(data, offset):
    str, _, remaining_data = data[offset:].partition(b'\x00')
    offset += len(str) + 1
    return str.decode('utf-8'), offset

class GameManagerParser:
    def __init__(self, client_id,logger=None,mqtt=None):
        self.logger = logger
        self.mqtt = mqtt
        self.packet_handlers = {
            0x40: self.server_announce,
            0x41: self.server_closed,
            0x42: self.server_status,
            0x43: self.long_frame,
            0x44: self.lobby_created,
            0x45: self.lobby_closed,
            0x47: self.server_connection,
            0x49: self.cow_announce,
            0x4A: self.replay_update
        }
        self.id = client_id
    
    def publish_event(self, topic, data):
        if self.mqtt:
            self.mqtt.publish_json(topic, data)

    def log(self,level,message):
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(message)

    def update_client_id(self, new_id):
        self.id = new_id

    async def handle_packet(self, packet, game_server=None, cowmaster=None):
        packet_len, packet_data = packet
        packet_type = packet_data[0]

        if packet_len != len(packet_data):
            self.log("debug",f"GameServer #{self.id} - LEN DOESNT MATCH PACKET: {len} and {len(packet_data)}")

        # Retrieve the packet handler function based on the packet_type
        handler = self.packet_handlers.get(packet_type, self.unhandled_packet)

        # Call the handler with the split_packet as an argument
        try:
            await handler(packet_data,game_server,cowmaster)
        except Exception as e:
            self.log("exception",f"GameServer #{self.id} - An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()} with this packet type: {hex(packet_type)}")

    async def server_announce_preflight(packet):
        """ 0x40  Server announce
        int 0 - msg type
        int 1: (to end) server port
        """
        #
        port = int.from_bytes(packet[1:],byteorder='little')
        return port

    async def server_announce(self,packet):
        """ 0x40  Server announce
        int 0 - msg type
        int 1: (to end) server port
        """
        #
        port = int.from_bytes(packet[1:],byteorder='little')
        return port


    async def server_closed(self,packet, game_server=None, cowmaster=None):
        """  0x41 Server closed
        when the server is killed / crashes / gracefully stopped.

        I have noticed since pretending to be manager, the server will terminate after 10 minutes with the following message:
            [Mar 13 11:54:25] Sv: [11:54:25] No users currently connected and received last manager communication 10 minutes ago, shutting down.
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down...
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down server...

        """
        if game_server:
            self.log("debug",f"GameServer #{self.id} - Received server closed packet: {packet}")
            game_server.reset_game_state()
            # await game_server.save_gamestate_to_file()
            game_server.reset_skipped_frames()
            self.publish_event(topic="game_server/status", data={ "type":"server_closed", **game_server.game_state._state})  
        else:
            self.log("debug",f"CowMaster #{self.id} - Received server closed packet: {packet}")
            cowmaster.reset_cowmaster_state()


    async def server_status(self,packet, game_server=None, cowmaster=None):
        """  0x42 Server status update packet.

                The most valuable packet so far, is sent multiple times a second, contains all "live" state including:
                playercount, game phase, game state, client information

                Total Length is 54 w 0 Players
                Contains:
                    int 1 msg_type			# 0
                    int 1 status			# 1
                    int 4 uptime			# 2-6
                    int 4 server load		# 6-10
                    int 1 num_clients1		# 10
                    int 1 match_started		# 11
                    int 4 unknown           # 12-16
                    int 4 unknown           # 16-20
                    int 4 unknown           # 20-24
                    int 4 unknown           # 24-28
                    int 4 unknown           # 28-32
                    int 4 unknown           # 32-36
                    int 4 unknown           # 36-40
                    int 1 game_phase        # 40
                    int 4 unknown           # 40-44
                    int 4 unknown           # 44-48
                    int 4 unknown           # 48-52
                    int 1 num_clients2      # 53
                With Players, first 54 bytes remains as fixed values, so treat them first. Additional data is tacked on the end as the clients. See code below for parsing
        """

        # Parse fixed-length fields
        temp = ({
            'status': packet[1],                                        # extract status field from packet
            'uptime': int.from_bytes(packet[2:6], byteorder='little'),  # extract uptime field from packet
            'cpu_core_util': int.from_bytes(packet[6:10], byteorder='little') / 100,   # extract the server load value
            'num_clients': packet[10],                                  # extract number of clients field from packet
            'match_started': packet[11],                                # extract match started field from packet
            'game_phase': packet[40],                                   # extract game phase field from packet
        })
        if game_server:
            game_server.game_state.update(temp)
        if cowmaster:
            cowmaster.game_state.update(temp)

        # If the packet only contains fixed-length fields, print the game info and return
        if len(packet) == 54:
            if game_server:
                if game_server.game_state._state['num_clients'] == 0 and game_server.game_state._state['players'] != '':
                    game_server.game_state._state['players'] = []
            return

        # Otherwise, extract player data sections from the packet
        data = packet[53:]                                              # slice the packet to get player data section
        ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')    # define regex pattern for matching IP addresses

        cursor = 1
        num_players = data[0]

        clients = []
        for idx, ip_match in enumerate(ip_pattern.finditer(data)):
            # Extract IP address, username, account ID, and location from the player data section
            cursor, ip_end = ip_match.span()

            account_id = int.from_bytes(data[cursor-4:cursor], byteorder='little')
            
            # Extract IP address
            ip_end = data[cursor:].find(b'\x00') + cursor
            ip = data[cursor:ip_end].decode('utf-8')
            cursor = ip_end + 1
            
            # Extract name
            name_end = data[cursor:].find(b'\x00') + cursor
            name = data[cursor:name_end].decode('utf-8')
            cursor = name_end + 1
            
            # Extract possible location
            location_end = data[cursor:].find(b'\x00') + cursor
            location = data[cursor:location_end].decode('utf-8')
            cursor = location_end + 1
            
            # Extract shorts for statistics
            minping = int.from_bytes(data[cursor:cursor+2], byteorder='little')
            avgping = int.from_bytes(data[cursor+2:cursor+4], byteorder='little')
            maxping = int.from_bytes(data[cursor+4:cursor+6], byteorder='little')
            cursor += 6  # Move cursor ahead by 6 bytes (3 shorts)

            # Append extracted data to the clients list as a dictionary
            clients.append({
                'account_id': account_id,
                'name': name,
                'location': location,
                'ip': ip,
                'minping': minping,
                'avgping': avgping,
                'maxping': maxping
            })
        # Update game dictionary with player information and print
        if game_server:
            game_server.game_state.update({'players':clients})

    async def long_frame(self, packet, game_server=None, cowmaster=None):
        """  0x43 Long Frame
        when there are skipped server frames, this packet contains the time spent skipping frames (msec)
        int 1 msg type
        int 2 skipped frame LE
        """
        skipped_frames = int.from_bytes(packet[1:3], byteorder='little')
        current_time = datetime.datetime.now().timestamp()  # Get current time in Unix timestamp format
        self.log("debug", f"GameServer #{self.id} - skipped server frame: {skipped_frames}msec")
        if game_server:
            game_server.increment_skipped_frames(skipped_frames, current_time)



    async def lobby_created(self,packet, game_server=None, cowmaster=None):
        """  0x44 Lobby created
                int 4 matchid (64 bit for futureproof) # 0-4
                string date     ? didnt find
                string map
                string game name
                string game mode
                int 1 unknown
        """
        self.log("debug", f"GameServer #{self.id} - Received lobby created packet")

        match_id_bytes = packet[1:5]
        match_id = sum([match_id_bytes[i] * (256 ** i) for i in range(len(match_id_bytes))])

        strings = []
        current_index = 6
        while current_index < len(packet) and len(strings) < 3:
            try:
                null_byte_index = packet[current_index:].index(b'\x00')
            except ValueError:
                self.log("error", f"GameServer #{self.id} - Failed to find null byte in packet: {packet}")
                return

            string_value = packet[current_index:current_index+null_byte_index].decode('utf-8', errors='replace')
            strings.append(string_value)
            current_index += null_byte_index + 1

        lobby_info = {
            'match_id': match_id,
            'map': strings[0],
            'name': strings[1],
            'mode': strings[2]
        }
        game_server.game_state.update({'match_info': lobby_info})

        if game_server.get_dict_value('current_match_id') != match_id:
            game_server.update_dict_value('current_match_id', match_id)
            game_server.reset_skipped_frames()

        self.log("debug", f"GameServer #{self.id} - {lobby_info}")
        self.publish_event(topic="game_server/match", data={ "type":"lobby_created", **game_server.game_state._state})
        

    async def lobby_closed(self,packet, game_server=None, cowmaster=None):
        """   0x45 Lobby closed
        """
        self.log("debug",f"GameServer #{self.id} - Received lobby closed packet: {packet}")
        empty_lobby_info = {
            'match_id': '',
            'map': '',
            'name': '',
            'mode': '',
        }
        game_server.game_state.update({'match_info':empty_lobby_info})
        game_server.game_state.update({'players':[]})
        if game_server:
            game_server.reset_game_state()
            # await game_server.save_gamestate_to_file()
            game_server.reset_skipped_frames()
            self.publish_event(topic="game_server/match", data={ "type":"lobby_closed", **game_server.game_state._state})
        else:
            cowmaster.reset_cowmaster_state()

    async def cow_being_used(self, packet, game_server=None, cowmaster=None):
        """ 0x46 Server is being used
            full packet: \x46\x00\x00
            this packet arrives right before the lobby created packet and i assume its being used to
            tell the manager that the server is in use.
            assumption: byte 3-4 is a status
        """


    async def server_connection(self,packet, game_server=None, cowmaster=None):
        """ 0x47 Server selected / player joined

                This packet arrives any time someone begins connecting to the server
        """
        self.log("debug",f"GameServer #{self.id} - Received server connection packet: {packet}")

    async def cow_stats_submission(self, packet, game_server=None, cowmaster=None):
        """ 0x48 state of stats submission
            full example: \x48\x00\x00
            \x48\x00\x00 is Stat submission successful
            \x48\x06\x00 is connected to:
                [Aug 17 10:59:48] Error: [10:59:48] Stat submission failure
                [Aug 17 10:59:48] Error: [10:59:48] Stat submission [3485594] request completely failed
        """

    async def cow_announce(self, packet, game_server=None, cowmaster=None):
        """ 0x49 Fork status response (success or fail)

            This packet arrives from the cow master after fork completed or attempted
            example:
                Success fork \x49\x11\x27\x86\xae
                Fail fork (tried on windows): \x49\x11\x27\x00\x00
                 - Sv: [01:45:45] Received message to fork...
                 - Error: [01:45:45] Server manager requested a fork, but we're a non linux server build.

            2 bytes - message type
            4 bytes - port (\x11\x27 = 10001)
            4 bytes - unknown (translates into 44678 decimal)
                Best guess on that is the source port. Unsure tho.
                In some case it probably has to do something with the identification, cause
                The manager has to know which server is getting ready.
                Idea: Create a gameserver object based on the port
                Update: when failed to fork, these 4 bytes are 0000
        """
        port = int.from_bytes(packet[1:3],byteorder='little')
        self.log('debug',f'CowMaster #{self.id} - fork response: {self.format_packet(packet)} (port: {port})')


    async def replay_update(self,packet, game_server=None, cowmaster=None):
        """ 0x4A Replay status packet

            This is an update from the game server regarding the status of the zipped replay file.
            Most likely for the manager to upload incrementally, if that setting is on (default not on)
        """
        # self.log("debug",f"GameServer #{self.id} - Received replay zip update: {packet}")
        if game_server.get_dict_value('current_match_id') == None:
            match = re.search(rb"/(\d+)/", packet)
            if match:
                match_id = int(match.group(1))
                self.log("debug",f"Updated running match data with Match ID: {match_id}")
                game_server.update_dict_value('current_match_id',match_id)
                await game_server.load_gamestate_from_file(match_only=True)
            else:
                self.log("debug","Match ID not found")


    async def unhandled_packet(self,packet, game_server=None, cowmaster=None):
            """    Any unhandled packet

            Unknowns:
                b'F\x00\x00'
                b'H\x00\x00'
            """


            

            #TODO: Python decodes the output of bytes weirdly. We want to prevent that.


            self.log("debug",f"GameServer #{self.id} - Received unknown packet: {self.format_packet(packet)}")
    
    def format_packet(self,packet):
        return ''.join(['\\x{:02x}'.format(byte) for byte in packet])

class ManagerChatParser:
    def __init__(self,logger=None):
        self.logger = logger
        self.chat_to_mgr_handlers = {
            0x1700: self.chat_handshake_accepted,
            0x1704: self.chat_replay_request,
            0x0400: self.chat_shutdown_notice,
            0x2a01: self.chat_heartbeat_received,
            0x1703: self.chat_policies,
        }
        self.mgr_to_chat_handlers = {
            0x1600: self.mgr_handshake_request,
            0x1602: self.mgr_server_info_update,
            0x1603: self.mgr_replay_response,
            0x2a00: self.mgr_sending_heartbeat
        }
    def log(self,level,message):
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(message)

    async def handle_packet(self, packet_type, packet_len, packet_data, direction):
        if direction == "sending":
            self.print_prefix = f">>> [MGR|CHATSV] - [{hex(packet_type)}] "
            handler = self.mgr_to_chat_handlers.get(packet_type, self.unhandled_packet)
        elif direction == "receiving":
            self.print_prefix = f"<<< [MGR|CHATSV] - [{hex(packet_type)}] "
            handler = self.chat_to_mgr_handlers.get(packet_type, self.unhandled_packet)
        if packet_len != len(packet_data):
            self.log("warn",f"{self.print_prefix}LEN DOESNT MATCH PACKET: {packet_len} and {len(packet_data)}")
        return await handler(packet_data)

    async def chat_handshake_accepted(self,packet_data):
        self.log("debug",f"{self.print_prefix}Handshake accepted")

    async def chat_replay_request(self,packet_data):
        #   Replay request
        account_id = int.from_bytes(packet_data[2:6],'little')
        match_id = int.from_bytes(packet_data[6:10],'little')
        extension,_,remaining_data = packet_data[10:].partition(b'\x00')
        filehost,_,remaining_data = remaining_data.partition(b'\x00')
        directory,_,remaining_data = remaining_data.partition(b'\x00')
        upload_to_ftb = remaining_data[0]
        upload_to_s3 = remaining_data[1]
        download_link = remaining_data[2:].split(b'\x00', 1)[0].decode('utf-8')

        extension = extension.decode('utf-8')
        filehost = filehost.decode('utf-8')
        directory = directory.decode('utf-8')

        parsed = {"account_id":account_id,"match_id":match_id,"extension":extension,"filehost":filehost,"directory":directory,"upload_to_ftb":upload_to_ftb,"upload_to_s3":upload_to_s3,"download_link":download_link}
        self.log("debug",f"{self.print_prefix}Upload replay\n Account ID: {account_id}\n Match ID: {match_id}\n Extension: {extension}\n Filehost: {filehost}\n Directory: {directory}\n Upload to ftb: {upload_to_ftb}\n Upload to S3: {upload_to_s3}\n Download Link: {download_link}")
        return parsed
        #self.log("debug",f"{self.print_prefix}{packet_data}")
    async def chat_shutdown_notice(self,packet_data):
        self.log("debug",f"{self.print_prefix}Received chat server shutdown notice.")

    async def chat_heartbeat_received(self,packet_data):
        self.log("debug",f"{self.print_prefix}Received heartbeat.")

    async def chat_policies(self,packet_data):
        self.log("debug",f"{self.print_prefix}Received server setting policy.")

    async def mgr_handshake_request(self,packet_data):
        #   Handshake
        #   b'+\x00\x00\x16Y\xf0\x02\x00f7851dd680764deaabf4bcc447ce5b57\x00F\x00\x00\x00'  -working
        server_id = int.from_bytes(packet_data[2:6],byteorder='little')
        session_id = packet_data[6:].split(b'\x00', 1)[0].decode('utf-8')
        self.log("debug",f"{self.print_prefix}Handshake\n\tServer ID: {server_id}\n\tSession: {session_id}")

    async def mgr_server_info_update(self,packet_data):
        #   b'\x02\x16Y\xf0\x02\x00AUSFRANKHOST:\x00NEWERTH\x00T4NK 0\x004.10.6.0\x00103.193.80.121\x00\xe3+\x00' - original
        server_id = int.from_bytes(packet_data[2:6],byteorder='little')
        username,_,remaining_data = packet_data[6:].partition(b'\x00')
        region,_,remaining_data = remaining_data.partition(b'\x00')
        server_name,_,remaining_data = remaining_data.partition(b'\x00')
        version,_,remaining_data = remaining_data.partition(b'\x00')
        ip_addr,_,remaining_data = remaining_data.partition(b'\x00')
        port = int.from_bytes(remaining_data[0:2],byteorder='little')

        username = username.decode('utf-8')
        region = region.decode('utf-8')
        server_name = server_name.decode('utf-8')
        version = version.decode('utf-8')
        ip_addr = ip_addr.decode('utf-8')

        self.log("debug",f"{self.print_prefix}Sending server info:\n\tUsername: {username}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tVersion: {version}\n\tIP Addr: {ip_addr}\n\tAutoping Port: {port}")

    async def mgr_sending_heartbeat(self,packet_data):
        self.log("debug",f"{self.print_prefix}Sending heartbeat..")

    async def mgr_receiving_heartbeat(self,packet_data):
        self.log("debug",f"{self.print_prefix}Received heartbeat")

    async def mgr_replay_response(self,packet_data):
        # Example, replay not found: b'\x03\x16\x00\x80\x19\x00\x80\x03\x00\x00\x01'
        # Example, replay not found: b'\x03\x16ob\x1c\x00\x80\x03\x00\x00\x01'
        # Replay found, send in parts:
        #   b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x05'
        #   b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x06'
        #   b'\x03\x16\x18L\x1d\x00\x80\x03\x00\x00\x07\x00'
        self.log("debug",f"{self.print_prefix}Responding to replay request..\n{packet_data}")

    async def unhandled_packet(self, packet_data):
        self.log("warn",f"{self.print_prefix} Unhandled packet: {packet_data}")

"""
class ManagerHTTPParser:
    def __init__(self, client_id):
        self.packet_handlers = {
            0x40: self.server_announce,
            0x41: self.server_closed,
            0x42: self.server_status,
            0x43: self.long_frame,
            0x44: self.lobby_created,
            0x45: self.lobby_closed,
            0x47: self.server_connection,
            0x4A: self.replay_update,
        }
        self.id = client_id
"""

class GameChatParser:
    def __init__(self, logger=None):
        self.logger = logger
        self.game_to_chat_handlers = {
            0x500: self.game_login,
            0x501: self.game_server_closed,
            0x2a00: self.game_send_heartbeat,
            0x502: self.game_send_server_info,
            0x513: self.game_player_connection
        }
        self.chat_to_game_handlers = {
            0x1500: self.chat_logon_response,
            0x2a01: self.chat_heartbeat_received
        }

    def log(self,level,message):
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(message)

    async def handle_packet(self, packet_type, packet_len, packet_data, direction):
        if direction == "sending":
            self.print_prefix = f">>> [GAME|CHAT] - [{hex(packet_type)}] "
            handler = self.game_to_chat_handlers.get(packet_type, self.unhandled_packet)
        elif direction == "receiving":
            self.print_prefix = f"<<< [GAME|CHAT] - [{hex(packet_type)}] "
            handler = self.chat_to_game_handlers.get(packet_type, self.unhandled_packet)
        if packet_len != len(packet_data):
            self.log("warn",f"{self.print_prefix}LEN DOESNT MATCH PACKET: {packet_len} and {len(packet_data)}")
        await handler(packet_data)

    async def game_login(self,packet_data):
        server_id = int.from_bytes(packet_data[2:6],byteorder='little')  # not the slave ID, the server ID given by master server
        session_id,_,remaining_data = packet_data[6:].partition(b'\x00')     # session ID is cookie given by master server
        chat_protocol = int.from_bytes(remaining_data,byteorder='little')   # unlikely to change
        session_id = session_id.decode('utf-8')
        self.log("debug",f"{self.print_prefix}Logging in...\n\tServer ID: {server_id}\n\tSession ID: {session_id}")

    async def game_server_closed(self,packet_data):
        self.log("debug",f"{self.print_prefix}Notifying of shutdown..")

    async def game_send_heartbeat(self,packet_data):
        self.log("debug",f"{self.print_prefix}Sending heartbeat..")

    async def game_send_server_info(self,packet_data):
        server_id = int.from_bytes(packet_data[2:6],byteorder='little')
        ip_addr, _, remaining_data = packet_data[6:].partition(b'\x00')
        port = int.from_bytes(remaining_data[0:2],byteorder='little')
        region, _, remaining_data = remaining_data[2:].partition(b'\x00')
        server_name, _, remaining_data = remaining_data.partition(b'\x00')
        slave_id = int.from_bytes(remaining_data[0:2],byteorder='little')
        #   2-4 ? b'\x00\x00'
        match_id = int.from_bytes(remaining_data[4:8],byteorder='little')
        u1 = packet_data[8]  # mb chatserver protocol
        u2 = packet_data[9]  # ?
        u3 = packet_data[10] # ?     this and above 2 combined = 2097155
        #   8-10 ? b'x03\x00 '
        ip_addr = ip_addr.decode('utf-8')
        region = region.decode('utf-8')
        server_name = server_name.decode('utf-8')
        self.log("debug",f"{self.print_prefix}Server sent lobby information\n\tIP Addr: {ip_addr}\n\tRegion: {region}\n\tServer Name: {server_name}\n\tSlave ID: {slave_id}\n\tMatch ID: {match_id}")

    async def game_player_connection(self, packet_data):
        self.log("debug",f"{self.print_prefix}Player connection")

    async def chat_logon_response(self,packet_data):
        self.log("debug",f"{self.print_prefix}Authenticated to Chat Server")

    async def chat_heartbeat_received(self,packet_data):
        self.log("debug",f"{self.print_prefix}Received heartbeat")

    async def unhandled_packet(self,packet_data):
        self.log("warn",f"Unhandled: {self.print_prefix}{packet_data}")

class ClientChatParser:
    def __init__(self, logger=None):
        self.logger = logger
        self.client_to_chat_handlers = {
            0xC00: self.client_connect_request,
            0xbe: self.client_replay_request,
        }
        self.chat_to_client_handlers = {
            0x1500: self.unhandled_packet,
            0x2a01: self.unhandled_packet,
            0x68: self.chat_online_counter,
            0xbf: self.chat_replay_upload_status,
            0x1c00: self.chat_authentication_ok,
            0x1c01: self.chat_authentication_fail
        }
    def null(self,data):
        pass
    def log(self,level,message):
        if self.logger:
            getattr(self.logger, level)(message)
        else:
            print(message)

    async def handle_packet(self, packet_type, packet_len, packet_data, direction):
        if direction == "sending":
            self.print_prefix = f">>> [CLIENT|CHAT] - [{hex(packet_type)}] "
            handler = self.client_to_chat_handlers.get(packet_type, self.unhandled_packet)
        elif direction == "receiving":
            self.print_prefix = f"<<< [CLIENT|CHAT] - [{hex(packet_type)}] "
            handler = self.chat_to_client_handlers.get(packet_type, self.unhandled_packet)
        # if packet_len != len(packet_data):
        #     self.log("warn",f"{self.print_prefix}LEN DOESNT MATCH PACKET: {packet_len} and {len(packet_data)}")
        return await handler(packet_data)

    async def client_connect_request(self, packet_data):
        offset = 2
        connect_request = {}

        connect_request['accountId'], offset = read_int(packet_data, offset)
        connect_request['sessionCookie'], offset = read_string(packet_data, offset)
        connect_request['externalIp'], offset = read_string(packet_data, offset)
        connect_request['sessionAuthHash'], offset = read_string(packet_data, offset)
        connect_request['chatProtocolVersion'], offset = read_int(packet_data, offset)
        connect_request['operatingSystem'], offset = read_byte(packet_data, offset)
        connect_request['osMajorVersion'], offset = read_byte(packet_data, offset)
        connect_request['osMinorVersion'], offset = read_byte(packet_data, offset)
        connect_request['osMicroVersion'], offset = read_byte(packet_data, offset)
        connect_request['osBuildCode'], offset = read_string(packet_data, offset)
        connect_request['osArchitecture'], offset = read_string(packet_data, offset)
        connect_request['clientVersionMajor'], offset = read_byte(packet_data, offset)
        connect_request['clientVersionMinor'], offset = read_byte(packet_data, offset)
        connect_request['clientVersionMicro'], offset = read_byte(packet_data, offset)
        connect_request['clientVersionHotfix'], offset = read_byte(packet_data, offset)
        connect_request['lastKnownClientState'], offset = read_byte(packet_data, offset)
        connect_request['clientChatModeState'], offset = read_byte(packet_data, offset)
        connect_request['clientRegion'], offset = read_string(packet_data, offset)
        connect_request['clientLanguage'], offset = read_string(packet_data, offset)

        self.log("debug",f"{self.print_prefix}Client Connect\n\t{connect_request}")

        return connect_request

    async def chat_online_counter(self,packet_data):
        offset = 2
        online_count, offset = read_int(packet_data,offset)
        self.log("debug",f"{self.print_prefix}Online count: {online_count}")

        return online_count

    async def client_replay_request(self,packet_data):
        offset = 2
        match_id, offset = read_int(packet_data, offset)
        file_format, offset = read_string(packet_data, offset)

        self.log("debug",f"{self.print_prefix}Replay Request\n\tMatch ID: {match_id}\n\tfile format: {file_format}")

    async def chat_replay_upload_status(self, packet_data):
        offset = 2
        replay_status = {}

        replay_status['match_id'], offset = read_int(packet_data, offset)
        replay_status['status'], offset = read_byte(packet_data, offset)
        if replay_status['status'] == 7:  # "UPLOAD_COMPLETE"
            replay_status['extra_byte'], offset = read_byte(packet_data, offset)

        status = None
        if replay_status['status'] == -1: status = 'None'
        if replay_status['status'] == 0: status = 'GENERAL_FAILURE'
        if replay_status['status'] == 1: status = 'DOES_NOT_EXIST'
        if replay_status['status'] == 2: status = 'INVALID_HOST'
        if replay_status['status'] == 3: status = 'ALREADY_UPLOADED'
        if replay_status['status'] == 4: status = 'ALREADY_QUEUED'
        if replay_status['status'] == 5: status = 'QUEUED'
        if replay_status['status'] == 6: status = 'UPLOADING'
        if replay_status['status'] == 7:
            status = 'DONE'
            self.log("info",f"Replay available: http://api.kongor.online/replays/M{replay_status['match_id']}.honreplay")

        self.log("debug",f"{self.print_prefix}Replay status update\n\tMatch ID: {replay_status['match_id']}\n\tStatus: {status}")

        return replay_status

    async def chat_authentication_ok(self,packet_data):
        offset = 2
        status, offset = read_int(packet_data, offset)
        return status

    async def chat_authentication_fail(self,packet_data):
        offset = 2
        status, offset = read_int(packet_data, offset)
        return status


    async def unhandled_packet(self,packet_data):
        self.log("warn",f"Unhandled: {self.print_prefix}{packet_data}")
        pass

"""
class GameHTTPParser:
    def __init__(self, client_id):
        self.packet_handlers = {
            0x40: self.server_announce,
            0x41: self.server_closed,
            0x42: self.server_status,
            0x43: self.long_frame,
            0x44: self.lobby_created,
            0x45: self.lobby_closed,
            0x47: self.server_connection,
            0x4A: self.replay_update,
        }
        self.id = client_id
"""
