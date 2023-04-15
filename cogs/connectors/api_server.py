from fastapi import FastAPI, Response, Body, HTTPException
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
HOME_PATH = get_home()
MISC = get_misc()


app = FastAPI(
    title="HoNfigurator API Server",
    version="1.0.0",
    description="API Server for HoNfigurator",
    docs_url="/docs",
    redoc_url="/redoc"
)

class Credentials(BaseModel):
    email: str
    password: str

@app.post("/api/authenticate")
def authenticate_user(credentials: Credentials):
    if credentials.email == "test@test.com" and credentials.password == "test":
        return {"token": "sample_token"}
    else:
        raise HTTPException(status_code=401, detail="Invalid email or password")

# Define your API endpoints here

class DataResponse(BaseModel):
    key: str

@app.get("/api/data", response_model=DataResponse)
def get_data():
    data = {"key": "value"}
    return data

class GlobalConfigResponse(BaseModel):
    hon_data: Dict[str, Any]

@app.get("/api/get_global_config", response_model=GlobalConfigResponse)
def get_global_config():
    return {"hon_data": global_config}

class TotalServersResponse(BaseModel):
    total_servers: int

@app.get("/api/get_total_servers", response_model=TotalServersResponse)
def get_total_servers():
    return {"total_servers": global_config['hon_data']['svr_total']}

class TotalCpusResponse(BaseModel):
    total_cpus: int

@app.get("/api/get_total_cpus", response_model=TotalCpusResponse)
def get_total_cpus():
    return {"total_cpus": MISC.get_cpu_count()}

class CpuNameResponse(BaseModel):
    cpu_name: str

@app.get("/api/get_cpu_name", response_model=CpuNameResponse)
def get_cpu_name():
    return {"cpu_name": MISC.get_cpu_name()}

class CpuUsageResponse(BaseModel):
    cpu_usage: float

@app.get("/api/get_cpu_usage", response_model=CpuUsageResponse)
def get_cpu_usage():
    return {"cpu_usage": MISC.get_cpu_load()}

class MemoryUsageResponse(BaseModel):
    memory_usage: float

@app.get("/api/get_memory_usage", response_model=MemoryUsageResponse)
def get_memory_usage():
    return {"memory_usage": MISC.get_used_ram()}

class MemoryTotalResponse(BaseModel):
    memory_total: float

@app.get("/api/get_memory_total", response_model=MemoryTotalResponse)
def get_memory_total():
    return {"memory_total": MISC.get_total_ram()}

class SvrIpResponse(BaseModel):
    svr_ip: str

@app.get("/api/get_svr_ip", response_model=SvrIpResponse)
def get_svr_ip():
    return {"svr_ip": global_config['hon_data']['svr_ip']}

class TotalAllowedServersResponse(BaseModel):
    total_allowed_servers: int

@app.get("/api/get_total_allowed_servers", response_model=TotalAllowedServersResponse)
def get_total_allowed_servers():
    return {"total_allowed_servers": MISC.get_total_allowed_servers(global_config['hon_data']['svr_total_per_core'])}

class NumPlayersIngameResponse(BaseModel):
    num_players_ingame: int

@app.get("/api/get_num_players_ingame", response_model=NumPlayersIngameResponse)
def get_num_players_ingame():
    num = 0
    for game_server in game_servers.values():
        num_clients = game_server.get_dict_value('num_clients')
        if num_clients is not None:
            num += num_clients
    return {"num_players_ingame": num}

class NumMatchesIngame(BaseModel):
    num_matches_ingame: int

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

class NumMatchesResponse(BaseModel):
    num: int

@app.get("/api/get_num_matches_ingame", response_model=NumMatchesResponse, summary="Get number of matches in game")
def get_num_matches_ingame():
    """
    Get the number of matches in game.

    This endpoint returns the number of game servers that have a match started.

    Returns:
        A JSON response with the following schema:

        ```
        {
            "num": int
        }
        ```

        The value of the "num" field is the number of game servers that have a match started.
    """
    num = 0
    for game_server in game_servers.values():
        if game_server.get_dict_value('match_started') == 1:
            num += 1
    return {"num": num}

