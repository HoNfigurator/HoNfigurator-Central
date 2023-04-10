#!/usr/bin/env python3
import json
from pprint import pprint
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.route('/api/data', methods=['GET'])
def get_data():
    data = {"key": "value"}
    return jsonify(data)

# Test
@app.route('/api/get_server_config', methods=['GET'])
def get_server_config():
    return jsonify(str(app.config["global_config"]))

@app.route('/api/get_instances_status', methods=['GET'])
def get_instances():
    data = {"server-1" : "running"}
    return jsonify(data)

#def start_api_server(global_config):
def start_api_server(global_config):
    app.config["global_config"] = global_config
    # FIXME:
    # thats just a default config. we should change it later to
    # restrict access and move the port. but for now its okay i guess.
    app.run(host="127.0.0.1", port=5000, debug=False)

