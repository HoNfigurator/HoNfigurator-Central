import argparse
import platform
import subprocess
import sys
import os
import shutil
import requests
import tempfile
import zipfile
from pathlib import Path
import psutil
import time
import re
import step_certificate
import hashlib
from tempfile import NamedTemporaryFile
import logging

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

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger()
operating_system = platform.system()

def install_filebeat_linux():
    # Update package lists for upgrades for packages that need upgrading
    subprocess.run(["sudo", "apt-get", "update"], check=True)

    # Download and install the Public Signing Key:
    subprocess.run("wget -qO - https://artifacts.elastic.co/GPG-KEY-elasticsearch | sudo apt-key add -", shell=True, check=True)

    # Save the repository definition to /etc/apt/sources.list.d/elastic-7.x.list:
    subprocess.run('echo "deb https://artifacts.elastic.co/packages/8.x/apt stable main" | sudo tee -a /etc/apt/sources.list.d/elastic-8.x.list', shell=True, check=True)

    # Update the system and install filebeat
    # subprocess.run(["sudo", "apt-get", "update"], check=True)
    subprocess.run(["sudo", "apt-get", "install", "filebeat"], check=True)


def install_filebeat_windows():
    filebeat_install_dir = os.path.join(os.environ["ProgramFiles"], "FileBeat")
    if os.path.exists(Path(filebeat_install_dir) / "filebeat.exe"):
        return
    # Download and install Filebeat using Python
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_file = os.path.join(temp_dir, "filebeat-8.8.2-windows-x86_64.zip")
        url = "https://artifacts.elastic.co/downloads/beats/filebeat/filebeat-8.8.2-windows-x86_64.zip"

        # Download the Filebeat ZIP file
        response = requests.get(url)
        if response.status_code == 200:
            with open(zip_file, "wb") as file:
                file.write(response.content)
            print("Filebeat ZIP file downloaded successfully.")
        else:
            print("Failed to download Filebeat ZIP file.")

        # Extract ZIP contents to temporary folder
        temp_extract_folder = os.path.join(temp_dir, "filebeat-extract")
        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            zip_ref.extractall(temp_extract_folder)
        print("Filebeat ZIP file extracted successfully.")

        # Move extracted files to destination folder
        extracted_folder = os.listdir(temp_extract_folder)[0]
        source_folder = os.path.join(temp_extract_folder, extracted_folder)

        # Create destination folder if it doesn't exist
        if not os.path.exists(filebeat_install_dir):
            os.makedirs(filebeat_install_dir)
            print("Created destination folder:", filebeat_install_dir)

        extracted_files = os.listdir(source_folder)
        for file in extracted_files:
            source_path = os.path.join(source_folder, file)
            destination_path = os.path.join(filebeat_install_dir, os.path.basename(file))
            shutil.move(source_path, destination_path)
        print("Filebeat installed successfully at:", filebeat_install_dir)
        command = [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(filebeat_install_dir) / "install-service-filebeat.ps1")
        ]

        result = subprocess.run(command, capture_output=True, text=True)

        # Remove the extracted folder
        os.rmdir(source_folder)
        print("Extracted folder removed.")

def uninstall_filebeat_linux():
    # Uninstall Filebeat on Linux
    subprocess.run(["sudo", "systemctl", "stop", "filebeat"])
    subprocess.run(["sudo", "apt-get", "remove", "filebeat"])

def uninstall_filebeat_windows():
    filebeat_install_dir = os.path.join(os.environ["ProgramFiles"], "FileBeat")
    if os.path.exists(Path(filebeat_install_dir) / "filebeat.exe"):
        command = [
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(Path(filebeat_install_dir) / "uninstall-service-filebeat.ps1")
        ]

        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode == 0:
            shutil.rmtree(filebeat_install_dir)
            print("Filebeat uninstalled successfully.")
        else:
            print("Failed to uninstall Filebeat.")
    else:
        print("Filebeat is not installed.")

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