# Define a Pydantic model for the /api/get_skipped_frame_data endpoint response
class SkippedFramesResponse(BaseModel):
    server_data: Dict[str, Any]

@app.get("/api/get_skipped_frame_data", response_model=SkippedFramesResponse, summary="Get skipped frame data")
def get_skipped_frame_data(port: str):
    """
    Get skipped frame data.

    This endpoint returns detailed information about skipped frames for each game server.

    Args:
        port (str): The port number of the game server to get skipped frame data for, or "all" to get skipped frame data for all game servers.

    Returns:
        A JSON response with the following schema:

        ```
        {
            "server_data": {
                "<server_name>": {
                    "<player_id>": {
                        "skipped_frames": List[int],
                        "time_skipped": float
                    }
                }
            }
        }
        ```

        The "server_data" field is a dictionary with keys representing the names of game servers, and values representing dictionaries containing information about each player who skipped frames on that server. Each player dictionary contains a "skipped_frames" field with a list of skipped frame numbers and a "time_skipped" field with the total amount of time the player skipped frames for in seconds.
    """
    temp = {}
    if port != "all":
        game_server = game_servers.get(int(port),None)
        if game_server is None: return
        temp = game_server.get_dict_value("skipped_frames_detailed")
    else:
        for game_server in game_servers.values():
            temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_dict_value("skipped_frames_detailed")
    return {"server_data": temp}

# Define the /api/get_server_config_item endpoint with OpenAPI documentation
@app.get("/api/get_server_config_item", summary="Get server config item")
def get_server_config_item(key: str):
    """
    Get a specific item from the server configuration.

    Args:
        key (str): The key of the item to retrieve from the server configuration.

    Returns:
        The value of the item in the server configuration corresponding to the provided key.
    """
    return str(get_config_item_by_key(key))

@app.get("/api/get_server_config", summary="Get server config")
def get_server_config():
    """
    Get the server configuration.

    This endpoint returns the local configuration of each game server.

    Returns:
        A JSON response with the server configurations for each game server.
    """
    # Create an empty dictionary to store the local configurations
    temp = {}

    # Iterate through the game servers and store their local configurations
    for game_server in game_servers.values():
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.config.get_local_configuration()
    return temp

@app.get("/api/get_num_reserved_cpus")
def get_num_reserved_cpus():
    return str(MISC.get_num_reserved_cpus())

# Define the /api/get_instances_status endpoint with OpenAPI documentation
@app.get("/api/get_instances_status", summary="Get instances status")
def get_instances():
    """
    Get the status of all game server instances.

    Returns:
        A JSON response with the status of all game server instances.
    """
    temp = {}
    for game_server in game_servers.values():
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_pretty_status()
    return temp


# Define a Pydantic model for the /api/stop_server and /api/start_server endpoints
class ServerPort(BaseModel):
    port: int

# Define the /api/stop_server endpoint with OpenAPI documentation
@app.post("/api/stop_server", summary="Stop a game server instance")
async def stop_server(server_port_data: ServerPort):
    """
    Stop a game server instance.

    Args:
        server_port_data (ServerPort): The port number of the game server to stop.

    Returns:
        None.
    """
    server_port = server_port_data.port
    game_server = game_servers.get(server_port, None)

    if game_server:
        await manager_event_bus.emit('cmd_shutdown_server', game_server)


# Define the /api/start_server endpoint with OpenAPI documentation
@app.post("/api/start_server", summary="Start a game server instance")
async def start_server(server_port_data: ServerPort):
    """
    Start a game server instance.

    Args:
        server_port_data (ServerPort): The port number of the game server to start.

    Returns:
        None.
    """
    server_port = server_port_data.port
    game_server = game_servers.get(server_port, None)

    if game_server:
        await manager_event_bus.emit('start_game_servers', game_server)

async def start_api_server(config, game_servers_dict, event_bus, host="0.0.0.0", port=5000):
    global global_config, game_servers, manager_event_bus
    global_config = config
    game_servers = game_servers_dict
    manager_event_bus = event_bus

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
            LOGGER.exception(traceback.format_exc())
    # Create an asyncio task from the coroutine, and return the task
    return asyncio.create_task(asgi_server())
