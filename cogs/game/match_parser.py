import re

class MatchParser:
    def __init__(self, match_id, log_path):
        self.match_id = match_id
        self.log_path = log_path
        self.player_details = {}
        
        # Pre-compile regex patterns
        self.chat_pattern = re.compile(r'PLAYER_CHAT player:(\d+) target:"(\w+)" msg:"(.*?)"')
        self.player_pattern = re.compile(r'PLAYER_CONNECT player:(\d+) name:"(.*?)" id:(\d+) psr:(\d+\.\d+)')

    def parse_chat(self):
        chat_messages = {}

        try:
            with open(self.log_path, 'r', encoding='utf-16-le') as file:
                for line in file:  # Process file line-by-line
                    self._parse_player_line(line)
                    self._parse_chat_line(line, chat_messages)
        except FileNotFoundError:
            print(f"File not found: {self.log_path}")
        except Exception as e:
            print(f"An error occurred: {str(e)}")
        
        return chat_messages, self.player_details

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

    def _parse_chat_line(self, line, chat_messages):
        match = self.chat_pattern.search(line)
        if match:
            player_id, target, message = match.groups()
            if player_id not in chat_messages:
                chat_messages[player_id] = []
            chat_messages[player_id].append((target, message))
