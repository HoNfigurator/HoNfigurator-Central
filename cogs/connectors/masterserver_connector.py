import traceback
import aiohttp
import os
import urllib.parse
from cogs.misc.logger import get_logger
from cogs.handlers.events import stop_event
import phpserialize
import hashlib

LOGGER = get_logger()

class MasterServerHandler:

    def __init__(self, master_server="api.kongor.online", version="4.10.6.0", was="was-crIac6LASwoafrl8FrOa", event_bus=None):
        self.manager_event_bus = event_bus
        self.manager_event_bus.subscribe('replay_upload_request', self.get_replay_upload_info)
        self.manager_event_bus.subscribe('replay_upload_start', self.upload_replay_file)
        self.version = version
        self.was = was
        self.master_server = master_server
        self.base_url = f"http://{self.master_server}"
        self.headers = {
            "User-Agent": f"S2 Games/Heroes of Newerth/{self.version}/was/x86_64",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        self.session = aiohttp.ClientSession()
        self.server_id = None
        self.cookie = None
        LOGGER.debug(f"Master server URL: {self.base_url}")
        LOGGER.debug(f"Headers: {self.headers}")
    
    def set_server_id(self, server_id):
        self.server_id = server_id

    def set_cookie(self, cookie):
        self.cookie = cookie

    async def send_replay_auth(self, login, password):
        url = f"{self.base_url}/server_requester.php?f=replay_auth"
        data = {
            "login": login,
            "pass": password
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=self.headers) as response:
                return await response.text(), response.status

    async def get_replay_upload_info(self, match_id, extension, username, file_size):
        url = f"{self.base_url}/server_requester.php?f=sm_upload_request"
        data = {
            # "pass": "a67dcdxj95a3rff",
            "man_masterLogin":f"{username}:",
            "match_id": match_id,
            "file_extension": extension,
            "file_size": file_size
            # "md5_checksum": 'ffcb32ec48b2cf5e57943409fb4b44cd',
            # "hash_key": '588da37c6689075914fdaea4a9b93b1d919e93b0'
        }
        LOGGER.debug(f"Request data: {data}")
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=self.headers) as response:
                if response.status == 200:
                    try:
                        response_text = await response.text()
                        return phpserialize.loads(response_text.encode('utf-8')), response.status
                    except Exception:
                        LOGGER.exception(f"Error parsing PHP serialized response: {traceback.format_exc()}")
                        return {"error": "Error parsing PHP serialized response", "exception": str(traceback.format_exc())}, response.status
                else:
                    LOGGER.error(f"Error fetching upload information: {response.status}")
                    return {"error": "Error fetching upload information", "status": response.status}, response.status

    async def upload_replay_file(self, file_path, file_name, url):
        async with aiohttp.ClientSession() as session:
            try:
                with open(file_path, 'rb') as replay_file:
                    data = aiohttp.FormData(quote_fields=False)
                    headers = {'User-Agent': f'S2 Games/Heroes of Newerth/{self.version}/was/x86_64'}
                    data.add_field('file', replay_file, filename=file_name, content_type='application/octet-stream')
                    #LOGGER.debug(f"Request data: {data[:100]}... (truncated)")
                    #'FormData' object is not subscriptable
                    async with session.post(f"http://{url}", data=data, headers=headers) as response:
                        LOGGER.debug(f"Code: {response.status}, Text: response.text()")
                        return await response.text(), response.status
            except IOError:
                LOGGER.exception(f"Error opening the file: {file_path}")
                return {"error": "Error opening the file", "exception": str(traceback.format_exc())}, -1
    async def get_spectator_header(self):
        url = f"{self.base_url}/server_requester.php"
        data = {
            "f": "get_spectator_header"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, headers=self.headers) as response:
                return await response.text(), response.status
    
    async def send_stats_file(self, username, password, match_id, file_path):
        def generate_resubmission_key(match_id, session_cookie):
            sha1 = hashlib.sha1()
            sha1.update(f"{match_id}{session_cookie}".encode('utf-8'))
            resubmission_key = sha1.hexdigest()
            return resubmission_key

        if not self.cookie:
            LOGGER.error("Unable to resubmit stats, as there is no stored session cookie. Indicating the server is not authenticated with the master server.")
            return
        elif not self.server_id:
            LOGGER.error("Unable to resubmit stats, as there is no stored server id. The particular time this error occured, indicates there may have been an issue assigning the server id.")
            return

        url = f"{self.base_url}/stats_requester.php"

        headers = self.headers.copy()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        params = {
            'svr_login': username,
            'pass': password,
            'resubmission_key': generate_resubmission_key(match_id, self.cookie),
            'server_id': self.server_id
        }

        try:
            # Read the file content as a string with specified encoding
            with open(file_path, 'r', encoding='utf-16-le') as f:
                file_content = f.read().lstrip('\ufeff')

            # Manually construct the request payload
            payload = "f=resubmit_stats"
            for key, value in params.items():
                payload += f"&{key}={value}"
            payload += f"&{file_content}"

            headers["Content-Length"] = str(len(payload))

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=payload) as response:
                    return await response.text(), response.status
        except Exception:
            print(traceback.format_exc())

    async def compare_upstream_patch(self):
        url = f"{self.base_url}/patcher/patcher.php"
        data = {"latest": "", "os": f"{self.was}", "arch": "x86_64"}
        try:
            async with self.session.post(url, headers=self.headers, data=data) as response:
                if response.status == 200:
                    return await response.text(), response.status
                else:
                    return None
        except aiohttp.ClientError:
            LOGGER.exception(f"An error occurred while handling the compare_upstream_patch function: {traceback.format_exc()}")

    async def close_session(self):
        await self.session.close()
