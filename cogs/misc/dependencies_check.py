import subprocess as sp
import sys
import traceback

class PrepareDependencies:
    def __init__(self, home_path):
        self.script_home = home_path
        self.python_version = sys.version_info[:2]
        if self.python_version[0] != 3:
            raise RuntimeError(f"Unsupported Python version: {sys.version}")
        elif self.python_version[1] < 9:
            raise RuntimeError(f"Python version too old: {sys.version}")
        elif self.python_version[1] > 11:
            raise RuntimeError(f"Python version too new: {sys.version}")
        else:
            minor_version = self.python_version[1]
            self.pip_requirements = home_path / f"py3.{minor_version}" / "requirements.txt"

    def get_required_packages(self):
        try:
            with open(self.pip_requirements) as f:
                required_packages = f.read().splitlines()
            return required_packages
        except Exception as e:
            print(f"Error reading requirements file: {e}")
            return []

    def format_package_version(self, package):
        return f"{package.project_name}=={package.version}"

    def update_dependencies(self):
        try:
            required = self.get_required_packages()
            required = [pkg.replace('-', '_') for pkg in required]
            if len(required) == 0:
                print("Unable to get contents of requirements.txt file")
                return False

            installed_packages = sp.run(['pip', 'freeze'], stdout=sp.PIPE, text=True)
            installed_packages_list = installed_packages.stdout.split('\n')

            # Replace dashes with underscores in installed package names
            installed_packages_list = [pkg.replace('-', '_') for pkg in installed_packages_list]

            missing = set(required) - set(installed_packages_list)
            python_path = sys.executable
            if missing:
                if self.python_version == (3, 11):
                    result = sp.run([python_path, '-m', 'pip', 'install', *missing, '--break-system-packages'])
                else:
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
