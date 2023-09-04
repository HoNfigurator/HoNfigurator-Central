import argparse
import traceback
import platform
import subprocess
import aiohttp
import asyncio
import aiofiles
import os
import shutil
import ipaddress
import tempfile
import zipfile
from pathlib import Path
import psutil
import re
import hashlib
from tempfile import NamedTemporaryFile
import yaml

# if code is launched independtly
if __name__ == "__main__":
    import step_certificate
    LOGGER = None
    stop_event = asyncio.Event()
    roles_database = None
else:
    # if imported into honfigurator main
    import utilities.step_certificate as step_certificate
    from cogs.misc.logger import get_logger, set_filebeat_auth_token, get_filebeat_auth_token, set_filebeat_auth_url, set_filebeat_status, get_misc, get_filebeat_auth_url, get_home

    from cogs.db.roles_db_connector import RolesDatabase
    from cogs.handlers.events import stop_event
    LOGGER = get_logger()
    roles_database = RolesDatabase()
    MISC = get_misc()

def print_or_log(log_lvl='info', msg=''):
    log_lvl = log_lvl.lower()
    if LOGGER:
        getattr(LOGGER, log_lvl)(msg)
    else:
        print(msg)

def get_filebeat_path():
    operating_system = platform.system()
    if operating_system == "Windows":
        return os.path.join(os.environ["ProgramFiles"], "filebeat")
    elif operating_system == "Linux":
        return os.path.join("/", "usr", "share", "filebeat")
    else:
        return "Unsupported operating system"

def get_filebeat_crt_path():
    return os.path.join(get_filebeat_path(), "client.crt")

def get_filebeat_key_path():
    return os.path.join(get_filebeat_path(), "client.key")

def get_filebeat_csr_path():
    return os.path.join(get_filebeat_path(), "client.csr")

def calculate_file_hash(file_path):
    with open(file_path, "rb") as file:
        hash_object = hashlib.sha256()
        for chunk in iter(lambda: file.read(4096), b""):
            hash_object.update(chunk)
    return hash_object.hexdigest()

def read_admin_value_from_filebeat_config(config_path):
    admin_value = None
    with open(config_path) as file:
        config_data = file.read()
        match = re.search(r"Admin:\s*([^\n]+)", config_data)
        if match:
            admin_value = match.group(1).strip()
    return admin_value

async def filebeat_status():
    if LOGGER: # pass the reference through
        step_certificate.set_logger(LOGGER)

    installed = check_filebeat_installed()
    certificate_exists = check_certificate_exists(get_filebeat_crt_path(), get_filebeat_key_path())
    certificate_status = 'non-existent'

    if certificate_exists:
        valid_to = step_certificate.get_certificate_valid_to(get_filebeat_crt_path())
        if step_certificate.is_certificate_expired(get_filebeat_crt_path()):
            certificate_status = f"expired ({valid_to})"
        elif step_certificate.is_certificate_expiring(get_filebeat_crt_path()):
            certificate_status = f"expiring soon ({valid_to})"
        else:
            certificate_status = f"valid (until {valid_to})"

    filebeat_running = False
    if MISC.get_proc('filebeat') or MISC.get_proc('filebeat.exe'):
        filebeat_running = True

    status_dict = {
        "installed": installed,
        "running": filebeat_running,
        "certificate_exists": certificate_exists,
        "certificate_status": certificate_status,
        "pending_oauth_url": True if get_filebeat_auth_url() else False
    }

    set_filebeat_status(status_dict)

    return status_dict

operating_system = platform.system()
global_config = None

if operating_system == "Windows":
    windows_filebeat_install_dir = os.path.join(os.environ["ProgramFiles"], "FileBeat")

def check_filebeat_installed():
    if operating_system == "Linux":
        # Check if filebeat is already installed
        result = subprocess.run(["dpkg-query", "-W", "-f='${Status}'", "filebeat"], stdout=subprocess.PIPE, text=True)
        if "install ok installed" in result.stdout:
            print_or_log('debug',"Filebeat is already installed. Skipping installation.")
            return True
    else:
        if os.path.exists(Path(windows_filebeat_install_dir) / "filebeat.exe"):
            print_or_log('debug',"Filebeat is already installed. Skipping installation.")
            return True


