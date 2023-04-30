
# from cogs.misc.logger import get_home, get_logger
import traceback, sys
import subprocess as sp

class PrepareDependencies:
    def __init__(self, home_path):
        self.script_home = home_path
        self.pip_requirements = home_path / 'requirements.txt'
    def get_required_packages(self):
        try:
            with open(self.pip_requirements) as f:
                required_packages = f.read().splitlines()
            return required_packages
        except Exception:
            print(traceback.format_exc())
            return []

    def update_dependencies(self):
        try:
            required = self.get_required_packages()
            if len(required) == 0:
                print("Unable to get contents of requirements.txt file")
                return False
            installed_packages = sp.run(['pip', 'freeze'], stdout=sp.PIPE, text=True)
            installed_packages_list = installed_packages.stdout.split('\n')
            missing = set(required) - set(installed_packages_list)
            python_path = sys.executable
            if missing:
                result = sp.run([python_path, '-m', 'pip', 'install', *missing])
                if result.returncode == 0:
                    print(f"SUCCESS, upgraded the following packages: {', '.join(missing)}")
                    return result
                else:
                    print(f"Error updating packages: {missing}\n error {result.stderr}")
                    return result
            else:
                print("Packages OK.")
                return True
        except Exception:
            print(traceback.format_exc())
            return False
