import urllib.request
import traceback
import platform
import pathlib
import json
from pathlib import Path
from cogs.misc.logger import get_logger,get_home,get_misc

LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()

def get_cowmaster_configuration(global_config):
    executable = "hon-x86_64-server"
    file_name = executable

    local = ({
        'config' : {
        'file_name':file_name,
        'file_path' : str(Path(global_config.get("hon_install_directory")) / f'{file_name}')
    },
    'params' : {
        'svr_login':f"{global_config.get('svr_login')}:0",
        'svr_password':global_config.get('svr_password'),
        'svr_description':MISC.get_svr_description(),
        'sv_masterName':f"{global_config.get('svr_login')}:",
        'svr_slave':1,
        'svr_adminPassword':"",
        'svr_name':f"{global_config.get('svr_name')} 0",
        'svr_ip':global_config.get('svr_ip') if 'svr_ip' in global_config else MISC.get_public_ip(),
        'svr_port':global_config.get('svr_starting_gamePort') - 2,
#'svr_proxyPort':self.get_global_by_key('svr_starting_gamePort')+self.id+10000 - 1,
#'svr_proxyLocalVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id - 1,
#'svr_proxyRemoteVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id+10000 - 1,
        'svr_voicePortStart':global_config.get('svr_starting_voicePort'),
        'man_enableProxy':global_config.get('man_enableProxy'),
        'svr_location':global_config.get('svr_location'),
        'svr_enableBotMatch': global_config.get('svr_enableBotMatch'),
#'svr_override_affinity': self.get_global_by_key('svr_override_affinity'),
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
        #'host_affinity':','.join(MISC.get_server_affinity(self.id, self.gbl['hon_data']['svr_total_per_core'])),
        'man_cowServerPort':global_config.get('svr_starting_gamePort') - 2
    },
    'name' : f'{global_config.get("svr_name")}'
    })
    return local

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
            try:
                if k == 'svr_name':
                    return d[k].replace(' 0','')
                return d[k]
            except:
                pass
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
                'svr_port':self.get_global_by_key('svr_starting_gamePort')+self.id - 1,
                'svr_proxyPort':self.get_global_by_key('svr_starting_gamePort')+self.id+10000 - 1,
                'svr_proxyLocalVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id - 1,
                'svr_proxyRemoteVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id+10000 - 1,
                'svr_voicePortStart':self.get_global_by_key('svr_starting_voicePort')+self.id - 1,
                'man_enableProxy':self.get_global_by_key('man_enableProxy'),
                'svr_location':self.get_global_by_key('svr_location'),
                'svr_enableBotMatch': self.get_global_by_key('svr_enableBotMatch'),
                'svr_override_affinity': self.get_global_by_key('svr_override_affinity'),
                'svr_total_per_core' : self.get_global_by_key('svr_total_per_core'),
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
                'host_affinity':','.join(MISC.get_server_affinity(self.id, self.gbl['hon_data']['svr_total_per_core'])),
            },
            'name' : f'{self.get_global_by_key("svr_name")}-{self.id}'
        })

        if self.get_global_by_key('svr_override_affinity'):
            self.local['params'].pop('host_affinity', None)  # Remove 'host_affinity' key if svr_override_affinity is True

        return self.local
