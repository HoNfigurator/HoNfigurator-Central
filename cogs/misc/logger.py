import logging.handlers
import logging
import os
import logging.config
import json
from prompt_toolkit.shortcuts import print_formatted_text


class PromptToolkitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        print_formatted_text(msg)


# Get the path of the current script
def get_script_dir(file):
    return os.path.dirname(os.path.abspath(file))

logger = logging.getLogger('Server')

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

    else:
        # If the config file doesn't exist, set up logging manually
        file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'))
        file_handler.setLevel(logging.INFO)

        pt_handler = PromptToolkitLogHandler()
        pt_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        pt_handler.setLevel(logging.INFO)

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

def flatten_dict(d, parent_key='', sep=' '):
    items = []
    for k, v in d.items():
        new_key = parent_key + sep + k if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)
