from fastapi import FastAPI, Request, Response, Body, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
import httpx
from fastapi.responses import JSONResponse
from typing import Any, Dict
import uvicorn
import asyncio
from cogs.misc.logging import get_logger, get_misc, get_home
from cogs.db.roles_db_connector import RolesDatabase
from typing import Any, Dict, List, Tuple
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
roles_database = RolesDatabase()


app = FastAPI(
    title="HoNfigurator API Server",
    version="1.0.0",
    description="API Server for HoNfigurator",
    docs_url="/docs",
    redoc_url="/redoc"
)


def get_config_item_by_key(k):
    for d in global_config.values():
        try: return d[k]
        except: pass
    return None

"""!! SECURITY !!"""

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="https://discord.com/api/oauth2/token")

async def verify_token(request: Request, token: str = Depends(oauth2_scheme)):
    async with httpx.AsyncClient() as client:
        response = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token}"})

    if response.status_code == 200:
        user_info = response.json()
        return {"token": token, "user_info": user_info}
    else:
        LOGGER.warn(f"API Request from: {request.client.host} - Discord user lookup failure. Discord API Response: {response.text}")
        raise HTTPException(status_code=401, detail="Invalid OAuth token")

def check_permission_factory(allowed_roles: List[str]):
    async def check_permission(request: Request, token_and_user_info: dict = Depends(verify_token)):
        user_info = token_and_user_info["user_info"]

        if not has_permission(user_info, allowed_roles):
            LOGGER.warn(f"API Request from: {request.client.host} - Insufficient permissions")
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return token_and_user_info

    return check_permission

def has_permission(user_info: dict, allowed_roles: List[str]) -> bool:
    user_id = user_info["id"]
    user_roles = roles_database.get_user_roles_by_discord_id(user_id)

    if not user_roles:
        return False
    
    for r in range(0,len(user_roles)):
        user_roles[r] = user_roles[r].lower()

    return any(role.lower() in allowed_roles for role in user_roles)


def check_permission(permission: str, token_and_user_info: dict = Depends(verify_token)):
    user_info = token_and_user_info["user_info"]

    if not has_permission(user_info, permission):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return token_and_user_info

"""
API Endpoints below
"""
"""Unprotected Endpoints"""
class PingResponse(BaseModel):
    status: str
@app.get("/api/ping", response_model=PingResponse, description="Responds with the a simple pong to indicate server is alive.")
async def ping():
    return {"status":"OK"}

"""Protected Endpoints"""

"""Config Types"""
class GlobalConfigResponse(BaseModel):
    global_config: Dict

@app.get("/api/get_global_config")
async def get_global_config():
    # Replace this with your actual global_config data
    return global_config

class TotalServersResponse(BaseModel):
    total_servers: int

@app.get("/api/get_total_servers", response_model=TotalServersResponse)
def get_total_servers(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"total_servers": global_config['hon_data']['svr_total']}

class TotalCpusResponse(BaseModel):
    total_cpus: int

@app.get("/api/get_total_cpus", response_model=TotalCpusResponse)
def get_total_cpus(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"total_cpus": MISC.get_cpu_count()}

class CpuNameResponse(BaseModel):
    cpu_name: str

@app.get("/api/get_cpu_name", response_model=CpuNameResponse)
def get_cpu_name(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"cpu_name": MISC.get_cpu_name()}

class CpuUsageResponse(BaseModel):
    cpu_usage: float

@app.get("/api/get_cpu_usage", response_model=CpuUsageResponse)
def get_cpu_usage(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"cpu_usage": MISC.get_cpu_load()}

class MemoryUsageResponse(BaseModel):
    memory_usage: float

@app.get("/api/get_memory_usage", response_model=MemoryUsageResponse)
def get_memory_usage(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"memory_usage": MISC.get_used_ram()}

class MemoryTotalResponse(BaseModel):
    memory_total: float

@app.get("/api/get_memory_total", response_model=MemoryTotalResponse)
def get_memory_total(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"memory_total": MISC.get_total_ram()}

class SvrIpResponse(BaseModel):
    svr_ip: str

@app.get("/api/get_svr_ip", response_model=SvrIpResponse)
def get_svr_ip(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"svr_ip": global_config['hon_data']['svr_ip']}

class TotalAllowedServersResponse(BaseModel):
    total_allowed_servers: int

