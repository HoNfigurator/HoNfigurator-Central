from chatserver_connector_client import ChatServerHandler
import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(project_root)
from cogs.handlers.events import ReplayStatus
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
            chat_address="chat.projectkongor.com",
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
        while True:  # Loop until a break statement is encountered
            if self.chat_server_handler.replay_status == -2:
                pass
            else:
                replay_status = ReplayStatus(self.chat_server_handler.replay_status)
                if replay_status == ReplayStatus.UPLOAD_COMPLETE:
                    print("Replay upload completed successfully.")
                    break  # Stop the loop
                elif replay_status == ReplayStatus.UPLOADING:
                    print("Replay is currently being uploaded...")
                elif replay_status == ReplayStatus.QUEUED:
                    print("Replay is queued for upload...")
                elif replay_status == ReplayStatus.ALREADY_QUEUED:
                    print("Replay is already queued for upload.")
                    break
                elif replay_status == ReplayStatus.ALREADY_UPLOADED:
                    print("Replay has already been uploaded.")
                    break
                elif replay_status == ReplayStatus.INVALID_HOST:
                    print("Invalid host.")
                    break
                elif replay_status == ReplayStatus.DOES_NOT_EXIST:
                    print("Replay does not exist.")
                    break
                elif replay_status == ReplayStatus.GENERAL_FAILURE:
                    print("General failure while uploading replay.")
                    break
                elif replay_status == ReplayStatus.NONE:
                    print("Unknown error.")
                    break
            await asyncio.sleep(1)  # Sleep for a bit before checking again
        
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