def is_elastic_source_added():
    # Check if the Elastic source is already added to the apt sources list
    check_sources_command = ["grep", "-q", "artifacts.elastic.co", "/etc/apt/sources.list"]
    result = subprocess.run(check_sources_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode == 0

async def install_filebeat_linux():
    # Download and install the Public Signing Key:
    # subprocess.run("wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo apt-key add -", shell=True, check=True)
    await run_command(["wget","-qO","-","https://artifacts.elastic.co/GPG-KEY-elasticsearch","|","sudo","apt-key","add","-"])

    # Check if the Elastic source is already added before adding it
    if not is_elastic_source_added():
        # Save the repository definition to /etc/apt/sources.list.d/elastic-8.x.list:
        # subprocess.run('echo "deb https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee -a /etc/apt/sources.list.d/elastic-8.x.list', shell=True, check=True)
        await run_command(["echo","'deb https://artifacts.elastic.co/packages/8.x/apt stable main'","|","sudo","tee","-a","/etc/apt/sources.list.d/elastic-8.x.list"])

    # Update package lists for upgrades for packages that need upgrading
    # subprocess.run(["sudo", "apt-get", "update"], check=True)
    await run_command(["sudo","apt-get","update"])

    # Install filebeat
    # subprocess.run(["sudo", "apt-get", "install", "filebeat"], check=True)
    await run_command(["sudo","apt-get","install","filebeat"])
    return True

async def install_filebeat_windows():
    # Download and install Filebeat using Python
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_file = os.path.join(temp_dir, "filebeat-8.8.2-windows-x86_64.zip")
        url = "https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-8.8.2-windows-x86_64.zip"

        # Download the Filebeat ZIP file
        async with aiohttp.ClientSession() as session:
            async with session.get(url, ssl=False) as response:
                if response.status == 200:
                    content = await response.read()
                    async with aiofiles.open(zip_file, "wb") as file:
                        await file.write(content)
                    print_or_log('info',"Filebeat ZIP file downloaded successfully.")
                else:
                    print_or_log('error',"Failed to download Filebeat ZIP file.")

        # Extract ZIP contents to temporary folder
        temp_extract_folder = os.path.join(temp_dir, "filebeat-extract")
        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            zip_ref.extractall(temp_extract_folder)
        print_or_log('info',"Filebeat ZIP file extracted successfully.")

        # Move extracted files to destination folder
        extracted_folder = os.listdir(temp_extract_folder)[0]
        source_folder = os.path.join(temp_extract_folder, extracted_folder)

        # Create destination folder if it doesn't exist
        if not os.path.exists(windows_filebeat_install_dir):
            os.makedirs(windows_filebeat_install_dir)
            print_or_log('info',f"Created destination folder: {windows_filebeat_install_dir}")

        extracted_files = os.listdir(source_folder)
        for file in extracted_files:
            source_path = os.path.join(source_folder, file)
            destination_path = os.path.join(windows_filebeat_install_dir, os.path.basename(file))
            shutil.move(source_path, destination_path)
        print_or_log('info',f"Filebeat installed successfully at: {windows_filebeat_install_dir}")
        command = [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(windows_filebeat_install_dir) / "install-service-filebeat.ps1")
        ]

        process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()
        if process.returncode == 0:
            print_or_log('info', "Filebeat service installed successfully.")
        else:
            print_or_log('error', f"Failed to install Filebeat service. Error: {stderr.decode()}")

        # Remove the extracted folder
        os.rmdir(source_folder)
        print_or_log('info',"Extracted folder removed.")
        return True

async def uninstall_filebeat_linux():
    # Uninstall Filebeat on Linux
    # subprocess.run(["sudo", "systemctl", "stop", "filebeat"])
    await run_command(["sudo", "systemctl", "stop", "filebeat"])
    # subprocess.run(["sudo", "apt-get", "remove", "filebeat"])
    await run_command(["sudo", "apt-get", "remove", "filebeat"])

async def uninstall_filebeat_windows():
    filebeat_install_dir = os.path.join(os.environ["ProgramFiles"], "FileBeat")
    if os.path.exists(Path(filebeat_install_dir) / "filebeat.exe"):
        command = [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(filebeat_install_dir) / "uninstall-service-filebeat.ps1")
        ]

        # result = subprocess.run(command, capture_output=True, text=True)
        result = await run_command(command)

        if result.returncode == 0:
            shutil.rmtree(filebeat_install_dir)
            print_or_log('info',"Filebeat uninstalled successfully.")
        else:
            print_or_log('info',"Failed to uninstall Filebeat.")
    else:
        print_or_log('info',"Filebeat is not installed.")

