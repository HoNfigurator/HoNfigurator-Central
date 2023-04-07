import subprocess, psutil
import platform
import os
from os.path import exists
from pathlib import Path
import sys
import urllib
from cogs.misc.logging import get_logger
from cogs.misc.exceptions import UnexpectedVersionError

LOGGER = get_logger()

class Misc:
    def __init__(self):
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_name = platform.processor()
        self.total_ram = psutil.virtual_memory().total
        self.os_platform = sys.platform
        self.total_allowed_servers = None
    def parse_linux_procs(proc_name, slave_id):
        for proc in psutil.process_iter():
            if proc_name == proc.name():
                cmd_line = proc.cmdline()
                if len(cmd_line) < 5:
                    continue
                for item in cmd_line[4].split(";"):
                    if "svr_slave" in item:
                        if int(item.split(" ")[-1]) == slave_id:
                            return [proc]
        return []
    def get_proc(proc_name, slave_id = ''):
        if sys.platform == "linux":
            return Misc.parse_linux_procs(proc_name, slave_id)
        procs = []
        for proc in psutil.process_iter():
            if proc.name() == proc_name:
                procs.append(proc)
        return procs
    def check_port(port):
        command = subprocess.Popen(['netstat','-oanp','udp'],stdout=subprocess.PIPE)
        result = command.stdout.read()
        result = result.decode()
        if f"0.0.0.0:{port}" in result:
            return True
        else:
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
    def get_total_ram(self):
        return self.total_ram
    def get_cpu_load():
        return psutil.getloadavg()
    def get_os_platform(self):
        return self.os_platform
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

        if svr_total_per_core > 2:
            raise Exception("You cannot specify more than 2 servers per core.")
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
        try:
            external_ip = urllib.request.urlopen('https://4.ident.me').read().decode('utf8')
        except Exception:
            external_ip = urllib.request.urlopen('http://api.ipify.org').read().decode('utf8')
        return external_ip
    def get_svr_description(self):
        return f"cpu: {self.get_cpu_name()}"
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
                raise UnexpectedVersionError("Unexpected game version. Have you merged the wasserver binaries into the HoN install folder?")
            else:
                return version
        elif self.get_os_platform() == "linux":
            with open(Path(hon_exe).parent / "version.txt", 'r') as f:
                return f.readline()