@app.get("/api/get_total_allowed_servers", response_model=TotalAllowedServersResponse)
def get_total_allowed_servers(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return {"total_allowed_servers": MISC.get_total_allowed_servers(global_config['hon_data']['svr_total_per_core'])}

class NumPlayersIngameResponse(BaseModel):
    num_players_ingame: int

@app.get("/api/get_num_players_ingame", response_model=NumPlayersIngameResponse)
def get_num_players_ingame(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    num = 0
    for game_server in game_servers.values():
        num_clients = game_server.get_dict_value('num_clients')
        if num_clients is not None:
            num += num_clients
    return {"num_players_ingame": num}

class NumMatchesIngameResponse(BaseModel):
    num_matches_ingame: int

@app.get("/api/get_num_matches_ingame", response_model=NumMatchesIngameResponse)
def get_num_matches_ingame(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    num = 0
    for game_server in game_servers.values():
        if game_server.get_dict_value('match_started') == 1:
            num += 1
    return {"num_matches_ingame": num}

@app.get("/api/get_skipped_frame_data/{port}")
def get_skipped_frame_data(port: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
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
def get_num_matches_ingame(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
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
def get_skipped_frame_data(port: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
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
                        "skipped_frames": list[int],
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
@app.get("/api/get_server_config_item/{key}", summary="Get server config item")
def get_server_config_item(key: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    """
    Get a specific item from the server configuration.

    Args:
        key (str): The key of the item to retrieve from the server configuration.

    Returns:
        The value of the item in the server configuration corresponding to the provided key.
    """
    return str(get_config_item_by_key(key))

@app.get("/api/get_server_config", summary="Get server config")
def get_server_config(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
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
def get_num_reserved_cpus(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return str(MISC.get_num_reserved_cpus())

# Define the /api/get_instances_status endpoint with OpenAPI documentation
@app.get("/api/get_instances_status", summary="Get instances status")
#def get_instances(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
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

"""
Roles & Perms
"""
@app.get("/api/roles/all", summary="Get all roles with associated permissions")
# def get_all_roles(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
def get_all_roles(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return roles_database.get_all_roles()

@app.get("/api/roles", summary="Get specified role with associated permissions")
# def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    roles = roles_database.get_all_roles()
    if role in roles:
        return roles[role]
    else: return {"error":"no such role."}

@app.delete("/api/roles/delete/{role_name}", summary="Delete specified role")
# def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
def delete_role(role_name: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    roles = roles_database.get_all_roles()
    role_to_delete = [role for role in roles if role["name"] == role_name]
    if role_to_delete:
        roles_database.remove_role(role_to_delete[0])
        return {"message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Role not found")

class AddRole(BaseModel):
    name: str
    permissions: list

@app.post("/api/roles/add", summary="Add specified user with associated roles", response_model=AddRole)
def add_role(role_form: AddRole, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    roles = roles_database.get_all_roles()
    role_exists = [role for role in roles if role["name"] == role_form.name]
    new_role = {
        "name": role_form.name,
        "permissions": role_form.permissions
    }
    if role_exists:
        roles_database.edit_role(new_role)
        return JSONResponse(status_code=200, content=new_role)
    else:
        roles_database.add_role(new_role)
        return JSONResponse(status_code=201, content=new_role)

@app.get("/api/users/all", summary="Get all users with associated roles")
# def get_all_users(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
def get_all_users(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    return roles_database.get_all_users_with_roles()

@app.get("/api/users", summary="Get specified user with associated roles")
# def get_user(user: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
def get_user(user: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    users = roles_database.get_all_users()
    if user in users:
        return user
    raise HTTPException(status_code=404, detail="User not found")

@app.delete("/api/users/delete/{user_id}", summary="Delete specified user")
def delete_user(user_id: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    users = roles_database.get_all_users()
    user_to_delete = [user for user in users if user["discord_id"] == user_id]
    if user_to_delete:
        roles_database.remove_user(user_to_delete[0])
        return {"message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="User not found")


class AddUser(BaseModel):
    nickname: str
    discord_id: str
    roles: list

@app.post("/api/users/add", summary="Add specified user with associated roles", response_model=AddUser)
def add_user(user_form: AddUser, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    users = roles_database.get_all_users()
    user_exists = [user for user in users if user["discord_id"] == user_form.discord_id]
    new_user = {
        "discord_id": user_form.discord_id,
        "nickname": user_form.nickname,
        "roles": user_form.roles
    }
    if user_exists:
        roles_database.edit_user(new_user)
        return JSONResponse(status_code=200, content=new_user)
    else:
        roles_database.add_new_user(new_user)
        return JSONResponse(status_code=201, content=new_user)


@app.get("/api/permissions/all", summary="Get all API endpoints with associated permissions")
def get_all_permissions(token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    endpoints = {}
    openapi_schema = app.openapi()
    paths = openapi_schema["paths"]
    for path, methods in paths.items():
        description = methods[list(methods.keys())[0]].get("description", "")
        endpoints.update({path:description})
    return endpoints


"""Control Types"""
# Define the /api/stop_server endpoint with OpenAPI documentation
@app.post("/api/stop_server/{port}", summary="Stop a game server instance")
async def stop_server(port: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    """
    Stop a game server instance.

    Args:
        port (ServerPort): The port number of the game server to stop.

    Returns:
        None.
    """
    if port != "all":
        game_server = game_servers.get(int(port),None)
        if game_server is None: return JSONResponse(status_code=404, content={"error":"Server not managed by manager."})
        await manager_event_bus.emit('cmd_shutdown_server', game_server)
    else:
        for game_server in game_servers.values():
            await manager_event_bus.emit('cmd_shutdown_server', game_server)

@app.post("/api/start_server/{port}", summary="Start a game server instance")
async def start_server(port: str, token_and_user_info: dict = Depends(check_permission_factory(allowed_roles=["admin","superadmin"]))):
    """
    Start a game server instance.

    Args:
        port (ServerPort): The port number of the game server to start.

    Returns:
        None.
    """
    if port != "all":
        game_server = game_servers.get(int(port),None)
        if game_server is None: return JSONResponse(status_code=404, content={"error":"Server not managed by manager."})
        await manager_event_bus.emit('start_game_servers', game_server)
    else:
        for game_server in game_servers.values():
            await manager_event_bus.emit('start_game_servers', game_server)

@app.post("/api/add_servers/{num}", description="Add X number of game servers. Dynamically creates additional servers based on total allowed count.")
async def add_all_servers(num: int):
    await manager_event_bus.emit('balance_game_server_count',add_servers=num)

@app.post("/api/add_all_servers", description="Add total number of possible servers.")
async def add_servers():
    await manager_event_bus.emit('balance_game_server_count',add_servers="all")

@app.post("/api/remove_servers/{num}", description="Remove X number of game servers. Dynamically removes servers idle servers.")
async def remove_servers(num: int):
    await manager_event_bus.emit('balance_game_server_count',remove_servers=num)

@app.post("/api/remove_all_servers", description="Remove all idle servers. Marks occupied servers as 'To be removed'.")
async def remove_all_servers():
    await manager_event_bus.emit('balance_game_server_count',remove_servers="all")

""" End API Calls """



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