def get_process_environment(process,var):
    # process = psutil.Process(pid)
    env_vars = process.environ()

    # Access specific environmental variables
    requested_env = env_vars.get(var)

    return requested_env

def check_process(process_name, exclude = []):
    for process in psutil.process_iter(['name']):
        if process.info['name'] == process_name:
            if process not in exclude:
                return process

    return None

def extract_settings_from_commandline(commandline, setting):
    result = None

    # Construct the regex pattern dynamically using the provided setting
    pattern = r'Set {} ([^;]+)'.format(setting)

    # Find the occurrence of the setting in the command line
    for _ in commandline:
        match = re.search(pattern, _)
        if match: break

    # Extract the value if a match is found
    if match:
        result = match.group(1)

    return result

def check_certificate_exists(crt_path, key_path):
    certificate_exists = Path(crt_path).is_file() and Path(key_path).is_file()
    return certificate_exists

async def request_client_certificate(svr_name, filebeat_path):

    try:
        # Check if the certificate files already exist
        csr_file_path = get_filebeat_csr_path()
        crt_file_path = get_filebeat_crt_path()
        key_file_path = get_filebeat_key_path()
        certificate_exists = check_certificate_exists(crt_file_path, key_file_path)

        if certificate_exists:
            if step_certificate.is_certificate_expiring(crt_file_path):
                print_or_log('info',"Renewing existing client certificate...")
                # Construct the command for certificate renewal
                result = step_certificate.renew_certificate(crt_file_path,key_file_path)
                if (isinstance(result,bool) and result) or result.returncode == 0:
                    return True
                else:
                    # Certificate request failed
                    error_message = result.stderr.strip()
                    print_or_log('info',f"Error: {error_message}")
                    return False

            elif step_certificate.is_certificate_expired(crt_file_path):
                pass
            else:
                return True
            
        print_or_log('info',"Requesting new client certificate...")
        # Construct the command for new certificate request
        if __name__ == "__main__":
            return await step_certificate.discord_oauth_flow_stepca(svr_name, csr_file_path, crt_file_path, key_file_path)

        else:
            return await step_certificate.discord_oauth_flow_stepca(svr_name, csr_file_path, crt_file_path, key_file_path, token=get_filebeat_auth_token())

    except Exception as e:
        print_or_log('error',f"Encountered an error while requesting a client certificate. {traceback.format_exc()}")

async def get_discord_user_id_from_api(discord_id):
    api_url = f'https://management.honfigurator.app:3001/api-ui/getDiscordUsername/{discord_id}'

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, ssl=False) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('username')
                else:
                    print(f"Failed to get Discord username for ID: {discord_id}")
                    return None
    except aiohttp.ClientError as e:
        print(f"Error occurred while making the API request: {e}")
        return None

async def get_public_ip():
    providers = ['https://4.ident.me', 'https://api.ipify.org', 'https://ifconfig.me','https://myexternalip.com/raw','https://wtfismyip.com/text']
    timeout = aiohttp.ClientTimeout(total=5)  # Set the timeout for the request in seconds

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for provider in providers:
            try:
                async with session.get(provider, ssl=False) as response:
                    if response.status == 200:
                        ip_str = await response.text()
                        try:
                            # Try to construct an IP address object. If it fails, this is not a valid IP.
                            ipaddress.ip_address(ip_str)
                            return ip_str
                        except ValueError:
                            print_or_log('warn',f"Invalid IP received from {provider}. Trying another provider...")
            except asyncio.TimeoutError:
                print_or_log('warn',f"Timeout when trying to fetch IP from {provider}. Trying another provider...")
                continue
            except Exception as e:
                print_or_log('warn',f"Error occurred when trying to fetch IP from {provider}: {e}")
                continue

    LOGGER.critical("Tried all public IP providers and could not determine public IP address. This will most likely cause issues.")
    return None


