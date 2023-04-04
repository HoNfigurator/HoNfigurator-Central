import traceback
import aiohttp
import inspect
from cogs.misc.logging import get_logger
import phpserialize

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
                with open(file_path, 'rb') as file:
                    data = aiohttp.FormData(quote_fields=False)
                    # data.add_field('match_id', str(match_id))
                    # data.add_field('file_extension', extension)
                    data.add_field('file', file, filename=file_name, content_type='application/octet-stream')
                    async with session.post(f"http://{url}", data=data) as response:
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

    async def compare_upstream_patch(self):
        url = f"{self.base_url}/patcher/patcher.php"
        headers = {
            "User-Agent": f"S2 Games/Heroes of Newerth/{self.version}/was/x86_64",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"latest": "", "os": f"{self.was}", "arch": "x86_64"}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, data=data) as response:
                    if response.status == 200:
                        return await response.text(), response.status
                    else:
                        return None
            except aiohttp.ClientError:
                LOGGER.exception(f"An error occurred while handling the {inspect.currentframe().f_code.co_name} function: {traceback.format_exc()}")
