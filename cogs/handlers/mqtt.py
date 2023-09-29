import paho.mqtt.client as mqtt
import json

class MQTTHandler:

    def __init__(self, server="45.132.247.12", port=1883, keepalive=60, username='guam', password='guam', global_config=None):
        self.server = server
        self.port = port
        self.keepalive = keepalive

        # Create a new MQTT client instance
        self.client = mqtt.Client()

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
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
            'svr_version' : self.global_config['hon_data']['svr_version']
        }

    def publish_json(self, topic, data, qos=0):
        data.update(self.add_metadata())
        payload = json.dumps(data)
        result = self.client.publish(topic, payload, qos)
        return result.rc == mqtt.MQTT_ERR_SUCCESS