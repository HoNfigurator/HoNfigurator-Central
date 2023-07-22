from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import asyncio
import datetime
import os
import time
import math
from fastapi import FastAPI, Request, Response, Body, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
import httpx
from fastapi.responses import JSONResponse, PlainTextResponse
from typing import Any, Dict
import uvicorn
import asyncio
from cogs.misc.logger import get_logger, get_misc, get_home, get_setup, get_filebeat_auth_url
from cogs.handlers.events import stop_event
from cogs.db.roles_db_connector import RolesDatabase
from cogs.game.match_parser import MatchParser
from typing import Any, Dict, List, Tuple
import logging
from os.path import exists
import json
from pydantic import BaseModel
from datetime import datetime, timedelta
import traceback
import utilities.filebeat as filebeat
from utilities.step_certificate import is_certificate_expiring
import aiofiles
import aiohttp
import ssl

app = FastAPI()
LOGGER = get_logger()
HOME_PATH = get_home()
MISC = get_misc()
SETUP = get_setup()

roles_database = RolesDatabase()

CACHE_EXPIRY = timedelta(minutes=20)  # Change to desired cache expiry time
user_info_cache = {}

app = FastAPI(
    title="HoNfigurator API Server",
    version="1.0.0",
    description="API Server for HoNfigurator",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    LOGGER.error(traceback.format_exc())

def get_config_item_by_key(k):
    for d in global_config.values():
        try: return d[k]
        except: pass
    return None

"""!! SECURITY !!"""

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="https://discord.com/api/oauth2/token")

async def verify_token(request: Request, token: str = Depends(oauth2_scheme)):
    now = datetime.now()

    # If the user info is in the cache and it's not expired, return it
    if token in user_info_cache and now - user_info_cache[token]['timestamp'] < CACHE_EXPIRY:
        return user_info_cache[token]['data']

    async with httpx.AsyncClient() as client:
        response = await client.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token}"})

    if response.status_code == 200:
        user_info = response.json()

        # Store the user info in the cache with the current timestamp
        user_info_cache[token] = {'data': {"token": token, "user_info": user_info}, 'timestamp': now}

        return {"token": token, "user_info": user_info}
    else:
        LOGGER.warn(f"API Request from: {request.client.host} - Discord user lookup failure. Discord API Response: {response.text}")
        raise HTTPException(status_code=401, detail="Invalid OAuth token")

def check_permission_factory(required_permission: str):
    async def check_permission(request: Request, token_and_user_info: dict = Depends(verify_token)):
        user_info = token_and_user_info["user_info"]

        permission = has_permission(user_info, required_permission)
        if not has_permission(user_info, required_permission):
            LOGGER.warn(f"API Request from: {request.client.host} - Insufficient permissions")
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return token_and_user_info

    return check_permission


def get_inherited_roles(role_name: str) -> List[str]:
    role = roles_database.get_role_by_name(role_name)
    if not role:
        return []

    inherits = json.loads(role["inherits"])
    all_inherited_roles = inherits.copy()
    for inherited_role_name in inherits:
        all_inherited_roles.extend(get_inherited_roles(inherited_role_name))

    return all_inherited_roles

def has_permission(user_info: dict, required_permission: str) -> bool:
    user_id = user_info["id"]
    user_permissions = roles_database.get_user_permissions_by_discord_id(user_id)

    if not user_permissions:
        return False

    for p in range(0, len(user_permissions)):
        user_permissions[p] = user_permissions[p].lower()

    return required_permission.lower() in user_permissions



def check_permission(permission: str, token_and_user_info: dict = Depends(verify_token)):
    user_info = token_and_user_info["user_info"]

    if not has_permission(user_info, permission):
        raise HTTPException(status_code=403, content="Insufficient permissions")

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

