import argparse
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

# if code is launched independtly
if __name__ == "__main__":
    import step_certificate
    LOGGER = None
    stop_event = asyncio.Event()
else:
    # if imported into honfigurator main
    import utilities.step_certificate as step_certificate
    from cogs.misc.logger import get_logger, set_filebeat_auth_token, get_filebeat_auth_token, set_filebeat_auth_url
    from cogs.handlers.events import stop_event
    LOGGER = get_logger()

def print_or_log(log_lvl='info', msg=''):
    if LOGGER:
        getattr(LOGGER, log_lvl)(msg)
    else:
        print(msg)

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

operating_system = platform.system()
global_config = None

if operating_system == "Windows":
    windows_filebeat_install_dir = os.path.join(os.environ["ProgramFiles"], "FileBeat")

def check_filebeat_installed():
    if operating_system == "Linux":
        # Check if filebeat is already installed
        result = subprocess.run(["dpkg-query", "-W", "-f='${Status}'", "filebeat"], stdout=subprocess.PIPE, text=True)
        if "install ok installed" in result.stdout:
            print_or_log('info',"Filebeat is already installed. Skipping installation.")
            return True
    else:
        if os.path.exists(Path(windows_filebeat_install_dir) / "filebeat.exe"):
            print_or_log('info',"Filebeat is already installed. Skipping installation.")
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
            async with session.get(url) as response:
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

async def request_client_certificate(svr_name, filebeat_path):

    try:
        # Check if the certificate files already exist
        csr_file_path = filebeat_path / 'client.csr'
        crt_file_path = filebeat_path / 'client.crt'
        key_file_path = filebeat_path / 'client.key'
        certificate_exists = crt_file_path.is_file() and key_file_path.is_file()

        if certificate_exists and not step_certificate.is_certificate_expiring(crt_file_path):
            print_or_log('info',"Renewing existing client certificate...")
            # Construct the command for certificate renewal
            result = step_certificate.renew_certificate(crt_file_path,key_file_path)
            if (isinstance(result,bool) and result) or result.returncode == 0:
                return True
            
            else:
                # Certificate request failed
                error_message = result.stderr.strip()
                print_or_log('info',f"Error: {error_message}")
        else:
            print_or_log('info',"Requesting new client certificate...")
            # Construct the command for new certificate request
            return await step_certificate.discord_oauth_flow_stepca(svr_name, csr_file_path, crt_file_path, key_file_path, token=get_filebeat_auth_token())

    except Exception as e:
        print_or_log('error',f"Encountered an error while requesting a client certificate. {e}")

