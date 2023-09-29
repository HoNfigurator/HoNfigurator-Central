import subprocess
import asyncio
import sys
import os
import zipfile
import shutil
from pathlib import Path
import tempfile
import aiohttp
import aiofiles


# Specify where you want to install EMQX on Windows:
windows_emqx_install_dir = "C:\\EMQX"  # Modify this path as needed
emqx_bin_path = str(Path(windows_emqx_install_dir) / "bin")
emqx_cmd = str(Path(windows_emqx_install_dir) / "bin" / "emqx.cmd")
emqx_ctl = str(Path(windows_emqx_install_dir) / "bin" / "emqx_ctl.cmd")

if __name__ == "__main__":
    LOGGER = None
    stop_event = asyncio.Event()
else:
    # if imported into honfigurator main
    from cogs.misc.logger import get_logger, get_misc
    LOGGER = get_logger()
    MISC = get_misc()

def print_or_log(log_lvl='info', msg=''):
    log_lvl = log_lvl.lower()
    if LOGGER:
        getattr(LOGGER, log_lvl)(msg)
    else:
        print(msg)

def is_emqx_installed():
    """Check if EMQX is installed."""
    platform = sys.platform

    if platform == "linux" or platform == "linux2":
        try:
            result = subprocess.run(["emqx", "ctl", "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return "emqx" in result.stdout.decode().lower()
        except FileNotFoundError:
            return False
    elif platform == "win32":
        return os.path.exists(windows_emqx_install_dir)
    else:
        return False

def is_emqx_running():
    """Check if EMQX is running."""
    try:
        platform = sys.platform
        if platform == "linux" or platform == "linux2":  # linux2 is for older Python versions
            result = subprocess.run(["sudo", "systemctl", "is-active", "emqx"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return "active" in result.stdout.decode().lower()
        
        elif platform == "win32":
            result = subprocess.run([emqx_ctl, "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if "started" in result.stdout.decode().lower() or "starting" in result.stdout.decode().lower():
                return True
            else:
                return False
            
        else:
            print(f"Unsupported platform: {platform}")
            return False
    except Exception as e:
        print_or_log('error', f"Error checking EMQX status: {e}")
        return False

def start_emqx():
    """Start EMQX."""
    platform = sys.platform
    if platform == "linux" or platform == "linux2":
        subprocess.run(["sudo", "systemctl", "start", "emqx"])
    elif platform == "win32":
        subprocess.run([emqx_cmd, "start"])


    else:
        print(f"Unsupported platform: {platform}")

def install_emqx_on_linux():
    """Install EMQX on Linux."""
    subprocess.run(["sudo", "apt", "update"])
    subprocess.run(["sudo", "apt", "install", "-y", "curl", "wget"])
    subprocess.run(["wget", "https://www.emqx.com/downloads/broker/v4.3.5/emqx-ubuntu20.04-4.3.5-amd64.deb"])  # Replace with the desired version and OS variant
    subprocess.run(["sudo", "dpkg", "-i", "emqx-ubuntu20.04-4.3.5-amd64.deb"])
    subprocess.run(["rm", "emqx-ubuntu20.04-4.3.5-amd64.deb"])
    start_emqx()

async def install_emqx_on_windows():
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_file = os.path.join(temp_dir, "emqx-windows.zip")
        url = "https://www.emqx.com/en/downloads/broker/5.2.1/emqx-5.2.1-windows-amd64.zip"  # Replace with the desired version

        # Download the EMQX ZIP file
        async with aiohttp.ClientSession() as session:
            async with session.get(url, ssl=False) as response:
                if response.status == 200:
                    content = await response.read()
                    async with aiofiles.open(zip_file, "wb") as file:
                        await file.write(content)
                    print_or_log('info', "EMQX ZIP file downloaded successfully.")
                else:
                    print_or_log('error', "Failed to download EMQX ZIP file.")

        temp_extract_folder = os.path.join(temp_dir, "emqx-extract")
        with zipfile.ZipFile(zip_file, "r") as zip_ref:
            zip_ref.extractall(temp_extract_folder)
        print_or_log('info', "EMQX ZIP file extracted successfully.")

        # Assuming the zip contains a single top-level directory
        extracted_folder = os.listdir(temp_extract_folder)[0]
        source_folder = os.path.join(temp_extract_folder, extracted_folder)

        # If the destination folder does not exist, extract the zip there
        if not os.path.exists(windows_emqx_install_dir):
            with zipfile.ZipFile(zip_file, "r") as zip_ref:
                zip_ref.extractall(windows_emqx_install_dir)
            print_or_log('info', f"EMQX installed successfully at: {windows_emqx_install_dir}")
        else:
            print_or_log('error', f"Destination folder {windows_emqx_install_dir} already exists.")

        # Note: EMQX might not have a similar PowerShell script for service installation as Filebeat, so you'd need to handle that separately or refer to EMQX's official documentation for any service-related setup on Windows.

        # Remove the extracted folder and ZIP file
        shutil.rmtree(temp_extract_folder)
        print_or_log('info', "Extracted folder and ZIP file removed.")

        os.chdir(windows_emqx_install_dir / "bin")
        start_emqx()


async def main():
    # Check if EMQX is already installed
    if is_emqx_installed():
        print("EMQX is already installed!")
        if not is_emqx_running():
            print("EMQX is not running, starting now...")
            start_emqx()
        return

    platform = sys.platform

    if platform == "linux" or platform == "linux2":  # linux2 is for older Python versions
        install_emqx_on_linux()
    elif platform == "win32":
        await install_emqx_on_windows()
    else:
        print(f"Unsupported platform: {platform}")

if __name__ == "__main__":
    asyncio.run(main())
