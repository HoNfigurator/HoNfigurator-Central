from fastapi import FastAPI, Response, Body, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict
import uvicorn
import asyncio
from cogs.misc.logging import get_logger, get_misc, get_home
import logging
from os.path import exists
import json
from pydantic import BaseModel
import ssl
import traceback

app = FastAPI()

LOGGER = get_logger()
MISC = get_misc()
HOME_PATH = get_home()
# # Define a custom formatter for the Uvicorn logger
# api_server_formatter = logging.Formatter('%(asctime)s - %(levelname)s - API Server - %(message)s')

# Create a global variable to store the global_config
global_config: Dict[str, Any] = {}

def get_config_item_by_key(k):
    for d in global_config.values():
        try: return d[k]
        except: pass
    return None

@app.get("/api/data")
def get_data():
    data = {"key": "value"}
    return data

@app.get("/api/get_global_config")
def get_global_config():
    return str(global_config)

@app.get("/api/get_total_servers")
def get_total_servers():
    return str(global_config['hon_data']['svr_total'])

@app.get("/api/get_total_cpus")
def get_total_cpus():
    return str(MISC.get_cpu_count())

@app.get("/api/get_cpu_name")
def get_cpu_name():
    return str(MISC.get_cpu_name())

@app.get("/api/get_cpu_usage")
def get_cpu_usage():
    return str(MISC.get_cpu_load())

@app.get("/api/get_memory_usage")
def get_memory_usage():
    return str(MISC.get_used_ram())

@app.get("/api/get_memory_total")
def get_memory_total():
    return str(MISC.get_total_ram())

@app.get("/api/get_svr_ip")
def get_total_servers():
    return str(global_config['hon_data']['svr_ip'])

@app.get("/api/get_total_allowed_servers")
def get_total_allowed_servers():
    return str(MISC.get_total_allowed_servers(global_config['hon_data']['svr_total_per_core']))

@app.get("/api/get_num_players_ingame")
def get_num_matches_ingame():
    num = 0
    for game_server in game_servers.values():
        num_clients = game_server.get_dict_value('num_clients')
        if num_clients is not None:
            num += num_clients
    return str(num)

@app.get("/api/get_num_matches_ingame")
def get_num_matches_ingame():
    num = 0
    for game_server in game_servers.values():
        if game_server.get_dict_value('match_started') == 1:
            num += 1
    return str(num)

@app.get("/api/get_skipped_frame_data")
def get_skipped_frame_data(port: str):
    temp = {}
    if port != "all":
        game_server = game_servers.get(int(port),None)
        if game_server is None: return
        temp = game_server.get_dict_value("skipped_frames_detailed")
    else:
        for game_server in game_servers.values():
            temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_dict_value("skipped_frames_detailed")
    json_content = json.dumps(temp, indent=2)
    return Response(content=json_content, media_type="application/json")

@app.get("/api/get_server_config_item")
def get_server_config_item(key: str):
    return str(get_config_item_by_key(key))

@app.get("/api/get_server_config")
def get_server_config():
    # Create an empty dictionary to store the local configurations
    temp = {}

    # Iterate through the game servers and store their local configurations
    for game_server in game_servers.values():
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.config.get_local_configuration()
    json_content = json.dumps(temp, indent=2)
    # Return the local configurations as a JSON response
    return Response(content=json_content, media_type="application/json")


@app.get("/api/get_instances_status")
def get_instances():
    temp = {}
    for game_server in game_servers.values():
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_pretty_status()
    json_content = json.dumps(temp, indent=2)
    return Response(content=json_content, media_type="application/json")

class port(BaseModel):
    port: int

@app.post("/api/stop_server")
async def stop_server(server_port_data: port):
    server_port = server_port_data.port
    game_server = game_servers.get(server_port, None)

    if game_server:
        await manager_event_bus.emit('cmd_shutdown_server', game_server)

@app.post("/api/start_server")
async def stop_server(server_port_data: port):
    server_port = server_port_data.port
    game_server = game_servers.get(server_port, None)

    if game_server:
        await manager_event_bus.emit('start_game_servers', game_server)

async def start_api_server(config, game_servers_dict, event_bus, host="127.0.0.1", port=5000):
    global global_config, game_servers, manager_event_bus
    global_config = config
    game_servers = game_servers_dict
    manager_event_bus = event_bus

    # Create a coroutine that starts the ASGI server with the given app, host, and port
    async def asgi_server():
        try:
            # Create a new logger for uvicorn
            uvicorn_logger = logging.getLogger("uvicorn")

            # Set the handlers, log level, and propagation settings to match your existing logger
            uvicorn_logger.handlers = LOGGER.handlers.copy()

            uvicorn_logger.setLevel(logging.WARNING)
            uvicorn_logger.propagate = LOGGER.propagate

            # Specify the path to the certificate and key files
            ssl_keyfile = HOME_PATH / "localhost.key"
            ssl_certfile = HOME_PATH / "localhost.crt"
            if exists(ssl_keyfile) and exists(ssl_certfile):
                return await uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level="warning",
                    lifespan="on",
                    use_colors=False,
                    ssl_keyfile=ssl_keyfile,
                    ssl_certfile=ssl_certfile
                )
            else:
                return await uvicorn.run(
                    app,
                    host=host,
                    port=port,
                    log_level="warning",
                    lifespan="on",
                    use_colors=False
                )
        except Exception:
            print(traceback.format_exc())
    # Create an asyncio task from the coroutine, and return the task
    return asyncio.create_task(asgi_server())