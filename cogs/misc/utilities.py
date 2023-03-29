import subprocess, psutil
from cogs.misc.logging import get_logger

LOGGER = get_logger()

class Misc:
    def __init__():
        return
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
