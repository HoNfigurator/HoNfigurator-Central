import re, json

class MatchParser:
    def __init__(self, match_id, log_path):
        self.match_id = match_id
        self.log_path = log_path
        self.player_details = {}
        
        # Pre-compile regex patterns
        self.chat_pattern_lobby = re.compile(r'PLAYER_CHAT player:(\d+) target:"(\w+)" msg:"(.*?)"')
        self.chat_pattern_game = re.compile(r'PLAYER_CHAT time:(\d+) player:(\d+) target:"(\w+)" msg:"(.*?)"')
        self.player_pattern = re.compile(r'PLAYER_CONNECT player:(\d+) name:"(.*?)" id:(\d+) psr:(\d+\.\d+)')

    def parse_chat(self):
        chat_messages = {}

        try:
            with open(self.log_path, 'r', encoding='utf-16-le') as file:
                for line_number, line in enumerate(file, start=1):  # Track line number
                    self._parse_player_line(line)
                    self._parse_chat_line(line, chat_messages, line_number)
        except FileNotFoundError:
            print(f"File not found: {self.log_path}")
        except Exception as e:
            print(f"An error occurred: {str(e)}")
        
        # Convert to JSON-compatible structure
        chat_messages_json = {
            player_id: [
                {"line_number": entry[0], "target": entry[1], "message": entry[2]} if len(entry) == 3
                else {"line_number": entry[0], "time": entry[1], "target": entry[2], "message": entry[3]}
                for entry in messages
            ]
            for player_id, messages in chat_messages.items()
        }
        
        # Combine results in a JSON-compatible dictionary
        result = {
            "chat_messages": chat_messages_json,
            "player_details": self.player_details
        }
        
        return json.dumps(result, indent=4)  # Pretty-print JSON output

    def parse_player_ids(self):
        try:
            with open(self.log_path, 'r', encoding='utf-16-le') as file:
                for line in file:
                    self._parse_player_line(line)
        except FileNotFoundError:
            print(f"File not found: {self.log_path}")
        except Exception as e:
            print(f"An error occurred: {str(e)}")
        
        return self.player_details
        
    def _parse_player_line(self, line):
        match = self.player_pattern.search(line)
        if match:
            player_id, player_name, player_id_num, psr = match.groups()
            self.player_details[player_id] = {
                'name': player_name,
                'id': player_id_num,
                'psr': float(psr)
            }

    def _parse_chat_line(self, line, chat_messages, line_number):
        match_lobby = self.chat_pattern_lobby.search(line)
        match_game = self.chat_pattern_game.search(line)
        
        # Process lobby match if found
        if match_lobby:
            player_id, target, message = match_lobby.groups()
            if player_id not in chat_messages:
                chat_messages[player_id] = []
            chat_messages[player_id].append((line_number, target, message))
        
        # Process game match if found
        if match_game:
            time, player_id, target, message = match_game.groups()
            if player_id not in chat_messages:
                chat_messages[player_id] = []
            chat_messages[player_id].append((line_number, time, target, message))