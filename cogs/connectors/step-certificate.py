import os
import platform
import subprocess
import sys

version = "0.23.2"
system = platform.system()

def run_command(cmd, shell=False):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=shell, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip()

def install_step_cli():
    if system == "Windows":
        print("Downloading and installing step CLI for Windows...")
        url = f"https://github.com/smallstep/cli/releases/download/v{version}/step_windows_{version}.zip"
        run_command(["powershell.exe", "Invoke-WebRequest", f"\"{url}\"", "-outFile", "step_windows.zip"])
        run_command(["powershell.exe", "Expand-Archive", "step_windows.zip", "-DestinationPath", "."])
        os.environ["PATH"] = os.path.abspath("step_windows") + os.pathsep + os.environ["PATH"]
    elif system == "Linux":
        print("Downloading and installing step CLI for Linux...")
        url = "https://github.com/smallstep/cli/releases/download/v0.17.0/step_linux_0.17.0_amd64.tar.gz"
        run_command(["curl", "-LO", url])
        run_command(["tar", "-xf", "step_linux_0.17.0_amd64.tar.gz"])
        os.environ["PATH"] = os.path.abspath("step_linux_0.17.0") + os.pathsep + os.environ["PATH"]
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)


# Invoke-WebRequest "https://hon-elk.honfigurator.app/roots.pem" -outfile "$steppath\certs\root_ca.crt"
# $fingerprint = & "$steppath\bin\step.exe" certificate fingerprint "$steppath\certs\root_ca.crt"
def bootstrap_ca():
    print("Bootstrapping the CA...")
    ca_url = "https://hon-elk.honfigurator.app"
    root_ca_location = "root_ca.crt"
    
    if system == "Windows":
        run_command(["powershell.exe", "Invoke-WebRequest", f"\"{ca_url}/roots.pem\"", "-OutFile", root_ca_location])
    elif system == "Linux":
        run_command(["curl", "-LO", f"{ca_url}/roots.pem", root_ca_location])
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)

    ca_fingerprint = run_command(["step","certificate","fingerprint",root_ca_location])
    run_command(["step", "ca", "bootstrap", "--ca-url", ca_url, "--fingerprint", ca_fingerprint])

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
