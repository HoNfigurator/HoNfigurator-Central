
from cogs.misc.logger import get_home, get_logger, get_misc
import traceback, sys
import subprocess as sp

LOGGER = get_logger()
HOME_PATH = get_home()
pip_requirements = HOME_PATH / 'requirements.txt'

class PrepareDependencies:
    def __init__(self):
        pass
    def get_required_packages(self):
        try:
            with open(pip_requirements) as f:
                required_packages = f.read().splitlines()
            return required_packages
        except Exception:
            LOGGER.error(traceback.format_exc())
            return []

    def update_dependencies(self):
        try:
            required = self.get_required_packages()
            if len(required) == 0:
                LOGGER.warn("Unable to get contents of requirements.txt file")
                return False
            installed_packages = sp.run(['pip', 'freeze'], stdout=sp.PIPE, text=True)
            installed_packages_list = installed_packages.stdout.split('\n')
            missing = set(required) - set(installed_packages_list)
            python_path = sys.executable
            if missing:
                result = sp.run([python_path, '-m', 'pip', 'install', *missing])
                if result.returncode == 0:
                    LOGGER.info(f"SUCCESS, upgraded the following packages: {', '.join(missing)}")
                    return result
                else:
                    LOGGER.error(f"Error updating packages: {missing}\n error {result.stderr}")
                    return result
            else:
                LOGGER.info("Packages OK.")
                return True
        except Exception:
            LOGGER.exception(traceback.format_exc())
            return False