def request_client_certificate(svr_name, svr_location, filebeat_path):

    try:
        # Check if the certificate files already exist
        crt_file_path = filebeat_path / 'client.crt'
        key_file_path = filebeat_path / 'client.key'
        certificate_exists = crt_file_path.is_file() and key_file_path.is_file()

        if certificate_exists:
            print("Renewing existing client certificate...")
            # Construct the command for certificate renewal
            command = [
                "step", "ca", "renew", crt_file_path, key_file_path,
                "--force"
            ]
        else:
            token = input(f"Enter the authentication token for {svr_name} - {svr_location}: ")
            print("Requesting new client certificate...")
            # Construct the command for new certificate request
            command = [
                "step", "ca", "certificate", f'{svr_name} - {svr_location}',
                crt_file_path, key_file_path, "--token", token, "--not-after", "200h", "--provisioner", "step"
            ]

        # Run the command
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode == 0:
            # Certificate request successful
            certificate_data = result.stdout.strip()
            # Do something with the certificate data
            print("Client certificate request successful.")
        else:
            # Certificate request failed
            error_message = result.stderr.strip()
            print(f"Error: {error_message}")
            sys.exit(1)
    except FileNotFoundError:
        print("Step CLI is not installed or not in the system's PATH.")
        sys.exit(1)

def configure_filebeat(silent=False):
    filebeat_config_url = "https://honfigurator.app/hon-server-monitoring/filebeat.yml"
    honfigurator_ca_chain_url = "https://honfigurator.app/honfigurator-chain.pem"
    if operating_system == "Windows":
        destination_folder = os.path.join(os.environ["ProgramFiles"], "filebeat")
    else:
        destination_folder = "/usr/share/filebeat"
    
    if not os.path.exists(destination_folder): os.makedirs(destination_folder)
    
    honfigurator_ca_chain_response = requests.get(honfigurator_ca_chain_url)
    if honfigurator_ca_chain_response.status_code == 200:
        with open(Path(destination_folder) / "honfigurator-chain.pem", 'wb') as chain_file:
            chain_file.write(honfigurator_ca_chain_response.content)

    filebeat_config_response = requests.get(filebeat_config_url)
    if filebeat_config_response.status_code == 200:
        config_file_path = os.path.join(destination_folder, "filebeat.yml")
        filebeat_config = filebeat_config_response.content

        
        exclude = []
        while True:
            print("Scanning for running hon executable..")
            time.sleep(1)
            if operating_system == "Windows":
                process = check_process("hon_x64.exe",exclude)
            else: process = check_process("hon-x86_64-server",exclude)
            if process and len(process.cmdline()) > 4:
                break
            elif process and len(process.cmdline()) < 4:
                if process not in exclude:
                    exclude.append(process)
                    print(f"Excluded {process.pid}\n\t{process.cmdline()}")

        # Perform text replacements
        svr_name = extract_settings_from_commandline(process.cmdline(), "svr_name")
        space_count = 0
        index = len(svr_name) - 1

        # Find the index of the second space from the end of the string
        while index >= 0 and space_count < 2:
            if svr_name[index] == ' ':
                space_count += 1
            index -= 1

        # Remove the portion of the string from the index found until the end
        svr_name = svr_name[:index+1]
        svr_location = extract_settings_from_commandline(process.cmdline(), "svr_location")
        if operating_system == "Windows":
            slave_log = Path(get_process_environment(process,"USERPROFILE")) / "Documents" / "Heroes of Newerth x64" / "KONGOR" / "logs" / "*.clog"
            match_log = Path(get_process_environment(process,"USERPROFILE")) / "Documents" / "Heroes of Newerth x64" / "KONGOR" / "logs" / "M*.log"
        else:
            slave_log = Path(process.cwd()).parent / "config" / "KONGOR" / "logs" / "*.clog"
            match_log = Path(process.cwd()).parent / "config" / "KONGOR" / "logs" / "M*.log"
        svr_desc = extract_settings_from_commandline(process.cmdline(),"svr_description")
        if svr_desc: launcher = "HoNfigurator"
        else: launcher = "COMPEL"
        print(f"Details\n\tsvr name: {svr_name}\n\tsvr location: {svr_location}")

        
        request_client_certificate(svr_name, svr_location, Path(destination_folder))
        
        if os.path.exists(config_file_path):
            old_config_hash = calculate_file_hash(config_file_path)
            existing_discord_id = read_admin_value_from_filebeat_config(config_file_path)
            if existing_discord_id:
                print("Existing Discord ID:", existing_discord_id)
        
        # svr_name = svr_name[:-2]
        filebeat_config = filebeat_config.replace(b"$server_name", str.encode(svr_name))
        filebeat_config = filebeat_config.replace(b"$id", str.encode(svr_name))
        filebeat_config = filebeat_config.replace(b"$region", str.encode(svr_location))
        filebeat_config = filebeat_config.replace(b"$slave_log",str.encode(str(slave_log)))
        filebeat_config = filebeat_config.replace(b"$match_log",str.encode(str(match_log)))
        filebeat_config = filebeat_config.replace(b"$server_launcher",str.encode(launcher))
        if not silent:
            if existing_discord_id:
                discord_id = input(f"What is your discord user name? ({existing_discord_id}): ")
                if discord_id == "": discord_id = existing_discord_id
            else: discord_id = input(f"What is your discord user name?: ")
        filebeat_config = filebeat_config.replace(b"$discord_id", str.encode(discord_id))
        if operating_system == "Windows":
            encoding = "utf-16-le"
        else: encoding = "BINARY"
        filebeat_config = filebeat_config.replace(b"$encoding", str.encode(encoding))
        filebeat_config = filebeat_config.replace(b"$ca_chain", str.encode(str(Path(destination_folder) / "honfigurator-chain.pem")))
        filebeat_config = filebeat_config.replace(b"$client_cert", str.encode(str(Path(destination_folder) / "client.crt")))
        filebeat_config = filebeat_config.replace(b"$client_key", str.encode(str(Path(destination_folder) / "client.key")))

        new_config_hash = None
        old_config_hash = None
        
        if os.path.exists(config_file_path):
            old_config_hash = calculate_file_hash(config_file_path)
        temp_dir = tempfile.TemporaryDirectory()
        temp_file_path = Path(temp_dir.name) / 'filebeat.yml'
        with open(temp_file_path, 'wb') as temp_file:
            temp_file.write(filebeat_config)
        new_config_hash = calculate_file_hash(temp_file_path)

        if old_config_hash != new_config_hash:
            shutil.move(temp_file_path, config_file_path)
            print("Filebeat configuration file downloaded and placed at:", config_file_path)
            return True
        else:
            print("No configuration changes required")
            return False
        
    else:
        print("Failed to download Filebeat configuration file.")
    

