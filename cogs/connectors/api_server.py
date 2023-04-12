from fastapi import FastAPI, Response, Body, Request
from fastapi.responses import JSONResponse
from typing import Any, Dict
import uvicorn
import asyncio
from cogs.misc.logging import get_logger
import logging
import pathlib
import json
from pydantic import BaseModel

app = FastAPI()
LOGGER = get_logger()
# # Define a custom formatter for the Uvicorn logger
# api_server_formatter = logging.Formatter('%(asctime)s - %(levelname)s - API Server - %(message)s')

# Create a global variable to store the global_config
global_config: Dict[str, Any] = {}

# Custom JSON encoder that handles WindowsPath objects
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Path):
            return str(obj)
        return super(CustomJSONEncoder, self).default(obj)

@app.get("/api/data")
def get_data():
    data = {"key": "value"}
    return data

@app.get("/api/get_global_config")
def get_global_config():
    return str(global_config)

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
        # Create a new logger for uvicorn
        uvicorn_logger = logging.getLogger("uvicorn")

        # Set the handlers, log level, and propagation settings to match your existing logger
        uvicorn_logger.handlers = LOGGER.handlers.copy()

        uvicorn_logger.setLevel(LOGGER.level)
        uvicorn_logger.propagate = LOGGER.propagate

        return await uvicorn.run(
            app,
            host=host,
            port=port,
            log_level="info",
            lifespan="on",
            use_colors=False
        )

    # Create an asyncio task from the coroutine, and return the task
    return asyncio.create_task(asgi_server())