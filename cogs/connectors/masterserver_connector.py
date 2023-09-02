import traceback
import aiohttp
from cogs.misc.logger import get_logger, get_misc
from cogs.misc.exceptions import HoNCompatibilityError
from cogs.handlers.events import stop_event
import phpserialize
import aiofiles

LOGGER = get_logger()
MISC = get_misc()

class MasterServerHandler:

    def __init__(self, master_server="api.kongor.online", version="4.10.6.0", architecture="", event_bus=None):
        self.manager_event_bus = event_bus
        self.manager_event_bus.subscribe('replay_upload_request', self.get_replay_upload_info)
        self.manager_event_bus.subscribe('replay_upload_start', self.upload_replay_file)
        self.version = version
        self.was = "was-crIac6LASwoafrl8FrOa"
        self.las = "las-crIac6LASwoafrl8FrOa"
        self.architecture = architecture
        if MISC.get_os_platform() == "win32":
            self.arch_platform = "x86_64"
        else:
            self.arch_platform = "x86-biarch"

        self.arch_type = self.architecture.split('-')[0]
        self.master_server = master_server
        self.base_url = f"http://{self.master_server}"
        self.user_agent = f"S2 Games/Heroes of Newerth/{self.version}/{self.arch_type}/{self.arch_platform}"
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
            "Server-Launcher": "HoNfigurator"
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
        timeout = aiohttp.ClientTimeout(total=10)  # 10 seconds timeout for the entire operation
        async with aiohttp.ClientSession(timeout=timeout) as session:
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
                async with aiofiles.open(file_path, 'rb') as replay_file:
                    file_data = await replay_file.read()

                data = aiohttp.FormData(quote_fields=False)
                headers = {'User-Agent': self.user_agent}
                data.add_field('file', file_data, filename=file_name, content_type='application/octet-stream')

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
            # sha1 = hashlib.sha1()
            # sha1.update(f"{match_id}{session_cookie}".encode('utf-8'))
            # resubmission_key = sha1.hexdigest()
            resubmission_key = f"{match_id}_honfigurator"
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
            'login': username,
            'pass': password,
            'resubmission_key': generate_resubmission_key(match_id, self.cookie),
            'server_id': self.server_id
        }

        try:
            # Read the file content as a string with specified encoding
            if MISC.get_os_platform() == "win32":
                async with aiofiles.open(file_path, 'r', encoding='utf-16-le') as f:
                    file_content = (await f.read()).lstrip('\ufeff')
            elif MISC.get_os_platform() == "linux":
                async with aiofiles.open(file_path, 'r', encoding='ascii') as f:
                    file_content = (await f.read()).lstrip('\ufeff')
            else:
                raise HoNCompatibilityError(f"OS is reported as {MISC.get_os_platform()} however only 'win32' or 'linux' are supported.")

            # Manually construct the request payload
            payload = "f=resubmit_stats"
            for key, value in params.items():
                payload += f"&{key}={value}"
            payload += f"&{file_content}"

            headers["Content-Length"] = str(len(payload))

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=payload) as response:
                    LOGGER.debug(f"[{response.status}] {match_id} stats resubmission")
                    return await response.text(), response.status
        except Exception:
            print(traceback.format_exc())

    async def compare_upstream_patch(self):
        url = f"{self.base_url}/patcher/patcher.php"
        data = {"latest": "", "os": f"{self.architecture}", "arch": self.arch_platform}
        timeout = aiohttp.ClientTimeout(total=10)  # 10 seconds timeout for the entire operation
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=self.headers, data=data) as response:
                    if response.status == 200:
                        return await response.text(), response.status
                    else:
                        return None
        except aiohttp.ClientError:
            LOGGER.exception(f"An error occurred while handling the compare_upstream_patch function: {traceback.format_exc()}")

    async def close_session(self):
        await self.session.close()
