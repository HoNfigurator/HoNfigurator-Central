import logging.handlers
import logging
import os, sys
from prompt_toolkit.shortcuts import print_formatted_text


class PromptToolkitLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        print_formatted_text(msg)


# Get the path of the current script
def get_script_dir(file):
    return os.path.dirname(os.path.abspath(file))

def set_logger():
    global logger
    global HOME_PATH

    # Define the logging directory (in this case, a subdirectory called 'logs')
    log_dir = os.path.join(HOME_PATH, 'logs')

    # Create the logging directory if it doesn't already exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up logging to write to a file in the logging directory
    log_path = os.path.join(log_dir, 'server.log')

    # Set a maximum file size of 10MB for the log file
    max_file_size = 10 * 1024 * 1024  # 10MB in bytes
    file_handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=max_file_size, backupCount=5)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s'))
    # set a formatted on print statements
    pt_handler = PromptToolkitLogHandler()
    pt_handler.setLevel(logging.INFO)
    pt_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    # Create a logger with a specific name for this module
    logger = logging.getLogger("Server")
    logger.addHandler(file_handler)
    logger.addHandler(pt_handler)

    logger.setLevel(logging.DEBUG)
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
