import logging.handlers
import logging
import os
import logging.config
import json
from prompt_toolkit.shortcuts import print_formatted_text


class CustomLogger(logging.Logger):
    def interest(self, message, *args, **kws):
        if self.isEnabledFor(25):
            self._log(25, message, args, **kws)
    def highlight(self, message, *args, **kws):
        if self.isEnabledFor(26):
            self._log(26, message, args, **kws)

# Set the logger class to our custom logger
logging.setLoggerClass(CustomLogger)

# Add the 'INTEREST' level name (with a level of 25)
logging.addLevelName(25, "INTEREST")
# Add the 'HIGHLIGHT' level name (with a level of 26)
logging.addLevelName(26, "HIGHLIGHT")

class FileFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        super().__init__("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s", *args, **kwargs)

    def format(self, record):
        if record.levelno in [25,26]:
            record.levelname = "INFO"
        return super().format(record)

class ColorFormatter(FileFormatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    green = "\x1b[32;20m"
    purple = "\x1b[35;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(levelname)s - %(message)s (%(filename)s)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        25: green + format + reset,  # 'INTEREST' level
        26: purple + format + reset, # 'HIGHLIGHT' level
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
        logging.FATAL: bold_red + format + reset
    }

    def formatException(self, exc_info):
        """Format the exception to be colored"""
        return self.red + super().formatException(exc_info) + self.reset

    def format(self, record):
        """Format the record to include the colored exception"""
        # Change level name before formatting
        if record.levelno in [25,26]:
            record.levelname = "INFO"
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

    
class PromptToolkitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        print_formatted_text(msg)

FILEBEAT_AUTH_TOKEN = None
FILEBEAT_AUTH_URL = None

# Get the path of the current script
def get_script_dir(file):
    return os.path.dirname(os.path.abspath(file))

logger = logging.getLogger('Server')

def set_filebeat_auth_token(token):
    global FILEBEAT_AUTH_TOKEN
    FILEBEAT_AUTH_TOKEN = token

def get_filebeat_auth_token():
    return FILEBEAT_AUTH_TOKEN

def set_filebeat_auth_url(url):
    global FILEBEAT_AUTH_URL
    logger.info("Setting oauth url")
    FILEBEAT_AUTH_URL = url

def get_filebeat_auth_url():
    logger.info("Unsetting oauth url")
    return FILEBEAT_AUTH_URL

def set_logger():
    global HOME_PATH

    # Define the logging directory (in this case, a subdirectory called 'logs')
    log_dir = os.path.join(HOME_PATH, 'logs')
    log_file = os.path.join(log_dir, 'server.log')

    # Create the logging directory if it doesn't already exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Load the logging configuration from file
    config_path = str(HOME_PATH / 'config' / 'logging.json')

    #file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)

    # Replace the {LOG_DIR} placeholder with the absolute path of the log directory
    if os.path.exists(config_path):
        with open(config_path, 'rt') as f:
            config = json.load(f)
        config['handlers']['file']['filename'] = log_file
        logging.config.dictConfig(config)
        logger = logging.getLogger('Server')
        # Set appropriate formatters for each handler
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.name == 'console':
                handler.setFormatter(ColorFormatter())
            elif isinstance(handler, logging.FileHandler):
                handler.setFormatter(FileFormatter())

    else:
        # If the config file doesn't exist, set up logging manually
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(FileFormatter())
        file_handler.setLevel(logging.INFO)

        pt_handler = PromptToolkitLogHandler()
        pt_handler.setFormatter(ColorFormatter())
        pt_handler.setLevel(logging.INFO)
        
        logger = logging.getLogger('Server')

        logger.addHandler(file_handler)
        logger.addHandler(pt_handler)

        logger.propagate = False


def get_logger():
    global logger
    return logger

def set_misc(misc_object):
    global MISC
    MISC = misc_object

def get_misc():
    global MISC
    return MISC

def set_setup(setup_object):
    global SETUP
    SETUP = setup_object

def get_setup():
    global SETUP
    return SETUP

def set_home(script_home):
    global HOME_PATH
    HOME_PATH = script_home

def get_home():
    global HOME_PATH
    return HOME_PATH

def get_filebeat_status():
    return FILEBEAT_STATUS

def set_filebeat_status(status):
    global FILEBEAT_STATUS
    FILEBEAT_STATUS = status

def flatten_dict(d, parent_key='', sep=' '):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
