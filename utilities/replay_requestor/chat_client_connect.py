from chatserver_connector_client import ChatServerHandler
import asyncio
import argparse
import sys
import requests

class ClientConnect:
    def __init__(self, session_cookie):
        self.chat_server_handler = ChatServerHandler
        self.external_ip = requests.get('https://api.ipify.org').text
        self.session_cookie = session_cookie

    async def authenticate_and_handle_chat_server(self, match_id: int):
        """
        Create a new chatserver object and connect using a cookie.
        """
        self.chat_server_handler = ChatServerHandler(
            chat_address="chat.kongor.online",
            chat_port="11031",
            external_ip=self.external_ip,
            cookie=self.session_cookie,
            account_id=0,
            session_auth_hash=self.session_cookie
        )

        # connect and authenticate to chatserver
        chat_auth_response = await self.chat_server_handler.connect()

        if not chat_auth_response:
            print(f"Chatserver authentication failure")
            return
        
        handle_packets_task = asyncio.create_task(self.chat_server_handler.handle_packets())

        i = 0
        while not self.chat_server_handler.authentication_response_received:
            await asyncio.sleep(1)
            print("waiting for authentication response")
            if i >=5:
                print(f"Chat server took too long to respond.")
                handle_packets_task.cancel()
                return

        if not self.chat_server_handler.authenticated:
            print(f"Chatserver authentication failure")
            handle_packets_task.cancel()
            return
        
        print("Authenticated to ChatServer.")

        await self.create_replay_request(match_id)

        # Wait for response
        while not self.chat_server_handler.replay_status == 7:
            await asyncio.sleep(1)
        
        # Close connection
        await self.chat_server_handler.close_connection()
        handle_packets_task.cancel()

    async def create_replay_request(self, match_id:int):
        await self.chat_server_handler.create_client_replay_request_packet({"match_id":match_id,"file_format":"honreplay"})

# Use argparse to get match ID and session_cookie from command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("match_id", help="Match ID to be used", type=int)
parser.add_argument("session_cookie", help="Session cookie for authentication")
args = parser.parse_args()

chat_connecter = ClientConnect(args.session_cookie)
asyncio.run(chat_connecter.authenticate_and_handle_chat_server(args.match_id))