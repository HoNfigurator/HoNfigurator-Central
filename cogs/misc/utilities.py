import subprocess, psutil
import os
import hashlib
import crcmod
import zipfile
import binascii
from os.path import exists
from pathlib import Path
import sys
from cpuinfo import get_cpu_info
import requests
import aiohttp
from cogs.misc.logger import get_logger, get_home
from cogs.misc.exceptions import HoNUnexpectedVersionError
import ipaddress
import asyncio


LOGGER = get_logger()
HOME_PATH = get_home()

class Misc:
    def __init__(self):
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_name = get_cpu_info().get('brand_raw', 'Unknown CPU')
        self.total_ram = psutil.virtual_memory().total
        self.os_platform = sys.platform
        self.total_allowed_servers = None
        self.github_branch_all = self.get_all_branch_names()
        self.github_branch = self.get_current_branch_name()
        self.public_ip = self.lookup_public_ip()
        self.hon_version = None

    def build_commandline_args(self,config_local, config_global):
        params = ';'.join(' '.join((f"Set {key}",str(val))) for (key,val) in config_local['params'].items())
        if self.get_os_platform() == "win32":
            if config_global['hon_data']['svr_noConsole']:
                return [config_local['config']['file_path'],"-dedicated","-mod","game;KONGOR","-noconsole","-noconfig","-execute",params,"-masterserver",config_global['hon_data']['svr_masterServer'],"-register",f"127.0.0.1:{config_global['hon_data']['svr_managerPort']}"]
            else:
                return [config_local['config']['file_path'],"-dedicated","-mod","game;KONGOR","-noconfig","-execute",params,"-masterserver",config_global['hon_data']['svr_masterServer'],"-register",f"127.0.0.1:{config_global['hon_data']['svr_managerPort']}"]
        elif self.get_os_platform() == "linux":
            return [
                config_local['config']['file_path'],
                '-dedicated',
                '-noconfig',
                '-mod game;KONGOR',
                '-execute',
                f'"{params}"',
                '-masterserver',
                config_global['hon_data']['svr_masterServer'],
                '-register',
                f'127.0.0.1:{config_global["hon_data"]["svr_managerPort"]}'
            ]
        
    def parse_linux_procs(self, proc_name, slave_id):
        for proc in psutil.process_iter():
            if proc_name == proc.name():
                if slave_id == '':
                    return [ proc ]
                else:
                    cmd_line = proc.cmdline()
                    if len(cmd_line) < 5:
                        continue
                    for i in range(len(cmd_line)):
                        if cmd_line[i] == "-execute":
                            for item in cmd_line[i+1].split(";"):
                                if "svr_slave" in item:
                                    if int(item.split(" ")[-1]) == slave_id:
                                        return [ proc ]
        return []
    
    def get_proc(self, proc_name, slave_id=''):
        if sys.platform == "linux":
            return self.parse_linux_procs(proc_name, slave_id)
        procs = []
        for proc in psutil.process_iter():
            try:
                if proc_name == proc.name():
                    if slave_id == '':
                        procs.append(proc)
                    else:
                        cmd_line = proc.cmdline()
                        if len(cmd_line) < 5:
                            continue
                        for i in range(len(cmd_line)):
                            if cmd_line[i] == "-execute":
                                for item in cmd_line[i+1].split(";"):
                                    if "svr_slave" in item:
                                        if int(item.split(" ")[-1]) == slave_id:
                                            procs.append(proc)
            except psutil.NoSuchProcess:
                pass
        return procs
    
    def get_process_by_port(self,port):
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN' and conn.laddr.port == port:
                try:
                    process = psutil.Process(conn.pid)
                    return process
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        return None
    def check_port(self, port):
        for conn in psutil.net_connections('udp'):
            if conn.laddr.port == port:
                return True
        return False
        
    def get_process_priority(proc_name):
        pid = False
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                pid = proc.pid
        if pid:
            p = next((proc for proc in psutil.process_iter() if proc.pid == pid),None)
            prio = p.nice()
            prio = (str(prio)).replace("Priority.","")
            prio = prio.replace("_PRIORITY_CLASS","")
            if prio == "64": prio = "IDLE"
            elif prio == "128": prio = "HIGH"
            elif prio == "256": prio = "REALTIME"
            return prio
        else: return "N/A"

    def get_cpu_count(self):
        return self.cpu_count
    
    def get_cpu_name(self):
        if self.get_os_platform() == "win32":
            return self.cpu_name
        elif self.get_os_platform() == "linux":
            # Linux uses the /proc/cpuinfo file
            with open('/proc/cpuinfo') as f:
                for line in f:
                    if line.startswith('model name'):
                        return line.split(':')[1].strip()
                    
    def format_memory(self,value):
        if value < 1:
            return round(value * 1024)  # Convert to MB and round
        else:
            return round(value, 2)  # Keep value in GB, round to 2 decimal points

    def get_total_ram(self):
        total_ram_gb = self.total_ram / (1024 ** 3)  # Convert bytes to GB
        return self.format_memory(total_ram_gb)

    def get_used_ram(self):
        used_ram_gb = psutil.virtual_memory().used / (1024 ** 3)  # Convert bytes to GB
        return self.format_memory(used_ram_gb)

    def get_cpu_load(self):
        # Getting loadover15 minutes
        load1, load5, load15 = psutil.getloadavg()

        cpu_usage = (load1/os.cpu_count()) * 100

        return round(cpu_usage, 2)

    def get_os_platform(self):
        return self.os_platform
    
    def get_num_reserved_cpus(self):
        if self.cpu_count <=4:
            return 1
        elif self.cpu_count >4 and self.cpu_count <= 12:
            return 2
        elif self.cpu_count >12:
            return 4
        
    def get_total_allowed_servers(self,svr_total_per_core):
        total = svr_total_per_core * self.cpu_count
        if self.cpu_count <=4:
            total -= 1
        elif self.cpu_count >4 and self.cpu_count <= 12:
            total -= 2
        elif self.cpu_count >12:
            total -= 4
        return total
    
    def get_server_affinity(self,server_id,svr_total_per_core):
        server_id = int(server_id)
        affinity = []

        if svr_total_per_core > 3:
            raise Exception("You cannot specify more than 3 servers per core.")
        elif svr_total_per_core < 0:
            raise Exception("You cannot specify a number less than 1. Must be either 1 or 2.")
        if svr_total_per_core == 1:
            affinity.append(str(self.cpu_count - server_id))
        else:
            t = 0
            for num in range(0, server_id):
                if num % svr_total_per_core == 0:
                    t += 1
            affinity.append(str(self.cpu_count - t))

        return affinity
    
    def get_public_ip(self):
        if self.public_ip:
            return self.public_ip
        return self.lookup_public_ip()
    
    def lookup_public_ip(self):
        try:
            self.public_ip = requests.get('https://4.ident.me').text
        except Exception:
            try:
                self.public_ip = requests.get('http://api.ipify.org').text
            except Exception:
                LOGGER.error("Failed to fetch public IP")
                self.public_ip = None
        return self.public_ip
    
    async def lookup_public_ip_async(self):
        providers = ['https://4.ident.me', 'https://api.ipify.org', 'https://ifconfig.me','https://myexternalip.com/raw','https://wtfismyip.com/text']
        timeout = aiohttp.ClientTimeout(total=5)  # Set the timeout for the request in seconds

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for provider in providers:
                try:
                    async with session.get(provider) as response:
                        if response.status == 200:
                            ip_str = await response.text()
                            try:
                                # Try to construct an IP address object. If it fails, this is not a valid IP.
                                ipaddress.ip_address(ip_str)
                                return ip_str
                            except ValueError:
                                LOGGER.warn(f"Invalid IP received from {provider}. Trying another provider...")
                except asyncio.TimeoutError:
                    LOGGER.warn(f"Timeout when trying to fetch IP from {provider}. Trying another provider...")
                    continue
                except Exception as e:
                    LOGGER.warn(f"Error occurred when trying to fetch IP from {provider}: {e}")
                    continue
            LOGGER.critical("Tried all public IP providers and could not determine public IP address. This will most likely cause issues.")
    
    def get_svr_description(self):
        return f"cpu: {self.get_cpu_name()}"
    
    def find_process_by_cmdline_keyword(self, keyword, proc_name=None):
        for process in psutil.process_iter(['cmdline']):
            if process.info['cmdline']:
                if keyword in process.info['cmdline']:
                    if proc_name:
                        if proc_name == process.name():
                            return process
                    else:
                        return process
        return None
    
    def get_svr_version(self,hon_exe):
        def validate_version_format(version):
            version_parts = version.split('.')
            if len(version_parts) != 4:
                return False

            for part in version_parts:
                try:
                    int(part)
                except ValueError:
                    return False

            return True

        if not exists(hon_exe):
            raise FileNotFoundError(f"File {hon_exe} does not exist.")

        if self.get_os_platform() == "win32":
            version_offset = 88544
            with open(hon_exe, 'rb') as hon_x64:
                hon_x64.seek(version_offset, 1)
                version = hon_x64.read(18)
                # Split the byte array on b'\x00' bytes
                split_bytes = version.split(b'\x00')
                # Decode the byte sequences and join them together
                version = ''.join(part.decode('utf-8') for part in split_bytes if part)

            if not validate_version_format(version):
                raise HoNUnexpectedVersionError("Unexpected game version. Have you merged the wasserver binaries into the HoN install folder?")

        elif self.get_os_platform() == "linux":
            with open(Path(hon_exe).parent / "version.txt", 'r') as f:
                version = f.readline().rstrip('\n')
        
        self.hon_version = version
        return version

    def update_github_repository(self):
        try:
            # Change the current working directory to the HOME_PATH
            os.chdir(HOME_PATH)

            # Run the git pull command
            LOGGER.debug("Checking for upstream HoNfigurator updates.")
            result = subprocess.run(["git", "pull"], text=True, capture_output=True)

            # Log any errors encountered
            if result.stderr and result.returncode != 0:
                LOGGER.error(f"Error encountered while updating: {result.stderr}")

            # Check if the update was successful
            if "Already up to date." not in result.stdout and "Fast-forward" in result.stdout:
                LOGGER.info("Update successful. Relaunching the code...")

                # Relaunch the code
                os.execv(sys.executable, [sys.executable] + sys.argv)
            else:
                LOGGER.debug("HoNfigurator already up to date. No need to relaunch.")
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"Error updating the code: {e}")
    
    def calculate_crc32(self, file_path):
        crc32_func = crcmod.predefined.mkCrcFun('crc-32')
        crc = 0

        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b''):
                crc = crc32_func(chunk, crc)

        return binascii.hexlify(crc.to_bytes(4, 'big')).decode()
    
    def calculate_md5(self, file_path):
        with open(file_path, "rb") as file:
            md5_hash = hashlib.md5()
            chunk_size = 4096

            while chunk := file.read(chunk_size):
                md5_hash.update(chunk)

            return md5_hash.hexdigest()
    
    def unzip_file(self, source_zip, dest_unzip):
        with zipfile.ZipFile(source_zip, 'r') as zip_ref:
            zip_ref.extractall(dest_unzip)
    
    def save_last_working_branch(self):
        with open(HOME_PATH / "logs" / ".last_working_branch", "w") as f:
            f.write(self.get_current_branch_name())

    def get_current_branch_name(self):
        try:
            os.chdir(HOME_PATH)
            branch_name = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                universal_newlines=True
            ).strip()
            return branch_name
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"{HOME_PATH} Not a git repository: {e.output}")
            return None
    
    def get_git_commit_date(self):
        command = 'git log -1 --format="%cd" --date=format-local:"%Y-%m-%d %H:%M:%S"'
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return result.stdout.strip()

    def get_all_branch_names(self):
        try:
            os.chdir(HOME_PATH)
            # Fetch the latest information from the remote repository
            subprocess.run(['git', 'fetch'])

            # Remove any stale remote-tracking branches
            subprocess.run(['git', 'remote', 'prune', 'origin'])

            # Retrieve the branch names from the remote repository
            branch_names = subprocess.check_output(
                ['git', 'for-each-ref', '--format=%(refname:lstrip=3)', 'refs/remotes/origin/'],
                universal_newlines=True
            ).strip()
            branches = [branch.strip() for branch in branch_names.split('\n') if branch.strip() != 'HEAD']

            # Process the branch names, excluding "HEAD"
            return branches
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"{HOME_PATH} Not a git repository: {e.output}")
            return None

    def change_branch(self, target_branch):
        try:
            os.chdir(HOME_PATH)
            current_branch = self.get_current_branch_name()

            if current_branch == target_branch:
                LOGGER.info(f"Already on target branch '{target_branch}'")
                return "Already on target branch"

            subprocess.run(['git','pull',target_branch])
            result = subprocess.run(['git', 'checkout', target_branch], text=True, capture_output=True)

            # Log any errors encountered
            if result.stderr and result.returncode != 0:
                LOGGER.error(f"Error encountered while switching branches: {result.stderr}")
                return result.stderr

            LOGGER.info(f"Switched to branch '{target_branch}'")
            LOGGER.info("Relaunching code into new branch.")
            os.execv(sys.executable, [sys.executable] + sys.argv)
        except subprocess.CalledProcessError as e:
            LOGGER.error(f"Error: Could not switch to branch '{target_branch}', make sure it exists: {e.output}")
