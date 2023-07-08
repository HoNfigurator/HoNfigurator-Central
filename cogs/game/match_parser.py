import re

class MatchParser:
    def __init__(self, match_id, log_path):
        self.match_id = match_id
        self.log_path = log_path
        self.player_details = {}

    def parse_chat(self):
        chat_messages = {}

        pattern = r'PLAYER_CHAT player:(\d+) target:"(\w+)" msg:"(.*?)"'
        player_pattern = r'PLAYER_CONNECT player:(\d+) name:"(.*?)" id:(\d+) psr:(\d+\.\d+)'

        # with open(self.log_path, 'r', encoding='utf-16-le') as file:
        with open(self.log_path, 'r', encoding='utf-8') as file:
            log_content = file.read()

        matches = re.findall(pattern, log_content)
        player_matches = re.findall(player_pattern, log_content)

        for match in player_matches:
            player_id, player_name, player_id_num, psr = match
            self.player_details[player_id] = {
                'name': player_name,
                'id': player_id_num,
                'psr': float(psr)
            }

        for match in matches:
            player_id, target, message = match
            if player_id not in chat_messages:
                chat_messages[player_id] = []
            chat_messages[player_id].append((target, message))

        # # Display the chat messages
        # for player_id, messages in chat_messages.items():
        #     player_name = self.player_details[player_id]['name']
        #     print(f"Player {player_name} ({player_id}):")
        #     for target, message in messages:
        #         print(f"  {target}: {message}")
        
        return chat_messages, self.player_details