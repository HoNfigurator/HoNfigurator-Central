import os
from os.path import exists
import platform
import subprocess
import sys
from pathlib import Path
import shutil
import urllib.request
import tarfile
import zipfile
import ssl
import tempfile

version = "0.24.3"
system = platform.system()

ssl._create_default_https_context = ssl._create_unverified_context

def run_command(cmd, shell=False):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=shell, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

def install_step_cli():
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)
        
        if system == "Windows":
            download_location = tempdir_path / "step_windows.zip"
            install_location = Path(os.environ['PROGRAMDATA'])
            step_location = install_location / "step"

            print(f"Downloading and installing step CLI for Windows... {step_location}")
            url = f"https://github.com/smallstep/cli/releases/download/v{version}/step_windows_{version}_amd64.zip"
            urllib.request.urlretrieve(url, download_location)
            with zipfile.ZipFile(download_location, 'r') as zip_ref:
                zip_ref.extractall(tempdir_path)
            extracted_folder = tempdir_path / f"step_{version}"
            if exists(step_location): shutil.rmtree(step_location)
            shutil.move(extracted_folder, step_location)
            os.environ["PATH"] = os.path.abspath(step_location / "bin") + os.pathsep + os.environ["PATH"]
        elif system == "Linux":
            print("Downloading and installing step CLI for Linux...")
            url = f"https://github.com/smallstep/cli/releases/download/v{version}/step_linux_{version}_amd64.tar.gz"
            download_location = tempdir_path / "step.tar.gz"
            urllib.request.urlretrieve(url, download_location)
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
            print(f"Unsupported system: {system}")
            sys.exit(1)

def uninstall_step_cli():
    if system == "Windows":
        install_location = Path(os.environ['PROGRAMDATA']) / "step"
        if exists(install_location):
            shutil.rmtree(install_location)
        print("Step CLI for Windows has been uninstalled.")
    elif system == "Linux":
        step_install_location = "/usr/share/step"
        step_bin_location = "/usr/local/bin/step"
        if exists(step_install_location):
            shutil.rmtree(step_install_location)
        if exists(step_bin_location):
            os.remove(step_bin_location)
        print("Step CLI for Linux has been uninstalled.")
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)

# Invoke-WebRequest "https://hon-elk.honfigurator.app/roots.pem" -outfile "$steppath\certs\root_ca.crt"
# $fingerprint = & "$steppath\bin\step.exe" certificate fingerprint "$steppath\certs\root_ca.crt"
def bootstrap_ca():
    print("Bootstrapping the CA...")
    ca_url = "https://hon-elk.honfigurator.app"
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir_path = Path(tempdir)

        root_ca_download_location = tempdir_path / "root_ca.crt"

        urllib.request.urlretrieve(f"{ca_url}/roots.pem", root_ca_download_location)
        ca_fingerprint = run_command(["step","certificate","fingerprint",root_ca_download_location])
        p = subprocess.Popen(["step", "ca", "bootstrap", "--ca-url", ca_url, "--fingerprint", ca_fingerprint, '--force'], stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
        p.communicate()

def request_certificate(provisioner_name, provisioner_password_file):
    print("Requesting a certificate...")
    run_command([
        "step", "ca", "certificate",
        "--provisioner", provisioner_name,
        "--provisioner-password-file", provisioner_password_file,
        "example.com", "example.com.crt", "example.com.key"
    ])

def main():
    install_step_cli()
    bootstrap_ca()

    provisioner_name = "HoNfigurator"
    provisioner_password_file = "provisioner_password.txt"
    provisioner_password = ""

    # request_certificate(provisioner_name, provisioner_password_file)

if __name__ == "__main__":
    main()
