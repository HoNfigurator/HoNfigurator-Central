import subprocess as sp
import sys
import traceback

class PrepareDependencies:
    def __init__(self, home_path):
        self.script_home = home_path
        self.python_version = sys.version_info[:2]
        if self.python_version == (3, 9):
            self.pip_requirements = home_path / "py3.9" / "requirements.txt"
        if self.python_version == (3, 10):
            self.pip_requirements = home_path / "py3.10" / "requirements.txt"
        elif self.python_version == (3, 11):
            self.pip_requirements = home_path / "py3.11" / "requirements.txt"
        else:
            raise RuntimeError(f"Unsupported Python version: {sys.version}")

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
                result = sp.run([python_path, '-m', 'pip', 'install', *missing, '--break-system-packages'])
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
