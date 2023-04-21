import urllib.request
import traceback
import platform
import pathlib
import json
from pathlib import Path
from cogs.misc.logging import get_logger,get_home,get_misc

LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()

class ConfigManagement():
    def __init__(self,id,gbl):
        self.id = id
        self.gbl = gbl
        self.local = self.get_local_configuration()
    def get_total_servers(self):
        return self.gbl['hon_data']['svr_total']
    def get_global_by_key(self,k):
        for d in self.gbl.values():
            try: return d[k]
            except: pass
        return None
    def get_local_by_key(self,k):
        for d in self.local.values():
            try: return d[k]
            except: pass
        return None
    def get_local_configuration(self):
        if MISC.get_os_platform() == "win32":
            executable = f"hon_x64"
            suffix = ".exe"
            file_name = f'{executable}{suffix}'
        else:
            executable = "hon-x86_64-server"
            file_name = executable

        self.local = ({
            'config' : {
                'file_name':file_name,
                'file_path' : str(Path(self.get_global_by_key("hon_install_directory")) / f'{file_name}')
            },
            'params' : {
                'svr_login':f"{self.get_global_by_key('svr_login')}:{self.id}",
                'svr_password':self.get_global_by_key('svr_password'),
                'svr_description':MISC.get_svr_description(),
                'sv_masterName':f"{self.get_global_by_key('svr_login')}:",
                'svr_slave':self.id,
                'svr_adminPassword':"",
                'svr_name':f"{self.get_global_by_key('svr_name')} {self.id} 0",
                'svr_ip':self.get_global_by_key('svr_ip') if 'svr_ip' in self.gbl['hon_data'] else MISC.get_public_ip(),
                'svr_port':self.get_global_by_key('svr_starting_gamePort')+self.id,
                'svr_proxyPort':self.get_global_by_key('svr_starting_gamePort')+self.id+10000,
                'svr_proxyLocalVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id,
                'svr_proxyRemoteVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id+10000,
                'svr_voicePortStart':self.get_global_by_key('svr_starting_voicePort')+self.id,
                'man_enableProxy':self.get_global_by_key('svr_enableProxy'),
                'svr_location':self.get_global_by_key('svr_location'),
                'svr_broadcast':True,
                'upd_checkForUpdates':False,
                'sv_autosaveReplay':True,
                'sys_autoSaveDump':False,
                'sys_dumpOnFatal':False,
                'svr_chatPort':11032,
                'svr_maxIncomingPacketsPerSecond':300,
                'svr_maxIncomingBytesPerSecond':1048576,
                'con_showNet':False,
                'http_printDebugInfo':False,
                'php_printDebugInfo':False,
                'svr_debugChatServer':False,
                'svr_submitStats':True,
                'svr_chatAddress':'96.127.149.202',
                'http_useCompression':False,
                'man_resubmitStats':True,
                'man_uploadReplays':True,
                'sv_remoteAdmins':'',
                'sv_logcollection_highping_value':100,
                'sv_logcollection_highping_reportclientnum':1,
                'sv_logcollection_highping_interval':120000,
                #'host_affinity':self.id - 1
                'host_affinity':','.join(MISC.get_server_affinity(self.id, self.gbl['hon_data']['svr_total_per_core']))
            },
            'name' : f'{self.get_global_by_key("svr_name")}-{self.id}'
        })
        return self.local
