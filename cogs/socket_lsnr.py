import socket
import struct
import re

def receive_packet(sock):
    """ Packet format

            The packet comes like this:
                First 2 bytes = size of command
                3rd byte = message type / header
            
            First, get the size, then wait until the full size has been received.
    """
    # Read the first two bytes to get the length of the packet
    length_bytes = sock.recv(2)
    length = int.from_bytes(length_bytes, "little")

    # Read the remaining bytes of the packet
    remaining_bytes = length
    data = b""
    while remaining_bytes > 0:
        chunk = sock.recv(remaining_bytes)
        if not chunk:
            # The socket has been closed
            return None
        data += chunk
        remaining_bytes -= len(chunk)
    original_packet = length_bytes + data
    return original_packet,data

def handle_packet(original_packet,packet):
    # Process the packet data as needed
    if packet == b'':
        return None
    packet_type = packet[0]
    if packet_type == 0x41:
        """  Server closed
                when the server is killed / crashes / gracefully stopped.
                I have noticed since pretending to be manager, there are occasional crashes.
        """
        print(f"[{packet_type}] Received server closed packet:", packet)
    elif packet_type == 0x42:
        """  Server status update packet.
            
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
        game = {
            'status': packet[1],                                        # extract status field from packet
            'uptime': int.from_bytes(packet[2:6], byteorder='little'),  # extract uptime field from packet
            'num_clients': packet[10],                                  # extract number of clients field from packet
            'match_started': packet[11],                                # extract match started field from packet
            'game_phase': packet[40],                                   # extract game phase field from packet
            'num_clients2': packet[53]                                  # extract number of clients field from packet
        }

        # If the packet only contains fixed-length fields, print the game info and return
        if len(packet) == 54:
            print(game)
            return

        # Otherwise, extract player data sections from the packet
        data = packet[53:]                                              # slice the packet to get player data section
        ip_pattern = re.compile(rb'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')    # define regex pattern for matching IP addresses

        # Parse the player data sections
        clients = []
        for ip_match in ip_pattern.finditer(data):
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
        game.update({'players': clients})
        print(game)
    elif packet_type == 0x43:
        """  Lobby status
                typically this occurs when a lobby is created, or a lobby is started. Unsure what a lot of the info is. All the clients are in here, however I focused on parsing them in 0x42 as 0x42 contains all the same info from what I can see.
                to summarise, a mostly useless packet.
        """
        print(f"[{packet_type}] [{len(packet)}] Received lobby status update")
    elif packet_type == 0x44:
        """  Lobby created
                int 4 matchid (64 bit for futureproof) # 0-4
                string date     ? didnt find
                string map
                string game name
                string game mode
                int 1 unknown
        """
        print(f"[{packet_type}] [{len(packet)}] Received lobby created packet")

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
            string_value = packet[current_index:current_index+null_byte_index].decode('utf-8')
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

        # Print the lobby information
        print(lobby_info)
    elif packet_type == 0x45:
        """   Lobby closed
        """
        print(f"[{packet_type}] Received lobby closed packet:", packet)
    elif packet_type == 0x47:
        """   Server selected / player joined
                
                This packet arrives any time someone begins connecting to the server
        """
        print(f"[{packet_type}] [{len(packet)}] Received server selected packet (no lobby):", packet)
    elif packet_type == 0x4A:
        """ Replay status packet
        
            This is an update from the game server regarding the status of the zipped replay file.
            Most likely for the manager to upload incrementally, if that setting is on (default not on)
        """  
        print(f"[{packet_type}] Received replay zip update:", packet)
    else:
        """    Any unhandled packet
        """
        print(f"[{packet_type}] Received unknown packet:", packet)

def main():
    host = "127.0.0.1"
    port = 12345

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind((host, port))
    server_sock.listen(1)

    print(f"Listening on {host}:{port}")

    while True:
        client_sock, client_addr = server_sock.accept()
        print(f"Client connected from {client_addr[0]}:{client_addr[1]}")

        # Receive and handle packets from the client
        while True:
            original_packet,packet = receive_packet(client_sock)
            if packet is None:
                # Connection closed by client
                break
            handle_packet(original_packet,packet)

        # Close the client connection
        client_sock.close()
        print(f"Client disconnected from {client_addr[0]}:{client_addr[1]}")

if __name__ == "__main__":
    main()