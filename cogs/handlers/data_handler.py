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

def get_cowmaster_configuration(hon_data):
    file_name = hon_data['hon_executable_name']

    local = ({
        'config' : {
            'file_name':file_name,
            'file_path' : str(Path(hon_data.get("hon_install_directory")) / f'{file_name}')
    },
    'params' : {
        'svr_login':f"{hon_data.get('svr_login')}:0",
        'svr_password':hon_data.get('svr_password'),
        'svr_description':MISC.get_svr_description(),
        'sv_masterName':f"{hon_data.get('svr_login')}:",
        'svr_slave':0,
        'svr_adminPassword':"",
        'svr_name':f"{hon_data.get('svr_name')} 0",
        'svr_ip':hon_data.get('svr_ip') if 'svr_ip' in hon_data else MISC.get_public_ip(),
        'svr_port':hon_data.get('svr_starting_gamePort') - 2,
        'svr_voicePortStart':hon_data.get('svr_starting_voicePort'),
        'man_enableProxy':hon_data.get('man_enableProxy'),
        'svr_location':hon_data.get('svr_location'),
        'svr_enableBotMatch': hon_data.get('svr_enableBotMatch'),
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
        'man_cowServerPort':hon_data.get('svr_starting_gamePort') - 2,
        'cow_precache':True
    },
    'name' : f'{hon_data.get("svr_name")}'
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
        self.local = ({
            'config' : {
                'file_name':self.gbl['hon_data']['hon_executable_name'],
                'file_path' : str(Path(self.get_global_by_key("hon_install_directory")) / f"{self.gbl['hon_data']['hon_executable_name']}")
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
                'svr_port':self.get_global_by_key('svr_starting_gamePort') + self.id - 1,
                'svr_proxyPort':self.get_global_by_key('svr_starting_gamePort') + self.id + self.gbl['hon_data']['man_proxyPortIncrement'] - 1,
                'svr_proxyLocalVoicePort':self.get_global_by_key('svr_starting_voicePort') + self.id - 1,
                'svr_proxyRemoteVoicePort':self.get_global_by_key('svr_starting_voicePort')+self.id + self.gbl['hon_data']['man_proxyPortIncrement'] - 1,
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

        if MISC.get_os_platform() == "linux":
            if not self.gbl['hon_data']['man_enableProxy']:
                pass

            elif not self.gbl['hon_data']['man_thirdPartyProxy']:
                LOGGER.warn(f"Proxy configuration enabled but no third party proxy provided. You're either intending to run the proxy on another host, or you've forgotten to set this setting. Supported third party proxies: {MISC.get_supported_thirdparty_proxies()}")
            
            elif self.gbl['hon_data']['man_thirdPartyProxy'] not in MISC.get_supported_thirdparty_proxies():
                LOGGER.warn(f"Unsupported thirdparty proxy provided ({self.gbl['hon_data']['man_thirdPartyProxy']}). Supported third party proxies: {MISC.get_supported_thirdparty_proxies()}")

            else:
                if self.gbl['hon_data']['man_thirdPartyProxy'] == "quilkin":
                    self.local['config']['proxy_game_cmdline'] = ["quilkin","--no-admin","proxy","-p",self.local['params']['svr_proxyPort'],"--to",f"127.0.0.1:{self.local['params']['svr_port']}"]
                    self.local['config']['proxy_voice_cmdline'] = ["quilkin","--no-admin","proxy","-p",self.local['params']['svr_proxyRemoteVoicePort'],"--to",f"127.0.0.1:{self.local['params']['svr_proxyLocalVoicePort']}"]

        if self.get_global_by_key('svr_override_affinity'):
            self.local['params'].pop('host_affinity', None)  # Remove 'host_affinity' key if svr_override_affinity is True

        return self.local
