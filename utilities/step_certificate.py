import os
from os.path import exists
import platform
import subprocess
import sys
from pathlib import Path
import shutil
import tarfile
import zipfile
import ssl
import tempfile
import webbrowser
import json
from datetime import datetime
import aiohttp
from aiohttp import TCPConnector
import asyncio

version = "0.24.3"
system = platform.system()

if system == "Windows":
    step_location = Path(os.environ['PROGRAMDATA']) / "step" / "bin" / "step.exe"
elif system == "Linux": step_location = "step"

ssl._create_default_https_context = ssl._create_unverified_context

def print_or_log(log_lvl='info', msg=''):
    log_lvl = log_lvl.lower()
    if LOGGER:
        getattr(LOGGER, log_lvl)(msg)
    else:
        print(msg)

async def async_get(url, headers=None, ssl=False):
    connector = TCPConnector(ssl=ssl)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(url, headers=headers) as resp:
            resp_text = await resp.text()
            return resp.status,resp_text

async def async_post(url, data=None, headers=None, ssl=False):
    connector = TCPConnector(ssl=ssl)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.post(url, data=data, headers=headers) as resp:
            resp_text = await resp.text()
            return resp.status,resp_text

async def download_file(url, destination, ssl=False):
    connector = TCPConnector(ssl=ssl)
    async with aiohttp.ClientSession(connector=connector) as session:
        async with session.get(url) as resp:
            with open(destination, 'wb') as fd:
                while not stop_event.is_set():
                    chunk = await resp.content.read(1024)  # 1Kb
                    if not chunk:
                        break
                    fd.write(chunk)

def run_command(cmd, shell=False):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=shell, text=True)
    if result.returncode != 0:
        print_or_log('error',f"Error: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

async def install_step_cli():
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)
        
        if system == "Windows":
            download_location = tempdir_path / "step_windows.zip"
            install_location = Path(os.environ['PROGRAMDATA'])
            step_location = install_location / "step"

            print_or_log('info',f"Downloading and installing step CLI for Windows... {step_location}")
            url = f"https://github.com/smallstep/cli/releases/download/v{version}/step_windows_{version}_amd64.zip"
            await download_file(url, download_location)
            with zipfile.ZipFile(download_location, 'r') as zip_ref:
                zip_ref.extractall(tempdir_path)
            extracted_folder = tempdir_path / f"step_{version}"
            if exists(step_location): shutil.rmtree(step_location)
            shutil.move(extracted_folder, step_location)
            os.environ["PATH"] = os.path.abspath(step_location / "bin") + os.pathsep + os.environ["PATH"]
        elif system == "Linux":
            print_or_log('info',"Downloading and installing step CLI for Linux...")
            url = f"https://github.com/smallstep/cli/releases/download/v{version}/step_linux_{version}_amd64.tar.gz"
            download_location = tempdir_path / "step.tar.gz"
            await download_file(url, download_location)
            with tarfile.open(download_location, 'r:gz') as tar_ref:
                tar_ref.extractall(tempdir_path)
            extracted_folder = tempdir_path / f"step_{version}"
            step_install_location = "/usr/share/step"
            step_bin_location = "/usr/local/bin/step"
            if os.path.isdir(step_install_location): shutil.rmtree(step_install_location)
            shutil.move(extracted_folder, step_install_location)

            if os.path.lexists(step_bin_location):
                os.remove(step_bin_location)
            os.symlink(os.path.join(step_install_location, "bin", "step"), step_bin_location)
            os.environ["PATH"] = os.path.abspath(f"{step_install_location}/bin") + os.pathsep + os.environ["PATH"]
        else:
            print_or_log('error',f"Unsupported system: {system}")
            sys.exit(1)

def uninstall_step_cli():
    if system == "Windows":
        install_location = Path(os.environ['PROGRAMDATA']) / "step"
        if exists(install_location):
            shutil.rmtree(install_location)
        print_or_log('info',"Step CLI for Windows has been uninstalled.")
    elif system == "Linux":
        step_install_location = "/usr/share/step"
        step_bin_location = "/usr/local/bin/step"
        if exists(step_install_location):
            shutil.rmtree(step_install_location)
        if exists(step_bin_location):
            os.remove(step_bin_location)
        print_or_log('info',"Step CLI for Linux has been uninstalled.")
    else:
        print_or_log('error',f"Unsupported system: {system}")
        sys.exit(1)

