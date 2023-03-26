
import logging
import logging.handlers
import os, sys

# Get the path of the current script
def get_script_dir(file):
    return os.path.dirname(os.path.abspath(file))

script_dir = get_script_dir(__file__)

# Define the logging directory (in this case, a subdirectory called 'logs')
log_dir = os.path.join(script_dir, '..', 'logs')

# Create the logging directory if it doesn't already exist
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

# Set up logging to write to a file in the logging directory
log_path = os.path.join(log_dir, 'server.log')

# Set a maximum file size of 10MB for the log file
max_file_size = 10 * 1024 * 1024  # 10MB in bytes
file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=max_file_size, backupCount=5)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'))

# Create a logger with a specific name for this module
logger = logging.getLogger("Server")
logger.addHandler(file_handler)

# Create a stream handler for outputting logs to the console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

logger.setLevel(logging.DEBUG)
logger.propagate = False

def my_print(*args, **kwargs):
    msg = ' '.join(map(str, args))
    #logger.info(msg)
    #logger.debug(">")  # Add '>' to log file/console
    print(msg, **kwargs)
    print(">", end=" ", flush=True)

def flatten_dict(d, parent_key='', sep='_'):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)