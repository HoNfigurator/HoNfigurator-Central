from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import datetime
import pathlib
from fastapi import FastAPI, Request, Response, Body, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
import httpx
from fastapi.responses import JSONResponse
from typing import Any, Dict
import uvicorn
import asyncio
from cogs.misc.logger import get_logger, get_misc, get_home, get_setup
from cogs.misc.setup import SetupEnvironment
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
SETUP = get_setup()

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

def check_permission_factory(required_permission: str):
    async def check_permission(request: Request, token_and_user_info: dict = Depends(verify_token)):
        user_info = token_and_user_info["user_info"]

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
async def ping(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"status":"OK"}

"""Protected Endpoints"""

"""Config Types"""
class GlobalConfigResponse(BaseModel):
    global_config: Dict

@app.get("/api/get_global_config", description="Returns the global configuration of the manager")
async def get_global_config(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    return global_config

@app.post("/api/set_hon_data", description="Sets the 'hon_data' key within the global manager data dictionary")
async def set_hon_data(hon_data: dict = Body(...), token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    if SETUP.validate_hon_data(hon_data):
        global_config['hon_data'] = hon_data
        await manager_event_bus.emit('check_for_restart_required')

class TotalServersResponse(BaseModel):
    total_servers: int

@app.get("/api/get_total_servers", response_model=TotalServersResponse)
def get_total_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="monitor"))):
    return {"total_servers": global_config['hon_data']['svr_total']}

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
    return str(MISC.get_num_reserved_cpus())

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
        temp[game_server.config.get_local_by_key('svr_name')] = game_server.get_pretty_status()
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

@app.get("/api/users", summary="Get specified user with associated roles")
# def get_user(user: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
def get_user(user: str, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    users = roles_database.get_all_users()
    if user in users:
        return user
    raise HTTPException(status_code=404, detail="User not found")

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
        await manager_event_bus.emit('start_game_servers', game_server)
    else:
        for game_server in game_servers.values():
            await manager_event_bus.emit('start_game_servers', game_server)

@app.post("/api/add_servers/{num}", description="Add X number of game servers. Dynamically creates additional servers based on total allowed count.")
async def add_all_servers(num: int, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',add_servers=num)

@app.post("/api/add_all_servers", description="Add total number of possible servers.")
async def add_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',add_servers="all")

@app.post("/api/remove_servers/{num}", description="Remove X number of game servers. Dynamically removes servers idle servers.")
async def remove_servers(num: int, token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',remove_servers=num)

@app.post("/api/remove_all_servers", description="Remove all idle servers. Marks occupied servers as 'To be removed'.")
async def remove_all_servers(token_and_user_info: dict = Depends(check_permission_factory(required_permission="configure"))):
    await manager_event_bus.emit('balance_game_server_count',remove_servers="all")

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
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
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
        now = datetime.datetime.utcnow()
        time_remaining = cert.not_valid_after - now

        if time_remaining < datetime.timedelta(days=days_before_expiration):
            asyncio.run(create_self_signed_certificate(ssl_certfile, ssl_keyfile))
            print("Self-signed certificate has been renewed.")
        else:
            print("Self-signed certificate is still valid. No renewal needed.")
    except Exception as e:
        print(f"Error checking certificate expiration: {e}")


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

            if not exists(ssl_certfile) or not exists(ssl_keyfile):
                create_self_signed_certificate(ssl_certfile, ssl_keyfile)
            else:
                check_renew_self_signed_certificate(ssl_certfile, ssl_keyfile)

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
