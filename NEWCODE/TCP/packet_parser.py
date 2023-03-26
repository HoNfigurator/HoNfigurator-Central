from cogs.custom_print import my_print, logger, script_dir, flatten_dict
import inspect
import re
import traceback

class PacketParser:
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

    def update_client_id(self, new_id):
        self.id = new_id

    async def handle_packet(self, packet, game_server):
        packet_len, packet_data = packet
        packet_type = packet_data[0]

        if packet_len != len(packet_data):
            print(f"LEN DOESNT MATCH PACKET: {len} and {len(packet_data)}")

        # Retrieve the packet handler function based on the packet_type
        handler = self.packet_handlers.get(packet_type, self.unhandled_packet)

        # Call the handler with the split_packet as an argument
        try:
            await handler(packet_data,game_server)
        except Exception as e:
            logger.exception(f"An error occurred while handling the %s function: %s with this packet type: {packet_type}", inspect.currentframe().f_code.co_name, traceback.format_exc())

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


    async def server_closed(self,packet, game_server):
        """  0x41 Server closed
        when the server is killed / crashes / gracefully stopped.

        I have noticed since pretending to be manager, the server will terminate after 10 minutes with the following message:
            [Mar 13 11:54:25] Sv: [11:54:25] No users currently connected and received last manager communication 10 minutes ago, shutting down.
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down...
            [Mar 13 11:54:25] Sv: [11:54:25] Shutting down server...

        """
        logger.info(f"GameServer #{self.id} - Received server closed packet: {packet}")


    async def server_status(self,packet, game_server):
        """  0x42 Server status update packet.
            
                The most valuable packet so far, is sent multiple times a second, contains all "live" state including:
                playercount, game phase, game state, client information

                Total Length is 54 w 0 Players
                Contains:
                    int 1 msg_type			# 0
                    int 1 status			# 1
                    int 4 uptime			# 2-6
                    int 4 unknown			# 6-10
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
        game_server.game_state.update({
            'status': packet[1],                                        # extract status field from packet
            'uptime': int.from_bytes(packet[2:6], byteorder='little'),  # extract uptime field from packet
            'num_clients': packet[10],                                  # extract number of clients field from packet
            'match_started': packet[11],                                # extract match started field from packet
            'game_phase': packet[40],                                   # extract game phase field from packet
        })
        # If the packet only contains fixed-length fields, print the game info and return
        if len(packet) == 54:
            if game_server.game_state._state['num_clients'] == 0 and game_server.game_state._state['players'] != '':
                game_server.game_state._state['players'] = ''
            return

        # Otherwise, extract player data sections from the packet
        data = packet[53:]                                              # slice the packet to get player data section
        ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')    # define regex pattern for matching IP addresses

        # Parse the player data sections
        clients = []
        for idx, ip_match in enumerate(ip_pattern.finditer(data)):
            # Extract IP address, username, account ID, and location from the player data section
            ip_start, ip_end = ip_match.span()
            name_start = data[ip_end:].find(b'\x00') + ip_end
            name_end = data[name_start+1:].find(b'\x00') + name_start + 1
            name = data[name_start:name_end].decode('utf-8').replace('\x00', '')
            account_id = int.from_bytes(data[ip_start-4:ip_start], byteorder='little')
            location_start = data[name_end+1:].find(b'\x00') + name_end + 1
            location_end = data[location_start+1:].find(b'\x00') + location_start + 1
            location = data[location_start:location_end-1].decode('utf-8') if location_start > name_end+1 else ''
            
            # Append extracted data to the clients list as a dictionary
            clients.append({
                'account_id': account_id,
                'name': name,
                'location': location,
                'ip': data[ip_start:ip_end].decode('utf-8')
            })
        # Update game dictionary with player information and print
        game_server.game_state.update({'players':clients})


    async def long_frame(self,packet, game_server):
        """  0x43 Long Frame
        when there are skipped server frames, this packet contains the time spent skipping frames (msec)
        int 1 msg type 
        int 2 skipped frame LE


        """
        skipped_frames = int.from_bytes(packet[1:3],byteorder='little')
        print(f"GameServer #{self.id} - skipped server frame: {skipped_frames}msec")
        game_server.increment_skipped_frames(skipped_frames)


    async def lobby_created(self,packet, game_server):
        """  0x44 Lobby created
                int 4 matchid (64 bit for futureproof) # 0-4
                string date     ? didnt find
                string map
                string game name
                string game mode
                int 1 unknown
        """
        logger.info(f"GameServer #{self.id} - Received lobby created packet")

        # Extract the match ID from the packet bytes
        match_id_bytes = packet[1:5]
        match_id = sum([match_id_bytes[i] * (256 ** i) for i in range(len(match_id_bytes))])

        # Extract the strings from the packet bytes
        strings = []
        current_index = 6
        while current_index < len(packet):
            # Find the null byte that terminates the current string
            null_byte_index = packet[current_index:].index(b'\x00')
            # Extract the current string and append it to the list of strings
            try:
                string_value = packet[current_index:current_index+null_byte_index].decode('utf-8')
            except (UnicodeDecodeError, ValueError) as e:
                logger.exception(f"An error occurred while handling the %s function: %s with this packet: {packet}", inspect.currentframe().f_code.co_name, traceback.format_exc())
                string_value = ""
                return
            strings.append(string_value)
            # Update the current index to point to the next string
            current_index += null_byte_index + 1

        # Extract the unknown string from the packet bytes
        unknown = packet[28:32].decode('utf-8').rstrip('\x00')

        # Create a dictionary containing the lobby information
        lobby_info = {
            'match_id': match_id,
            'map': strings[0],
            'name': strings[1],
            'mode': strings[2]
        }
        game_server.game_state.update({'match_info':lobby_info})

        # set the current match ID and reset the skipped frame sum
        if game_server.get_dict_value('current_match_id') != match_id:
            game_server.update_dict_value('current_match_id',match_id)
            game_server.reset_skipped_frames()

        # Print the lobby information
        logger.info(f"GameServer #{self.id} - {lobby_info}")


    async def lobby_closed(self,packet, game_server):
        """   0x45 Lobby closed
        """
        logger.info(f"GameServer #{self.id} - Received lobby closed packet: {packet}")
        empty_lobby_info = {
            'match_id': '',
            'map': '',
            'name': '',
            'mode': '',
        }
        game_server.game_state.update({'match_info':empty_lobby_info})
        game_server.game_state.update({'players':[]})
        game_server.save()
        game_server.reset_skipped_frames()


    async def server_connection(self,packet, game_server):
        """ 0x47 Server selected / player joined
                
                This packet arrives any time someone begins connecting to the server
        """
        logger.info(f"GameServer #{self.id} - Received server connection packet: {packet}")
    

    async def replay_update(self,packet, game_server):
        """ 0x4A Replay status packet
        
            This is an update from the game server regarding the status of the zipped replay file.
            Most likely for the manager to upload incrementally, if that setting is on (default not on)
        """
        logger.info(f"GameServer #{self.id} - Received replay zip update:", packet)
        if game_server.get_dict_value('current_match_id') == None:
            match = re.search(rb"/(\d+)/", packet)
            if match:
                match_id = int(match.group(1))
                print("Match ID:", match_id)
                game_server.update_dict_value('current_match_id',match_id)
                game_server.load(match_only=True)
            else:
                print("Match ID not found")


    async def unhandled_packet(self,packet, game_server):
            """    Any unhandled packet

            Unknowns:
                b'F\x00\x00'
                b'H\x00\x00'
            """

            logger.info(f"GameServer #{self.id} - Received unknown packet: {packet}")