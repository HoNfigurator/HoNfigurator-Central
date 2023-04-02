import subprocess, psutil
from cogs.misc.logging import get_logger
import platform

LOGGER = get_logger()

class Misc:
    def __init__(self):
        self.cpu_count = psutil.cpu_count(logical=True)
        self.cpu_name = platform.processor()
        self.total_ram = psutil.virtual_memory().total
        self.os_platform = platform.system()
        self.total_allowed_servers = None
    def get_proc(proc_name):
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
        return self.cpu_name
    def get_total_ram(self):
        return self.total_ram
    def get_cpu_load():
        return psutil.getloadavg()
    def get_platform(self):
        return self.os_platform
    def get_total_allowed_servers(self,svr_total_per_core):
        total = svr_total_per_core * self.cpu_count
        if self.cpu_count <=4:
            total - 1
        elif self.cpu_count >4 and self.cpu_count <= 12:
            total - 2
        elif self.cpu_count >12:
            total - 4
        return total