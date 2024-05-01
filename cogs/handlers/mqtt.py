import paho.mqtt.client as mqtt
import json
import datetime
from cogs.misc.logger import get_logger, get_misc, get_discord_username
import os
from pathlib import Path

LOGGER = get_logger()

class MQTTHandler:

    def __init__(self, server="mqtt.honfigurator.app", port=8883, keepalive=60, username=None, password=None, global_config=None, certificate_path=None, key_path=None):
        self.server = server
        self.port = port
        self.keepalive = keepalive
        self.certificate_path = certificate_path
        self.key_path = key_path
        self.mastersv_state = None
        self.chatsv_state = None
        self.connected = False

        # Create a new MQTT client instance
        self.client = mqtt.Client()
        if get_misc().get_os_platform() == "win32":
            step_ca_dir = Path(os.environ["HOMEDRIVE"] + os.environ["HOMEPATH"]) / ".step" / "certs"
        else:
            step_ca_dir = Path(os.environ["HOME"]) / ".step" / "certs"

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        
        # Set the credentials and certificates
        if username and password:
            self.client.username_pw_set(username,password)
        else:
            self.client.tls_set(ca_certs=str(step_ca_dir / "root_ca.crt"),
                certfile=certificate_path,
                keyfile=key_path)

        self.global_config = global_config

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            LOGGER.highlight("Connected successfully to MQTT broker")
            self.connected = True
        else:
            LOGGER.error(f"Connection failed with code {rc}")
            
    def _on_disconnect(self, client, userdata, rc):
        LOGGER.warn("Disconnected from MQTT broker")
        self.connected = False

    def _on_publish(self, client, userdata, mid):
        LOGGER.debug(f"Message Published with MID: {mid}")

    def connect(self):
        self.client.connect(self.server, self.port, self.keepalive)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
    
    def set_mastersv_state(self, state):
        self.mastersv_state = state
    
    def set_chatsv_state(self, state):
        self.chatsv_state = state

    def add_metadata(self):
        metadata = {
            'svr_ip' : self.global_config['hon_data']['svr_ip'],
            'svr_name' : self.global_config['hon_data']['svr_name'],
            'svr_api_port' : self.global_config['hon_data']['svr_api_port'],
            'svr_autoping_port': self.global_config['hon_data']['autoping_responder_port'],
            'svr_version' : self.global_config['hon_data']['svr_version'],
            'svr_total_per_core' : self.global_config['hon_data']['svr_total_per_core'],
            'github_branch': self.global_config['system_data']['github_branch'],
            'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'svr_location': self.global_config['hon_data']['svr_location'],
            'cpu_name': self.global_config['system_data']['cpu_name'],
            'cpu_count': self.global_config['system_data']['cpu_count'],
            'chatsv_state': self.chatsv_state,
            'mastersv_state': self.mastersv_state,
            'branch_version': get_misc().get_github_tag(),
            'hon_user': self.global_config['hon_data']['svr_login']
        }
        if get_discord_username():
            metadata.update({'discord_id':get_discord_username()})
            
        return metadata

    def publish_json(self, topic, data, qos=1):
        if not self.connected:
            try:
                self.connect()
            except:
                LOGGER.error("Failed to connect to MQTT broker")
                return False

        data.update(self.add_metadata())
        payload = json.dumps(data)
        result = self.client.publish(topic, payload, qos)
        return result.rc == mqtt.MQTT_ERR_SUCCESS