async def get_public_ip():
    providers = ['https://api.ipify.org', 'https://ifconfig.me','https://myexternalip.com/raw','https://wtfismyip.com/text']
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
                            print(f"Invalid IP received from {provider}: {ip_str}. Trying another provider...")
            except asyncio.TimeoutError:
                print(f"Timeout when trying to fetch IP from {provider}. Trying another provider...")
                continue
            except Exception as e:
                print(f"Error occurred when trying to fetch IP from {provider}: {e}")
                continue

    print("All providers failed to fetch the public IP.")
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

    def perform_config_replacements(filebeat_config, svr_name, svr_location, slave_log, match_log, launcher, external_ip, existing_discord_id, looked_up_discord_username, destination_folder):
        encoding = "encoding: utf-16le" if operating_system == "Windows" else "charset: BINARY"

        replacements = {
            b"$server_name": str.encode(svr_name),
            b"$id": str.encode(svr_name.replace(" ", "-")),
            b"$region": str.encode(svr_location),
            b"$slave_log": str.encode(str(slave_log)),
            b"$match_log": str.encode(str(match_log)),
            b"$server_launcher": str.encode(launcher),
            b"0.0.0.0": str.encode(external_ip),
            b"charset: $encoding": str.encode(encoding),
            b"$ca_chain": str.encode(str(Path(destination_folder) / "honfigurator-chain.pem")),
            b"$client_cert": str.encode(str(Path(destination_folder) / "client.crt")),
            b"$client_key": str.encode(str(Path(destination_folder) / "client.key"))
        }

        if looked_up_discord_username and not isinstance(looked_up_discord_username,bool):
            discord_id = looked_up_discord_username
        elif existing_discord_id == "$discord_id":
            discord_id = input(f"What is your discord user name?: ")
        elif existing_discord_id:
            discord_id = existing_discord_id

        print_or_log('info',f"Discord Name: {discord_id}")
        replacements[b"$discord_id"] = str.encode(discord_id)

        for old, new in replacements.items():
            filebeat_config = filebeat_config.replace(old, new)
        
        return filebeat_config

    external_ip = await get_public_ip()
    if not external_ip:
        print_or_log('error','Obtaining public IP address failed.')

    filebeat_config_url = "https://honfigurator.app/hon-server-monitoring/filebeat-test.yml" if test else "https://honfigurator.app/hon-server-monitoring/filebeat.yml"
    honfigurator_ca_chain_url = "https://honfigurator.app/honfigurator-chain.pem"
    honfigurator_ca_chain_bundle_url = "https://honfigurator.app/honfigurator-chain-bundle.pem"

    destination_folder = os.path.join(os.environ["ProgramFiles"], "filebeat") if operating_system == "Windows" else "/usr/share/filebeat"
    config_folder = destination_folder if operating_system == "Windows" else "/etc/filebeat"

    os.makedirs(destination_folder, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        async with session.get(honfigurator_ca_chain_url) as response:
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(Path(destination_folder) / "honfigurator-chain.pem", 'wb') as chain_file:
                    await chain_file.write(content)
        async with session.get(honfigurator_ca_chain_bundle_url) as response:
            if response.status == 200:
                content = await response.read()
                async with aiofiles.open(Path(destination_folder) / "honfigurator-chain-bundle.pem", 'wb') as chain_file:
                    await chain_file.write(content)

    async with aiohttp.ClientSession() as session:
        async with session.get(filebeat_config_url) as response:
            if response.status != 200:
                print_or_log('info',"Failed to download Filebeat configuration file.")
                return
            filebeat_config = await response.read()
    
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
            process = check_process("hon_x64.exe", exclude) if operating_system == "Windows" else check_process("hon-x86_64-server", exclude)
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
    print_or_log('info',f"Details\n\tsvr name: {svr_name}\n\tsvr location: {svr_location}")

    looked_up_discord_username = await request_client_certificate(svr_name, Path(destination_folder))
    if not looked_up_discord_username:
        print_or_log('error', 'Failed to obtain discord user information and finish setting up the server for game server log submission.')
        return
        
    existing_discord_id, old_config_hash = None, None
    if os.path.exists(config_file_path):
        old_config_hash = calculate_file_hash(config_file_path)
        existing_discord_id = read_admin_value_from_filebeat_config(config_file_path)
        
    filebeat_config = perform_config_replacements(filebeat_config, svr_name, svr_location, slave_log, match_log, launcher, external_ip, existing_discord_id, looked_up_discord_username, destination_folder)

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
        print_or_log('info',"No configuration changes required")
        return False
    

# Constants for repeated strings
STARTED_SUCCESSFULLY = "Filebeat started successfully."
FAILED_START = "Failed to start Filebeat."
ALREADY_RUNNING = "Filebeat is already running."
STOPPED_SUCCESSFULLY = "Filebeat stopped successfully."
FAILED_STOP = "Failed to stop Filebeat."
ALREADY_STOPPED = "Filebeat is already stopped."


async def run_command(command_list, success_message):
    process = await asyncio.create_subprocess_shell(' '.join(command_list), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode == 0:
        print(success_message)
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

async def main(config=None):
    global global_config

    global_config = config
    # Parse command-line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-silent", action="store_true", help="Run in silent mode without asking for Discord ID")
    parser.add_argument("-test", action="store_true", help="Use an experimental filebeat configuration file")
    args = parser.parse_args()

    print_or_log('info','Setting up Filebeat. This is used to submit game match logs for trend analysis and is required by game server hosts.')
    if not check_filebeat_installed():
        await install_filebeat()
        
    step_certificate.main(stop_event, set_filebeat_auth_token, set_filebeat_auth_url)

    filebeat_changed = False
    if await configure_filebeat(silent=args.silent, test=args.test):
        filebeat_changed = True
        # Create scheduled task on Windows
        if not args.silent:
            if operating_system == "Windows":
                task_name = "Filebeat Task"
                script_path = os.path.abspath(__file__)
                command = f"python {script_path} -silent"

                # Check if the task already exists
                task_query = subprocess.run(["schtasks", "/query", "/tn", task_name], capture_output=True, text=True)
                if "ERROR: The system cannot find the file specified." in task_query.stderr:
                    # Create the scheduled task
                    subprocess.run(["schtasks", "/create", "/tn", task_name, "/tr", command, "/sc", "daily", "/st", "00:00"])
                    print_or_log('info',"Scheduled task created successfully.")
                else:
                    print_or_log('info',"Task already scheduled.")

            # Create cron job on Linux
            if operating_system == "Linux":
                script_path = os.path.abspath(__file__)
                command = f"python3 {script_path} -silent"
                add_cron_job(command)
                print_or_log('info',"Cron job created successfully.")

    # if filebeat_changed:
    await restart_filebeat(filebeat_changed, silent=args.silent)

if __name__ == "__main__":
    asyncio.run(main())