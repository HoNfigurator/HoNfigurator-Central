import asyncio
import re
from cogs.misc.logger import get_logger, get_misc

LOGGER = get_logger()
MISC = get_misc()

async def extract_player_info(log_file_path, target_player_name=None):
    """
    Extract player names and IPs from the Slave log file.

    Parameters:
        log_file_path (str): The path to the log file.
        target_player_name (str): The name of the target player to find the IP. 
                                  If None, returns all players and IPs.

    Returns:
        list or str: A list of tuples containing player names and IPs if
                     target_player_name is None, else the IP of the target player.
    """
    # Regular expressions for extracting player names and IPs
    name_re = re.compile(r'Name: (.+)')
    ip_re = re.compile(r'IP: (.+)')
    
    try:
        # Open the file with UTF-16 LE encoding
        loop = asyncio.get_running_loop()
        with open(log_file_path, 'r', encoding='utf-16-le') as file:
            # Run the blocking file read operation in the default thread pool
            log_content = await loop.run_in_executor(None, file.read)
            
            # Find all names and IPs
            names = name_re.findall(log_content)
            ips = ip_re.findall(log_content)
            
            # Check if target_player_name is provided
            if target_player_name:
                # Pair names and IPs together and create a dictionary
                player_dict = dict(zip(names, ips))
                # Return the IP of the target player
                return player_dict.get(target_player_name, None)
            else:
                # Pair names and IPs together
                player_info = list(zip(names, ips))
                return player_info

    except FileNotFoundError:
        print(f"File not found: {log_file_path}")
    except PermissionError:
        print(f"Permission denied: {log_file_path}")
    except UnicodeDecodeError:
        print(f"Error decoding file: {log_file_path}")

    # Return an empty list or None if an exception is encountered
    return [] if target_player_name is None else None

    
async def find_match_id_post_launch(slave_id, log_path):
    """
    Find the latest match ID for the given slave

    Parameters:
        slave_id (int): The slave identifier.
        log_path (str): The log directory to search in.

    Returns:
        int: The latest match ID for the given slave
    """
    file_pattern = re.compile(rf'Slave{slave_id}_M(\d+)_console.clog')
    # Ensure the directory exists
    if not log_path.is_dir():
        LOGGER.warning(f"GameServer #{slave_id} - Directory {log_path} does not exist.")
        return
    
    # Get all matching files and their creation times
    files_and_times = [
        (f, f.stat().st_ctime)
        for f in log_path.glob(f'Slave{slave_id}_M*_console.clog')
    ]

    # If no files found, return None
    if not files_and_times:
        LOGGER.debug(f"GameServer #{slave_id} - No matching files found when looking for match ID.")
        return
    
    # Find the newest file
    newest_file = max(files_and_times, key=lambda x: x[1])[0]
    
    # Extract the Match ID
    match = file_pattern.match(newest_file.name)
    if match:
        match_id = match.group(1)  # Return the Match ID
        return match_id
    else:
        LOGGER.warning(f"GameServer #{slave_id} - Unexpected filename format: {newest_file.name}")
        return

async def find_game_info_post_launch(slave_id, file_path):
    """
    Find lobby information from the given match log file

    Parameters:
        slave_id (int): The slave identifier.
        file_path (str): The log file path.

    Returns:
        dict: Lobby information
    """
    loop = asyncio.get_running_loop()
    
    encoding = 'utf-16-le' if MISC.get_os_platform() == "win32" else 'utf-8'
    try:
        with open(file_path, 'r', encoding=encoding) as file:
            # Run the blocking file read operation in the default thread pool
            text = await loop.run_in_executor(None, file.read)
    except FileNotFoundError:
        LOGGER.warning(f"GameServer #{slave_id} - File not found: {file_path}")
        return
    except PermissionError:
        LOGGER.warning(f"GameServer #{slave_id} - Permission denied: {file_path}")
        return
    except UnicodeDecodeError:
        LOGGER.warning(f"GameServer #{slave_id} - Error decoding file: {file_path}")
        return
    
    # Regular expressions for extracting the necessary information
    match_name_re = re.compile(r'INFO_MATCH name:"([^"]+)"')
    map_name_re = re.compile(r'INFO_MAP name:"([^"]+)"')
    map_mode_re = re.compile(r'INFO_SETTINGS mode:"([^"]+)"')
    
    # Extract information using the regular expressions
    match_name = match_name_re.search(text)
    map_name = map_name_re.search(text)
    map_mode = map_mode_re.search(text)

    # Extracting the matched groups or None if not found
    info = {
        'map': match_name.group(1).lower() if match_name else None,
        'name': map_name.group(1).lower() if map_name else None,
        'mode': map_mode.group(1).replace('Mode_','').lower() if map_mode else None
    }
    return info