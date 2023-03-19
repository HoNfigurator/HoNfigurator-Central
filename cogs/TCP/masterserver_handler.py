import requests
import aiohttp
import asyncio

class MasterServerHandler:

    def __init__(self,master_server="api.kongor.online",version="4.10.6.0",was="was-crIac6LASwoafrl8FrOa"):
        self.version = version
        self.was = was
        self.master_server = master_server
        self.base_url = f"http://{self.master_server}"
        self.headers = {
            "User-Agent": f"S2 Games/Heroes of Newerth/{self.version}/was/x86_64",
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded"
        }

    def send_replay_auth(self, login, password):
        url = f"{self.base_url}/server_requester.php?f=replay_auth"
        data = {
            "login": login,
            "pass": password
        }
        response = requests.post(url, data=data, headers=self.headers)
        return response.text, response.status_code

    def get_spectator_header(self):
        url = f"{self.base_url}/server_requester.php"
        data = {
            "f": "get_spectator_header"
        }
        response = requests.post(url, data=data, headers=self.headers)
        return response.text, response.status_code
    
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
            except aiohttp.ClientError as e:
                print(e)