async def configure_filebeat(silent=False,test=False):
    def get_log_paths(process):
        if operating_system == "Windows":
            slave_log = Path(get_process_environment(process,"USERPROFILE")) / "Documents" / "Heroes of Newerth x64" / "KONGOR" / "logs" / "*.clog"
            match_log = Path(get_process_environment(process,"USERPROFILE")) / "Documents" / "Heroes of Newerth x64" / "KONGOR" / "logs" / "M*.log"
        else:
            slave_log = Path(process.cwd()).parent / "config" / "KONGOR" / "logs" / "*.clog"
            match_log = Path(process.cwd()).parent / "config" / "KONGOR" / "logs" / "M*.log"
        
        return slave_log, match_log
    
    def resolve_filestream_indentation(text, target):
        count = 0
        new_text = ''
        for line in text.split('\n'):
            if target in line:
                count += 1
                if count == 2:
                    line = '  ' + line
            new_text += line + '\n'
        return new_text
    
    def perform_config_replacements(svr_name, svr_location, slave_log, match_log, launcher, external_ip, existing_discord_id, looked_up_discord_username, destination_folder):
        server_values = {
            'Name': svr_name,
            'Launcher': launcher,
            'Admin': looked_up_discord_username if looked_up_discord_username and not isinstance(looked_up_discord_username,bool) else existing_discord_id,
            'Region': svr_location,
            'Logging_Config_Version': '1.3',
            'Public_IP': external_ip if __name__ == "__main__" else global_config['hon_data']['svr_ip'],
            'HoN_User': global_config['hon_data']['svr_login'],
            'Servers_per_Core': global_config['hon_data']['svr_total_per_core'],
            'CPU': global_config['system_data']['cpu_name'],
            'CPU_Num_Cores': global_config['system_data']['cpu_count'],
            'RAM': global_config['system_data']['total_ram'],
            'Priority': global_config['hon_data']['svr_priority'],
            'Affinity_Override': global_config['hon_data']['svr_override_affinity'] if operating_system == 'Windows' else None,
            'BotMatch_Allowed': global_config['hon_data']['svr_enableBotMatch'],
            'GitHub_Branch': MISC.github_branch,
            'HoN_Server_Version': MISC.get_svr_version(global_config['hon_data']['hon_executable_path']),
            'HoNfigurator_API_Port': global_config['hon_data']['svr_api_port']
        }
        filebeat_inputs = {}
        filebeat_inputs['slave_logs'] = \
        {
            'type': 'filestream',
            'id': 'slave_logs',
            'enabled': True,
            'paths': [str(Path(slave_log))],
            'ignore_older': '24h',
            'scan_frequency': '60s',
            'exclude_files': '[".gz$"]',
            'fields_under_root': True,
            'fields': {
                'Server': server_values,
                'Log_Type': 'console'
            }
        }

        filebeat_inputs['match_logs'] = \
        {
            'type': 'filestream',
            'id': 'match_logs',
            'enabled': True,
            'paths': [str(Path(match_log))],
            'ignore_older': '24h',
            'scan_frequency': '60s',
            'exclude_files': '[".gz$"]',
            'fields_under_root': True,
            'include_lines': ['PLAYER_CHAT','PLAYER_CONNECT','PLAYER_TEAM_CHANGE','PLAYER_SELECT','PLAYER_SWAP','INFO_SETTINGS'],
            'fields': {
                'Server': server_values,
                'Log_Type': 'match'
            }
        }
        
        if global_config:
            if operating_system == "Windows" and global_config['hon_data']['man_enableProxy']:
                filebeat_inputs['proxy_logs'] = \
                {
                    'type': 'filestream',
                    'id': 'proxy_logs',
                    'enabled': True,
                    'paths': [str(Path(global_config['hon_data']['hon_artefacts_directory'] / 'HoNProxyManager' / 'proxy*.log'))],
                    'ignore_older': '24h',
                    'scan_frequency': '60s',
                    'exclude_files': '[".gz$"]',
                    'fields_under_root': True,
                    'fields': {
                        'Server': server_values,
                        'Log_Type': 'proxy'
                    }
                }

            filebeat_inputs['honfigurator_logs'] = \
            {
                'type': 'filestream',
                'id': 'honfigurator_logs',
                'enabled': True,
                'paths': [str(Path(get_home() / 'logs' / 'server.log'))],
                'ignore_older': '24h',
                'scan_frequency': '60s',
                'exclude_files': '[".gz$"]',
                'fields_under_root': True,
                'fields': {
                    'Server': server_values,
                    'Log_Type': 'honfigurator'
                },
                'parsers': [
                    {
                        'multiline': {
                            'type': 'pattern',
                            'pattern': '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}',
                            'negate': True,
                            'match': 'after'
                        }
                    }
                ]
            }
        
        if operating_system == "Windows":
            filebeat_inputs['slave_logs']['encoding'] = 'utf-16le'
            filebeat_inputs['match_logs']['encoding'] = 'utf-16le'
            if 'proxy_logs' in filebeat_inputs:
                filebeat_inputs['proxy_logs']['encoding'] = 'utf-8' 
        else:
            filebeat_inputs['slave_logs']['charset'] = 'BINARY'
            filebeat_inputs['match_logs']['charset'] = 'BINARY'
        if 'honfigurator_logs' in filebeat_inputs:
            filebeat_inputs['honfigurator_logs']['encoding'] = 'utf-8'

        filebeat_config = {
            'filebeat.inputs': list(filebeat_inputs.values()),
            'filebeat.config.modules': {
                'path': '${path.config}/modules.d/*.yml',
                'reload.enabled': False
            },
            'setup.template.settings': {
                'index.number_of_shards': '1'
            },
            'output.logstash': {
                'hosts': 'hon-elk.honfigurator.app:5044',
                'ssl.certificate_authorities': str(Path(destination_folder) / "honfigurator-chain.pem"),
                'ssl.certificate': str(Path(destination_folder) / "client.crt"),
                'ssl.key': str(Path(destination_folder) / "client.key")
            },
            'processors': [
                {'add_host_metadata': {'when.not.contains.tags': 'forwarded'}},
                {'add_locale': None}
            ],
            'filebeat.registry.flush': '60s'
        }

        yaml_config = yaml.dump(filebeat_config)
        return yaml_config.encode('utf-8')

    external_ip = await get_public_ip()
    if not external_ip:
        print_or_log('error','Obtaining public IP address failed.')

    honfigurator_ca_chain_url = "https://honfigurator.app/honfigurator-chain.pem"
    honfigurator_ca_chain_bundle_url = "https://honfigurator.app/honfigurator-chain-bundle.pem"

    destination_folder = get_filebeat_path()
    config_folder = destination_folder if operating_system == "Windows" else "/etc/filebeat"

    os.makedirs(destination_folder, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(honfigurator_ca_chain_url, ssl=False) as response:
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(Path(destination_folder) / "honfigurator-chain.pem", 'wb') as chain_file:
                    await chain_file.write(content)
        async with session.get(honfigurator_ca_chain_bundle_url, ssl=False) as response:
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(Path(destination_folder) / "honfigurator-chain-bundle.pem", 'wb') as chain_file:
                    await chain_file.write(content)
    
    config_file_path = os.path.join(config_folder, "filebeat.yml")

    exclude = []

    i=0

    svr_name = None
    svr_location = None
    svr_desc = None
    slave_log = None
    match_log = None

    if global_config is not None and 'hon_data' in global_config:
        svr_name = global_config['hon_data'].get('svr_name')
        svr_location = global_config['hon_data'].get('svr_location')
        svr_desc = 'using honfigurator' # this is a placeholder basically, so it knows it's honfigurator.
        
        slave_log = str(Path(global_config['hon_data'].get('hon_logs_directory')) / "*.clog")
        match_log = str(Path(global_config['hon_data'].get('hon_logs_directory')) / "*.log")

    if svr_name is None or svr_location is None:
    
        while not stop_event.is_set():
            print_or_log('info',f"Scanning for running hon executable.. timeout {i}/30 seconds")
            i+=1
            await asyncio.sleep(1)
            process = check_process("hon_x64.exe" if not global_config else global_config['hon_data']['hon_executable_name'], exclude) if operating_system == "Windows" else check_process("hon-x86_64-server" if not global_config else global_config['hon_data']['hon_executable_name'], exclude)
            if process and len(process.cmdline()) > 4:
                break
            elif process and len(process.cmdline()) < 4 and process not in exclude:
                exclude.append(process)
                print_or_log('info',f"Excluded {process.pid}\n\t{process.cmdline()}")

            if i >=30:
                print_or_log('info',"Please ensure your hon server is running prior to launching the script.")
                return
    
    # Perform text replacements
    if not svr_name: svr_name = extract_settings_from_commandline(process.cmdline(), "svr_name")
    space_count = svr_name.count(' ')
    svr_name = svr_name.rsplit(' ', 2)[0] if space_count >= 2 else svr_name
    if not svr_location: svr_location = extract_settings_from_commandline(process.cmdline(), "svr_location")

    if not slave_log: slave_log, match_log = get_log_paths(process)
    if not svr_desc: svr_desc = extract_settings_from_commandline(process.cmdline(),"svr_description")
    launcher = "HoNfigurator" if svr_desc else "COMPEL"

    looked_up_discord_username = await request_client_certificate(svr_name, Path(destination_folder))
        
    existing_discord_id, old_config_hash = None, None
    if os.path.exists(config_file_path):
        old_config_hash = calculate_file_hash(config_file_path)
        existing_discord_id = read_admin_value_from_filebeat_config(config_file_path)
    
    if not existing_discord_id and isinstance(looked_up_discord_username,bool):
        if roles_database:
            looked_up_discord_username = await get_discord_user_id_from_api(roles_database.get_discord_owner_id())
        else:
            looked_up_discord_username = await step_certificate.discord_oauth_flow_stepca(svr_name, get_filebeat_csr_path(), get_filebeat_crt_path(), get_filebeat_key_path(),get_filebeat_auth_token())
    
    if not looked_up_discord_username:
        print_or_log('error', 'Failed to obtain discord user information and finish setting up the server for game server log submission.')
        return
        
    filebeat_config = perform_config_replacements(svr_name, svr_location, slave_log, match_log, launcher, external_ip, existing_discord_id, looked_up_discord_username, destination_folder)

    temp_dir = tempfile.TemporaryDirectory()
    temp_file_path = Path(temp_dir.name) / 'filebeat.yml'
    async with aiofiles.open(temp_file_path, 'wb') as temp_file:
        await temp_file.write(filebeat_config)

    new_config_hash = calculate_file_hash(temp_file_path)

    if old_config_hash != new_config_hash:
        shutil.move(temp_file_path, config_file_path)
        print_or_log('info',f"Filebeat configuration file downloaded and placed at: {config_file_path}")
        return True
    else:
        print_or_log('debug',"No configuration changes required")
        return False
    

# Constants for repeated strings
STARTED_SUCCESSFULLY = "Filebeat started successfully."
FAILED_START = "Failed to start Filebeat."
ALREADY_RUNNING = "Filebeat is already running."
STOPPED_SUCCESSFULLY = "Filebeat stopped successfully."
FAILED_STOP = "Failed to stop Filebeat."
ALREADY_STOPPED = "Filebeat is already stopped."


async def run_command(command_list, success_message=None):
    process = await asyncio.create_subprocess_shell(' '.join(command_list), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        if success_message: print(success_message)
        return process
    else:
        print(f"Command: {' '.join(command_list)}")
        print(f"Return code: {process.returncode}")
        print(f"Error: {stderr.decode()}")
        return process

async def restart_filebeat(filebeat_changed, silent):
    async def restart():
        if operating_system == "Windows":
            process_name = "filebeat.exe"
            command_list = ["powershell.exe", "Restart-Service", "-Name", "filebeat"]
            success_message = "Filebeat service restarted successfully on Windows."
            if await run_command(command_list, success_message):
                return True

        else:  # Linux
            process_name = "filebeat"
            stop_command_list = ["sudo", "systemctl", "stop", "filebeat"]
            start_command_list = ["sudo", "systemctl", "start", "filebeat"]
            if check_process(process_name):
                await run_command(stop_command_list, STOPPED_SUCCESSFULLY)
            if await run_command(start_command_list, STARTED_SUCCESSFULLY):
                return True
        
    filebeat_running = False
    if (operating_system == "Windows" and check_process("filebeat.exe")) or (operating_system == "Linux" and check_process("filebeat")):
        filebeat_running = True

    if silent:
        # If silent, only restart filebeat if config has changed and it's currently running
        if filebeat_changed and filebeat_running:
            if await restart():
                print_or_log('info',"Setup complete! Please visit https://hon-elk.honfigurator.app:5601 to view server monitoring")
    else:
        # If not silent, start filebeat if stopped, or restart if config changed
        if filebeat_changed and filebeat_running:
            if await restart():
                print_or_log('info',"Setup complete! Please visit https://hon-elk.honfigurator.app:5601 to view server monitoring")
        elif not filebeat_running:
            await restart()

def add_cron_job(command):
    # Get current cron jobs
    current_crons = subprocess.run(["crontab", "-l"], text=True, capture_output=True).stdout
    
    # Don't add job if it's already there
    if command in current_crons:
        return
    
    with NamedTemporaryFile(delete=False) as tmp:
        # Write current cron jobs into temporary file
        tmp.write(current_crons.encode())
        # Add new cron job
        tmp.write(f"\n0 0 * * * {command}\n".encode())
        
    # Update cron jobs from the temporary file
    subprocess.run(["crontab", tmp.name])
    # Delete the temporary file
    os.unlink(tmp.name)

# Check the system
async def install_filebeat():
    if operating_system == "Windows":
        installed = await install_filebeat_windows()
        return installed
    elif operating_system == "Linux":
        installed = await install_filebeat_linux()
        return installed
    else:
        print_or_log('info',"Unsupported operating system.")
        return False

def remove_cron_job(command):
    try:
        # output the current crontab to a temporary file
        tmpfile = "/tmp/crontab.txt"
        subprocess.run(["crontab", "-l"], stdout=open(tmpfile, 'w'))

        # read the file, remove the line, and write it back out
        with open(tmpfile, 'r') as f:
            lines = f.readlines()
        with open(tmpfile, 'w') as f:
            for line in lines:
                if command not in line:
                    f.write(line)

        # load the revised crontab
        subprocess.run(["crontab", tmpfile])

        # remove the temporary file
        os.remove(tmpfile)

    except Exception as e:
        print_or_log('error',f"Failed to remove cron job: {e}")

async def main(config=None, from_main=True):
    try:
        global global_config

        global_config = config
        # Parse command-line arguments
        parser = argparse.ArgumentParser()
        parser.add_argument("-silent", action="store_true", help="Run in silent mode without asking for Discord ID")
        parser.add_argument("-test", action="store_true", help="Use an experimental filebeat configuration file")
        args = parser.parse_args()

        if from_main:
            print_or_log('info','Setting up Filebeat. This is used to submit game match logs for trend analysis and is required by game server hosts.')
        
        if not check_filebeat_installed():
            await install_filebeat()
        
        if __name__ == "__main__":
            await step_certificate.main(stop_event)
        else: await step_certificate.main(stop_event, LOGGER, set_filebeat_auth_token, set_filebeat_auth_url)

        filebeat_changed = False
        if await configure_filebeat(silent=args.silent, test=args.test):
            filebeat_changed = True
            # Delete scheduled task on Windows
            if operating_system == "Windows":
                task_name = "Filebeat Task"

                # Check if the task already exists
                task_query = subprocess.run(["schtasks", "/query", "/tn", task_name], capture_output=True, text=True)
                if "ERROR: The system cannot find the file specified." not in task_query.stderr:
                    # Delete the scheduled task
                    subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"])
                    print_or_log('info',"Scheduled task deleted successfully.")

            # Delete cron job on Linux
            if operating_system == "Linux":
                script_path = os.path.abspath(__file__)
                command = f"python3 {script_path} -silent"
                remove_cron_job(command)
                print_or_log('info',"Cron job deleted successfully.")

        # if filebeat_changed:
        certificate_exists = check_certificate_exists(get_filebeat_crt_path(), get_filebeat_key_path())
        if certificate_exists:
            await restart_filebeat(filebeat_changed, silent=args.silent)

        if not __name__ == "__main__":
            await filebeat_status()    # sets the overall status of filebeat for retreival by other components
        
        return True

    except asyncio.CancelledError:
        # Perform any necessary cleanup or handling for cancellation here
        print_or_log('info', 'Filebeat setup task was canceled. Performing cleanup...')
        # Cleanup code goes here - can't think of any.
        return  # suppress the CancelledError and not propagate it further

if __name__ == "__main__":
    asyncio.run(main())