async def bootstrap_ca(ca_url):
    print_or_log('info',"Bootstrapping the CA...")
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)

        root_ca_download_location = tempdir_path / "root_ca.crt"

        await download_file(f"{ca_url}/roots.pem", root_ca_download_location)
        ca_fingerprint = run_command([step_location,"certificate","fingerprint",root_ca_download_location])
        p = subprocess.Popen([step_location, "ca", "bootstrap", "--ca-url", ca_url, "--fingerprint", ca_fingerprint, '--force'], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        p.communicate()

async def register_client(server_url, ssl=False):
    response_status, response_text = await async_post(f'{server_url}/register', ssl=ssl)
    response = json.loads(response_text)  # Parse the JSON response
    if 'token' in response:
        return response['token']  # Extract the token from the response
    else:
        raise Exception("No token found in response")

def navigate_to_url(oauth_url):
    print_or_log('info',"You must authenticate with your discord account which is a member of the HOSTS role in the Project Kongor discord channel.")
    if system == "Windows":
        # Try to open the URL in a web browser
        webbrowser.open_new(oauth_url)
    else:
        # If it fails (because there's no web browser), print the URL instead
        print_or_log('interest',f"Please navigate to the following URL in a web browser to authorize match log submissions:\n\t{oauth_url}")

async def check_server_status(server_url, token, ssl=False):
    headers = {'x-auth-token': token}
    response_status, response_text = await async_get(f'{server_url}/status', headers=headers, ssl=ssl)
    response = json.loads(response_text)  # Parse the JSON response
    return response_status, response  # Return the parsed response

async def send_csr_to_server(server_url, csr, cert_name, token, ssl=False):
    headers = {'x-auth-token': token}
    data = {'csr': csr, 'name':cert_name}
    response_status, response_text = await async_post(f'{server_url}/csr', data=data, headers=headers, ssl=ssl)
    return response_status, response_text  # Return the response text

async def discord_oauth_flow_stepca(cert_name, csr_path, cert_path, key_path, token=None):
    # Config
    discord_client_id = '1096750568388702228'
    server_url = 'https://hon-elk.honfigurator.app:8443'

    # Register the client and get a token
    if not token:
        token = await register_client(server_url)
        if set_auth_token_callback: set_auth_token_callback(token)

    # Step 1: Redirect to Discord OAuth2 endpoint
    status_code, response_content = await check_server_status(server_url, token)
    if response_content['status'] != 200:
        oauth_url = f'https://discord.com/api/oauth2/authorize?client_id={discord_client_id}&redirect_uri={server_url}/callback&response_type=code&scope=identify&state={token}'
        if set_auth_url_callback: set_auth_url_callback(oauth_url)
        navigate_to_url(oauth_url)
    else: set_auth_url_callback(None)
    # Step 2: Poll server for status update
    while not stop_event.is_set():
        status_code, response_content = await check_server_status(server_url, token)

        if status_code == 200:
            # Server has validated the user and instructed the client to generate a CSR
            if response_content['status'] == 200:
                set_auth_url_callback(None)
                # Step 3: Generate CSR using Step CLI
                csr_command = f'{step_location} certificate create --force --no-password --insecure --csr "{cert_name}" "{str(csr_path)}" "{str(key_path)}"'
                subprocess.run(csr_command, shell=True)

                # Step 4: Send CSR to server
                with open(str(csr_path), "r") as file:
                    csr = file.read()
                status_code, cert_text = await send_csr_to_server(server_url, csr, cert_name, token)

                if status_code == 200:
                    # Step 5: Receive and save certificate from server
                    with open(cert_path, 'w') as cert_file:
                        cert_file.write(cert_text)

                    print_or_log('info','Certificate received and saved.')
                    return response_content["username"]
                else:
                    print_or_log('error','Failed to send CSR to server.')
            else:
                # print_or_log('info',f'Please follow the authentication steps at: {oauth_url}')
                for _ in range (1, 5): # Wait for 5 seconds before checking again
                    if stop_event.is_set():
                        break
                    await asyncio.sleep(1)
        else:
            print_or_log('error','Error from server.')
            return False

def is_certificate_expiring(cert_path):
    print_or_log('debug',"Checking if certificate is expired...")
    # Fetch certificate information
    cert_info = run_command([step_location, "certificate", "inspect", cert_path, "--format", "json"])
    # Convert cert_info string into a dictionary
    cert_info = json.loads(cert_info)
    # Fetch the expiration date from the certificate info
    not_after = cert_info.get('validity', {}).get('end')
    # Convert the expiration date string into a datetime object
    not_after = datetime.strptime(not_after, '%Y-%m-%dT%H:%M:%S%z')
    # Return True if the certificate is expired, False otherwise
    return datetime.now(tz=not_after.tzinfo) > not_after

def renew_certificate(crt_file_path, key_file_path):
    command = [
        step_location, "ca", "renew", crt_file_path, key_file_path,
        "--force"
    ]

    # Run the command
    result = subprocess.run(command, capture_output=True, text=True)

    return result

def request_certificate(provisioner_name, provisioner_password_file, cert_path):
    print_or_log('info',"Requesting a certificate...")
    if os.path.isfile(cert_path) and not is_certificate_expiring(cert_path):
        print_or_log('info',"Certificate already exists and it's valid.")
        return True
    else:
        run_command([
            step_location, "ca", "certificate",
            "--provisioner", provisioner_name,
            "--provisioner-password-file", provisioner_password_file,
            "example.com", cert_path, "example.com.key"
        ])
        print_or_log('info',"New certificate has been requested.")

def is_step_installed():
    try:
        result = subprocess.run([step_location, "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def is_ca_bootstrapped(ca_url):
    try:
        config_dir = run_command([step_location, "path"])
        ca_config_file = Path(config_dir) / "config" / "defaults.json"
        if not ca_config_file.is_file():
            return False

        with open(ca_config_file, 'r') as f:
            ca_config = json.load(f)

        return ca_config.get('ca-url') == ca_url
    except FileNotFoundError:
        return False


async def main(stop_event_from_honfig=None,logger=None, set_auth_token=None, set_auth_url=None):
    global set_auth_token_callback, set_auth_url_callback, stop_event, LOGGER
    if logger:
        LOGGER = logger
    if set_auth_token:
        set_auth_token_callback = set_auth_token
    if set_auth_url:
        set_auth_url_callback = set_auth_url
    if stop_event_from_honfig:
        stop_event = stop_event_from_honfig
    else: stop_event = asyncio.Event()

    if not is_step_installed():
        await install_step_cli()
    else:
        print_or_log('debug',"Step CLI is already installed.")

    ca_url = "https://hon-elk.honfigurator.app"
    if not is_ca_bootstrapped(ca_url):
        await bootstrap_ca(ca_url)
    else:
        print_or_log('debug',"The CA is already bootstrapped.")

if __name__ == "__main__":
    asyncio.run(main())