@app.get("/api/public/get_server_info", description="Returns basic server information.")
async def public_serverinfo():
    response = {}
    for game_server in game_servers.values():
        full_info = game_server.get_pretty_status_for_webui()
        response[game_server.config.get_local_by_key('svr_name')] = {
            "id" : full_info.get("ID"),
            "status" : full_info.get("Status"),
            "region" : full_info.get("Region"),
            "gamephase" : full_info.get("Game Phase")
        }
    return JSONResponse(status_code = 200, content = response)

@app.get("/api/public/check_filebeat_status", summary="Check whether Filebeat is installed and configured to send server logs.")
async def filebeat_installed():
    installed = filebeat.check_filebeat_installed()
    certificate_exists = filebeat.check_certificate_exists(filebeat.get_filebeat_crt_path(), filebeat.get_filebeat_key_path())
    certificate_expiring = False
    if certificate_exists:
        certificate_expiring = is_certificate_expiring(filebeat.get_filebeat_crt_path())
    if installed:
        if MISC.get_os_platform() == "linux":
            if MISC.get_proc('filebeat'):
                return JSONResponse(status_code=200, content={"installed": True, "running": False, "certificate_exists":certificate_exists, "certificate_expiring": certificate_expiring})
            else:
                return JSONResponse(status_code=400, content={"installed": True, "running": False, "certificate_exists":certificate_exists, "certificate_expiring": certificate_expiring})
        else:
            if MISC.get_proc('filebeat.exe'):
                return JSONResponse(status_code=200, content={"installed": True, "running": True, "certificate_exists":certificate_exists, "certificate_expiring": certificate_expiring})
            else:
                return JSONResponse(status_code=400, content={"installed": True, "running": False, "certificate_exists":certificate_exists, "certificate_expiring": certificate_expiring})
    else:
        return JSONResponse(status_code=404, content={"installed": False, "running": False, "certificate_exists":certificate_exists, "certificate_expiring": certificate_expiring})


"""Protected Endpoints"""

"""Config Types"""
class GlobalConfigResponse(BaseModel):
    global_config: Dict

