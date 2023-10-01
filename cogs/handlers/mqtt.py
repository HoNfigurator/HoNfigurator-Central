import paho.mqtt.client as mqtt
import json
import datetime
from utilities.filebeat import get_filebeat_crt_path, get_filebeat_key_path
from cogs.misc.logger import get_logger, get_misc, get_home
from os.path import exists
import ssl
import os
from pathlib import Path
import utilities.step_certificate as step_certificate

LOGGER = get_logger()

class MQTTHandler:

    def __init__(self, server="45.132.247.12", port=8883, keepalive=60, username=None, password=None, global_config=None):
        self.server = server
        self.port = port
        self.keepalive = keepalive

        self.certificate_path = get_filebeat_crt_path()
        self.key_path = get_filebeat_key_path()

        # Create a new MQTT client instance
        self.client = mqtt.Client()
        if get_misc().get_os_platform() == "win32":
            step_ca_dir = Path(os.environ["HOMEPATH"]) / ".step" / "certs"
        else:
            step_ca_dir = Path(os.environ["HOME"]) / ".step" / "certs"


        # Set the credentials and certificates
        self.client.tls_set(ca_certs=step_ca_dir / "root_ca.crt",
                            tls_version=ssl.PROTOCOL_TLSv1_2,
               certfile=get_filebeat_crt_path(),
               keyfile=get_filebeat_key_path())

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        if username and password:
            self.client.username_pw_set(username,password)

        self.global_config = global_config

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print("Connected successfully to broker")
        else:
            print(f"Connection failed with code {rc}")

    def _on_publish(self, client, userdata, mid):
        print(f"Message Published with MID: {mid}")

    def connect(self):
        self.client.connect(self.server, self.port, self.keepalive)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
    
    def add_metadata(self):
        return {
            'svr_ip' : self.global_config['hon_data']['svr_ip'],
            'svr_name' : self.global_config['hon_data']['svr_name'],
            'svr_version' : self.global_config['hon_data']['svr_version'],
            'svr_total_per_core' : self.global_config['hon_data']['svr_total_per_core'],
            'github_branch': self.global_config['system_data']['github_branch'],
            'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'svr_location': self.global_config['hon_data']['svr_location'],
            'cpu_name': self.global_config['system_data']['cpu_name'],
            'cpu_count': self.global_config['system_data']['cpu_count']
        }

    def publish_json(self, topic, data, qos=1):
        data.update(self.add_metadata())
        payload = json.dumps(data)
        result = self.client.publish(topic, payload, qos)
        return result.rc == mqtt.MQTT_ERR_SUCCESS