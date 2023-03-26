import os,sys,psutil,subprocess,traceback
import urllib.request
import platform
import json
from functools import reduce

class ServerGarage():
    def __init__(self,id,gbl_config):
        id = id
        self.gbl_config = gbl_config
        self.server_data = {}
    def build(self):
        try:
            self.data = ({
                'config' : {
                    'file_name':f'KONGOR_ARENA_{id}.exe',
                    'file_path' :f'{self.gbl_config["hon_data"]["hon_install_directory"]}'
                },
                'params' : {
                    'svr_port':self.gbl_config['hon_data']['starting_game_port']+id,
                    'svr_proxyPort':self.gbl_config['hon_data']['starting_game_port']+id+10000,
                    'svr_localVoicePort':self.gbl_config['hon_data']['starting_voice_port']+id,
                    'svr_RemoteVoicePort':self.gbl_config['hon_data']['starting_voice_port']+id+10000,
                    'svr_proxyEnabled':self.gbl_config['hon_data']['enable_proxy']
                },
                'name' : f'{self.gbl_config["hon_data"]["server_name"]}-{id}'
            })
            db_broker.Server().upsert_by_id(self.server_data,id)
        except Exception:
            print(traceback.format_exc())
            return False
        return self.data
class Enrichment:
    def __init__(self):
        return
    def get_cpu(self):
        try:
            return platform.processor()
        except:
            return "couldn't obtain"
    def get_public_ip(self):
        try:
            external_ip = urllib.request.urlopen('https://4.ident.me').read().decode('utf8')
        except Exception:
            external_ip = urllib.request.urlopen('http://api.ipify.org').read().decode('utf8')
        return external_ip
    def get_svr_description(self):
        return f"cpu: {self.get_cpu()}"

def get_global_configuration():
    with open("C:\\Users\\honserver4\\Documents\\GitHub\\honfigurator-central\\config\\config_data2.json", "r") as jsonfile:
        gbl = json.load(jsonfile)
        if 'svr_ip' not in gbl['hon_data']:
            public_ip = Enrichment().get_public_ip()
            gbl['hon_data']['svr_ip'] = public_ip
        gbl['hon_data']['hon_logs_directory'] = f"{gbl['hon_data']['hon_home_directory']}\\Documents\\Heroes of Newerth x64\\game\\logs"
        return gbl

#global_config = get_global_configuration()

class ConfigManagement():
    def __init__(self,id,gbl):
        self.id = id
        self.gbl = gbl
        self.local = self.get_local_configuration()
    def get_total_servers(self):
        return self.gbl['hon_data']['server_total']
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
        self.local = ({
            'config' : {
                'file_name':f'KONGOR_ARENA_{self.id}.exe',
                'file_path' :f'{self.get_global_by_key("hon_install_directory")}KONGOR_ARENA_{self.id}.exe'
            },
            'params' : {
                'svr_login':f"{self.get_global_by_key('svr_login')}:{self.id}",
                'svr_password':self.get_global_by_key('svr_password'),
                'svr_description':Enrichment().get_svr_description(),
                'sv_masterName':f"{self.get_global_by_key('svr_login')}:",
                'svr_slave':self.id,
                'svr_adminPassword':"",
                'svr_name':f"{self.get_global_by_key('svr_name')} {self.id} 0",
                'svr_ip':self.get_global_by_key('svr_ip') if 'svr_ip' in self.gbl['hon_data'] else Enrichment().get_public_ip(),
                'svr_port':self.get_global_by_key('starting_game_port')+self.id,
                'svr_proxyPort':self.get_global_by_key('starting_game_port')+self.id+10000,
                'svr_proxyLocalVoicePort':self.get_global_by_key('starting_voice_port')+self.id,
                'svr_proxyRemoteVoicePort':self.get_global_by_key('starting_voice_port')+self.id+10000,
                'man_enableProxy':self.get_global_by_key('enable_proxy'),
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
                'host_affinity':self.id - 1
            },
            'name' : f'{self.get_global_by_key("server_name")}-{self.id}'
        })
        return self.local