@app.get("/api/get_global_config", description="Returns the global configuration of the manager")
async def get_global_config(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return global_config

@app.get("/api/get_hon_version")
async def get_hon_version(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"data":MISC.hon_version}

@app.get("/api/get_commit_date", description="Return the date of the last commit / the last update time.")
async def get_commit_date(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"data":MISC.get_git_commit_date()}

@app.get("/api/get_replay/{match_id}", description="Searches the server for the specified replay")
async def get_replay(match_id: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    def convert_size(size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    if not match_id:
        return JSONResponse(status_code=500,content="Invalid match ID")
    match_id = match_id.replace("M",'')
    match_id = match_id.replace("m",'')
    match_id = match_id.replace(".honreplay",'')
    replay_exists,path = await manager_find_replay_callback(f"M{match_id}.honreplay")
    if replay_exists:
        # Get the file size in bytes
        file_size = os.path.getsize(path)
        
        # Convert file size to a human readable format
        file_size = convert_size(file_size)
        
        # Get the creation time
        creation_time = os.path.getctime(path)
        
        # Convert the creation time to a readable format
        creation_time = time.ctime(creation_time)
        
        return {
            'match_id': str(match_id),
            'path': str(path),
            'server': global_config['hon_data']['svr_name'],
            'file_size': file_size,
            'creation_time': creation_time
        }
    else:
        return JSONResponse(status_code=404,content="Replay not found")

@app.post("/api/set_hon_data", description="Sets the 'hon_data' key within the global manager data dictionary")
async def set_hon_data(hon_data: dict = Body(...), token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    try:
        validation = SETUP.validate_hon_data(hon_data=hon_data)
        if validation:
            global_config['hon_data'] = hon_data
            await manager_event_bus.emit('update_server_start_semaphore')
            await manager_event_bus.emit('check_for_restart_required')
    except ValueError as e:
        return JSONResponse(status_code=501, content=str(e))

@app.post("/api/set_app_data", description="Sets the 'application_data' key within the global manager data dictionary")
async def set_app_data(app_data: dict = Body(...), token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    try:
        validation = SETUP.validate_hon_data(application_data=app_data)
        if validation:
            global_config['application_data'] = app_data
            await manager_event_bus.emit('check_for_restart_required')
    except ValueError as e:
        return JSONResponse(status_code=501, content=str(e))

class TotalServersResponse(BaseModel):
    total_servers: int

@app.get("/api/get_total_servers", response_model=TotalServersResponse)
def get_total_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"total_servers": len(game_servers)}

class TaskStatusResponse(BaseModel):
    tasks_status: dict

@app.get("/api/get_tasks_status", response_model=TaskStatusResponse)
def get_tasks_status(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    def task_status(tasks_dict):
        task_summary = {}
        for task_name, task in tasks_dict.items():
            if task is None:
                continue
            if task.done():
                try:
                    if task.exception() is not None:
                        task_summary[task_name] = {'status': 'Done', 'exception': str(task.exception()), 'end_time': task.end_time}
                    else:
                        task_summary[task_name] = {'status': 'Done', 'end_time': task.end_time}
                except asyncio.CancelledError:
                    task_summary[task_name] = {'status': 'Cancelled'}
            else:
                task_summary[task_name] = {'status': 'Running'}
        return task_summary
    
    temp = {}
    temp_gameserver_tasks = {}

    for game_server in game_servers.values():
        temp_gameserver_tasks[game_server.config.get_local_by_key('svr_name')] = task_status(game_server.tasks)

    temp['manager'] = task_status(manager_tasks)
    temp['game_servers'] = temp_gameserver_tasks
    temp['health_checks'] = task_status(health_check_tasks)

    return {"tasks_status": temp}

class CurrentGithubBranch(BaseModel):
    branch: str
@app.get("/api/get_current_github_branch", response_model=CurrentGithubBranch)
def get_current_github_branch(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"branch":MISC.get_current_branch_name()}

class AllGithubBranch(BaseModel):
    all_branches: list
@app.get("/api/get_all_github_branches", response_model=AllGithubBranch)
def get_all_github_branches(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"all_branches":MISC.get_all_branch_names()}

@app.post("/api/switch_github_branch/{branch}")
def switch_github_branch(branch: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    result = MISC.change_branch(branch)
    return JSONResponse(status_code=501, content=result)
class TotalCpusResponse(BaseModel):
    total_cpus: int

@app.get("/api/get_total_cpus", response_model=TotalCpusResponse)
def get_total_cpus(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"total_cpus": MISC.get_cpu_count()}

class CpuNameResponse(BaseModel):
    cpu_name: str

@app.get("/api/get_cpu_name", response_model=CpuNameResponse)
def get_cpu_name(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"cpu_name": MISC.get_cpu_name()}

@app.get("/api/get_all_public_ports")
def get_public_ports(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    public_game_ports = []
    public_voice_ports = []
    for game_server in game_servers.values():
        public_game_ports.append(game_server.get_public_game_port())
        public_voice_ports.append(game_server.get_public_voice_port())
    return {
        'autoping_listener': global_config['hon_data']['autoping_responder_port'],
        'public_game_ports': public_game_ports,
        'public_voice_ports': public_voice_ports
    }

class CpuUsageResponse(BaseModel):
    cpu_usage: float

@app.get("/api/get_cpu_usage", response_model=CpuUsageResponse)
def get_cpu_usage(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"cpu_usage": MISC.get_cpu_load()}

class MemoryUsageResponse(BaseModel):
    memory_usage: float

@app.get("/api/get_memory_usage", response_model=MemoryUsageResponse)
def get_memory_usage(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"memory_usage": MISC.get_used_ram()}

class MemoryTotalResponse(BaseModel):
    memory_total: float

@app.get("/api/get_memory_total", response_model=MemoryTotalResponse)
def get_memory_total(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"memory_total": MISC.get_total_ram()}

class SvrIpResponse(BaseModel):
    svr_ip: str

@app.get("/api/get_svr_ip", response_model=SvrIpResponse)
def get_svr_ip(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"svr_ip": global_config['hon_data']['svr_ip']}

class TotalAllowedServersResponse(BaseModel):
    total_allowed_servers: int

@app.get("/api/get_total_allowed_servers", response_model=TotalAllowedServersResponse)
def get_total_allowed_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"total_allowed_servers": MISC.get_total_allowed_servers(global_config['hon_data']['svr_total_per_core'])}

class NumPlayersIngameResponse(BaseModel):
    num_players_ingame: int

@app.get("/api/get_num_players_ingame", response_model=NumPlayersIngameResponse)
def get_num_players_ingame(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    num = 0
    for game_server in game_servers.values():
        num_clients = game_server.get_dict_value('num_clients')
        if num_clients is not None:
            num += num_clients
    return {"num_players_ingame": num}
class NumMatchesIngameResponse(BaseModel):
    num_matches_ingame: int

@app.get("/api/get_num_matches_ingame", response_model=NumMatchesIngameResponse)
def get_num_matches_ingame(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    num = 0
    for game_server in game_servers.values():
        if game_server.get_dict_value('match_started') == 1:
            num += 1
    return {"num_matches_ingame": num}

@app.get("/api/get_skipped_frame_data/{port}")
def get_skipped_frame_data(port: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
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
def get_num_matches_ingame(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
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
def get_skipped_frame_data(port: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
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
def get_server_config_item(key: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    """
    Get a specific item from the server configuration.

    Args:
        key (str): The key of the item to retrieve from the server configuration.

    Returns:
        The value of the item in the server configuration corresponding to the provided key.
    """
    return str(get_config_item_by_key(key))

@app.get("/api/get_server_config", summary="Get server config")
def get_server_config(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
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
def get_num_reserved_cpus(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return MISC.get_num_reserved_cpus()

@app.get("/api/get_honfigurator_log_entries/{num}", description="Returns the specified number of log entries from the honfigurator log file.")
async def get_honfigurator_log(num: int, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    # return the contents of the current log file
    async with aiofiles.open(HOME_PATH / "logs" / "server.log", 'r') as f:
        file_content = await f.readlines()
    
    # Remove the newlines from each string in the list
    file_content = [line.strip() for line in file_content]
    return file_content[-num:][::-1]

@app.get("/api/get_chat_logs/{match_id}", description="Retrieve a list of chat entries from a given match id")
def get_chat_logs(match_id: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    if 'm' not in match_id.lower():
        match_id = f'M{match_id}'
    log_path = global_config['hon_data']['hon_logs_directory'] / f"{match_id}.log"

    if not exists(log_path):
        return JSONResponse(status_code=404, content="Log file not found.")
    
    match_parser = MatchParser(match_id, log_path)
    return match_parser.parse_chat()

@app.get("/api/get_honfigurator_log_file", description="Returns the HoNfigurator log file completely, for download.")
async def get_honfigurator_log_file(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    async with aiofiles.open(HOME_PATH / "logs" / "server.log", "r") as file:
        log_file_content = await file.readlines()
    return log_file_content

# Define the /api/get_instances_status endpoint with OpenAPI documentation
@app.get("/api/get_instances_status", summary="Get instances status")
#def get_instances(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
def get_instances(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    """
    Get the status of all game server instances.

    Returns:
        A JSON response with the status of all game server instances.
    """
    temp = {}
    for game_server in game_servers.values():
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_pretty_status_for_webui()
    return temp

"""
Roles & Perms
"""
@app.get("/api/roles/all", summary="Get all roles with associated permissions")
# def get_all_roles(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
def get_all_roles(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return roles_database.get_all_roles_with_permissions()

@app.get("/api/roles/default", summary="Get all default roles")
def get_default_roles(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return roles_database.get_default_roles()

@app.get("/api/roles", summary="Get specified role with associated permissions")
# def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    roles = roles_database.get_all_roles()
    if role in roles:
        return roles[role]
    else: return {"error":"no such role."}

@app.delete("/api/roles/delete/{role_name}", summary="Delete specified role")
# def get_role(role: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
def delete_role(role_name: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    roles = roles_database.get_all_roles()
    role_to_delete = [role for role in roles if role["name"] == role_name]
    if role_to_delete:
        roles_database.remove_role(role_to_delete[0])
        return {"message": "User deleted successfully"}
    else:
        raise HTTPException(status_code=404, content="Role not found")

class AddRole(BaseModel):
    name: str
    permissions: list

@app.post("/api/roles/add", summary="Add specified user with associated roles", response_model=AddRole)
def add_role(role_form: AddRole, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    roles = roles_database.get_all_roles()
    for i in range(len(role_form.permissions)):
        role_form.permissions[i] = role_form.permissions[i].lower()

    role_exists = [role for role in roles if role["name"] == role_form.name]
    if role_exists:
        return JSONResponse(status_code=501, content="Role with this name already exists.")
    
    new_role = {
        "name": role_form.name.lower(),
        "permissions": role_form.permissions
    }
    roles_database.add_new_role(new_role)
    return JSONResponse(status_code=201, content=new_role)

@app.post("/api/roles/edit", summary="Edit specified user with new values", response_model=AddRole)
def add_role(role_form: AddRole, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    roles = roles_database.get_all_roles()
    new_role = {
        "name": role_form.name.lower(),
        "permissions": role_form.permissions
    }

    role_exists = [role for role in roles if role["name"] == role_form.name]
    if not role_exists:
        return JSONResponse(status_code=501, content="The role you are editing no longer exists.")
    roles_database.add_new_role(new_role)
    return JSONResponse(status_code=201, content=new_role)

@app.get("/api/users/all", summary="Get all users with associated roles")
# def get_all_users(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
def get_all_users(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return roles_database.get_all_users_with_roles()

@app.get("/api/users/default", summary="Get all default users")
def get_default_users(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return roles_database.get_default_users()

@app.get("/api/user", summary="Get specified user with associated roles")
# def get_user(user: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
def get_user(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    roles = roles_database.get_user_roles_by_discord_id(token_and_user_info['user_info']['id'])
    perms = roles_database.get_user_permissions_by_discord_id(token_and_user_info['user_info']['id'])
    if not roles or not perms:
        return JSONResponse(status=404, content="The specified user information was not found.")
    return {'roles':roles, 'perms':perms}

@app.delete("/api/users/delete/{user_id}", summary="Delete specified user")
def delete_user(user_id: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
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
def add_user(user_form: AddUser, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    users = roles_database.get_all_users()
    user_exists = [user for user in users if user["discord_id"] == user_form.discord_id]
    new_user = {
        "discord_id": user_form.discord_id,
        "nickname": user_form.nickname.lower(),
        "roles": user_form.roles
    }
    if user_exists:
        return JSONResponse(status_code=501, content="The specified user already exists.")
    else:
        roles_database.add_new_user(new_user)
        return JSONResponse(status_code=201, content=new_user)

@app.post("/api/users/edit", summary="Edit specified user with new values", response_model=AddUser)
def edit_user(user_form: AddUser, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    users = roles_database.get_all_users()
    user_exists = [user for user in users if user["discord_id"] == user_form.discord_id]
    new_user = {
        "discord_id": user_form.discord_id,
        "nickname": user_form.nickname,
        "roles": user_form.roles
    }
    if not user_exists:
        return JSONResponse(status_code=501, content="The specified user no longer exists. Please refresh the page.")
    roles_database.add_new_user(new_user)
    return JSONResponse(status_code=201, content=new_user)

@app.get("/api/endpoints/all", summary="Get all API endpoints with associated permissions")
def get_all_endpoints(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    endpoints = {}
    openapi_schema = app.openapi()
    paths = openapi_schema["paths"]
    for path, methods in paths.items():
        description = methods[list(methods.keys())[0]].get("description", "")
        endpoints.update({path:description})
    return endpoints

@app.get("/api/permissions/all", summary="Get all permissions that can be assigned to roles")
def get_all_permissions(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    roles = roles_database.get_all_permissions()
    return roles
    


"""Control Types"""
# Define the /api/stop_server endpoint with OpenAPI documentation
@app.post("/api/stop_server/{port}", summary="Stop a game server instance")
async def stop_server(port: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="control"))):
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
async def start_server(port: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="control"))):
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
        await manager_event_bus.emit('start_game_servers', [game_server])
    else:
        await manager_event_bus.emit('start_game_servers', "all")
        # for game_server in game_servers.values():
        #     await manager_event_bus.emit('start_game_servers', [game_server])

@app.post("/api/add_servers/{num}", description="Add X number of game servers. Dynamically creates additional servers based on total allowed count.")
async def add_all_servers(num: int, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',to_add=num)

@app.post("/api/add_all_servers", description="Add total number of possible servers.")
async def add_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',to_add="all")

@app.post("/api/remove_servers/{num}", description="Remove X number of game servers. Dynamically removes servers idle servers.")
async def remove_servers(num: int, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',to_remove=num)

@app.post("/api/remove_all_servers", description="Remove all idle servers. Marks occupied servers as 'To be removed'.")
async def remove_all_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',to_remove="all")


@app.get("/api/get_filebeat_oauth_url") # unsure if this endpoint will ever be used.
async def get_filebeat_oauth_url(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    if 'spawned_filebeat_setup' in health_check_tasks:
        if not health_check_tasks['spawned_filebeat_setup'] or health_check_tasks['spawned_filebeat_setup'].done():
            return JSONResponse(status_code=200,content={"status":"filebeat setup task not currently running."})
    # if not get_filebeat_auth_url():
    #     return JSONResponse(status_code=404, content="No pending OAUTH url.")

    user = roles_database.get_user_by_discord_id(str(token_and_user_info['user_info']['id']))
    if user['nickname'] != 'owner':
        return JSONResponse(status_code=401,content={"status":"Only the server owner may process this command."})

    url = get_filebeat_auth_url()
    if url: return JSONResponse(status_code=200,content={"url":url})
    else:
        LOGGER.error("Filebeat setup task is running, but no OAUTH URL is available. Task should be complete, there is an issue worth reporting.")
        return JSONResponse(status_code=200,content={"status":"there is no OAUTH url available."})

# @app.post("/api/start_filebeat_setup_task")  # unsure if this endpoint will ever be used.
# async def start_filebeat_setup_task(token_and_user_info: dict = Depends(check_permission_factory(required_permission="superadmin"))):
#     if 'spawned_filebeat_setup' in health_check_tasks:
#         if health_check_tasks['spawned_filebeat_setup'] and not health_check_tasks['spawned_filebeat_setup'].done():
#             return JSONResponse(status_code=400,content={"status":"filebeat setup already running."})
    
#     if not await filebeat.check_filebeat_installed():
#         filebeat.install_filebeat()


""" End API Calls """

def create_self_signed_certificate(ssl_certfile, ssl_keyfile):
    # Generate a self-signed certificate with CN=localhost
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )

    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost")
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256(), default_backend())
    )

    # Write the key and certificate to the respective files
    with open(ssl_keyfile, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    with open(ssl_certfile, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def check_renew_self_signed_certificate(ssl_certfile, ssl_keyfile, days_before_expiration=30):
    # Check if the SSL certificate is going to expire within the specified number of days.
    # If it's going to expire, recreate the self-signed certificate.
    try:
        with open(ssl_certfile, "rb") as f:
            cert_pem = f.read()

        cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
        now = datetime.utcnow()
        time_remaining = cert.not_valid_after - now

        if time_remaining < timedelta(days=days_before_expiration):
            asyncio.run(create_self_signed_certificate(ssl_certfile, ssl_keyfile))
            LOGGER.info("Self-signed certificate has been renewed.")
        else:
            LOGGER.debug("Self-signed certificate is still valid. No renewal needed.")
    except Exception as e:
        LOGGER.error(f"Error checking certificate expiration: {e}")

def signal_handler(*_):
    stop_event.set()

def start_uvicorn(app, host, port, log_level, lifespan, use_colors, ssl_keyfile=None, ssl_certfile=None):
    if ssl_keyfile and ssl_certfile:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level,
            lifespan=lifespan,
            use_colors=use_colors,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile
        )
    else:
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level,
            lifespan=lifespan,
            use_colors=use_colors
        )

async def asgi_server(app, host, port):
    ssl_keyfile = HOME_PATH / "localhost.key"
    ssl_certfile = HOME_PATH / "localhost.crt"

    if not exists(ssl_certfile) or not exists(ssl_keyfile):
        create_self_signed_certificate(ssl_certfile, ssl_keyfile)
    else:
        check_renew_self_signed_certificate(ssl_certfile, ssl_keyfile)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        lifespan="on",
        use_colors=False,
        ssl_keyfile=ssl_keyfile if exists(ssl_keyfile) else None,
        ssl_certfile=ssl_certfile if exists(ssl_certfile) else None,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    try:
        server_pingable_resp_status, server_pingable_resp_text = await fetch_server_ping_response()
        if server_pingable_resp_status == 200:
            LOGGER.interest(f"\nRemote Management: https://management.honfigurator.app\nUse the following information to connect to your server.\n\tServer Name: {global_config['hon_data']['svr_name']}\n\tServer Address: {global_config['hon_data']['svr_ip']}")
        else:
            LOGGER.error(f"Server is not pingable over port {global_config['hon_data']['svr_api_port']}/tcp. Ensure that your firewall / router is configured to accept this traffic.")
        await stop_event.wait()
    finally:
        server.should_exit = True  # this flag tells Uvicorn to wrap up and exit
        LOGGER.info("Shutting down API Server")
        await server_task

async def fetch_server_ping_response():
    url = 'https://management.honfigurator.app:3001/api/ping'
    headers = {
        'Selected-Server': global_config['hon_data']['svr_ip'],
        'Selected-Port': str(global_config['hon_data']['svr_api_port'])
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, ssl=False) as response:
            response_text = await response.text()
            return response.status, response_text

async def start_api_server(config, game_servers_dict, game_manager_tasks, health_tasks, event_bus, find_replay_callback, host="0.0.0.0", port=5000):
    global global_config, game_servers, manager_event_bus, manager_tasks, health_check_tasks, manager_find_replay_callback, manager_check_game_stats_callback
    global_config = config
    game_servers = game_servers_dict
    manager_event_bus = event_bus
    manager_tasks = game_manager_tasks
    health_check_tasks = health_tasks
    manager_find_replay_callback = find_replay_callback

    # Create a new logger for uvicorn
    uvicorn_logger = logging.getLogger("uvicorn")

    # Set the handlers, log level, and propagation settings to match your existing logger
    uvicorn_logger.handlers = LOGGER.handlers.copy()
    uvicorn_logger.setLevel(logging.WARNING)
    uvicorn_logger.propagate = LOGGER.propagate

    LOGGER.interest(f"[*] HoNfigurator API - Listening on {host}:{port} (PUBLIC)")

    # loop = asyncio.get_running_loop()
    await asgi_server(app, host, port)