# Constants for repeated strings
STARTED_SUCCESSFULLY = "Filebeat started successfully."
FAILED_START = "Failed to start Filebeat."
ALREADY_RUNNING = "Filebeat is already running."
STOPPED_SUCCESSFULLY = "Filebeat stopped successfully."
FAILED_STOP = "Failed to stop Filebeat."
ALREADY_STOPPED = "Filebeat is already stopped."

def restart_filebeat(filebeat_changed, silent):
    def run_command(command_list, success_message):
        result = subprocess.run(command_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            print(success_message)
        else:
            print("Command:", " ".join(command_list))
            print("Return code:", result.returncode)
            print("Error:", result.stderr.decode())
    def restart():
        if operating_system == "Windows":
            process_name = "filebeat.exe"
            command_list = ["powershell.exe", "Restart-Service", "-Name", "filebeat"]
            success_message = "Filebeat service restarted successfully on Windows."
            run_command(command_list, success_message)

        else:  # Linux
            process_name = "filebeat"
            stop_command_list = ["sudo", "systemctl", "stop", "filebeat"]
            start_command_list = ["sudo", "systemctl", "start", "filebeat"]
            if check_process(process_name):
                run_command(stop_command_list, STOPPED_SUCCESSFULLY)
            run_command(start_command_list, STARTED_SUCCESSFULLY)
        
    if filebeat_changed and (check_process("filebeat.exe") or check_process("filebeat")):
        restart()
    elif not silent and (not check_process("filebeat.exe") or not check_process("filebeat")):
        while True:
            start = input("Would you like to start filebeat? (y/n): ")
            if start.lower() in ['y','n']:
                break
        if start.lower() == 'y':
            restart()

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
if operating_system == "Windows":
    install_filebeat_windows()
elif operating_system == "Linux":
    install_filebeat_linux()
else:
    print("Unsupported operating system.")
    sys.exit(1)
step_certificate.main()

# Parse command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument("-silent", action="store_true", help="Run in silent mode without asking for Discord ID")
args = parser.parse_args()

filebeat_changed = False
if configure_filebeat(silent=args.silent):
    filebeat_changed = True
    # Create scheduled task on Windows
    if not args.silent:
        if operating_system == "Windows":
            task_name = "Filebeat Task"
            script_path = os.path.abspath(__file__)
            command = f"python {script_path} -silent"

            # Create the scheduled task
            subprocess.run(["schtasks", "/create", "/tn", task_name, "/tr", command, "/sc", "daily", "/st", "00:00"])

            print("Scheduled task created successfully.")

        # Create cron job on Linux
        if operating_system == "Linux":
            script_path = os.path.abspath(__file__)
            command = f"python3 {script_path} -silent"
            add_cron_job(command)
            print("Cron job created successfully.")
# if filebeat_changed:
restart_filebeat(filebeat_changed, silent=args.silent)