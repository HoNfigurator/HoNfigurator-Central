import subprocess
import os

def pause():
    input("Press any key to continue...")

def reset_and_pull_repository():
    print("Resetting repository...")
    subprocess.run(['git', 'reset', '--hard'])
    subprocess.run(['git', 'pull'])

def launch_honfigurator():
    os.startfile('honfigurator.exe')

def handle_git_pull_errors(stderr):
    error = False

    if "local changes" in stderr:
        print("Local changes detected in the repository.")
        user_response = input("Do you want to reset local changes and update the repository? (y/n): ").lower()

        if user_response == 'y':
            reset_and_pull_repository()
        else:
            print("Skipping the update. Please resolve the conflicts manually before running the application.")
            error = True
    elif "error" in stderr.lower():
        print("An error occurred while updating the repository:")
        print(stderr)
        print("Please resolve the issue manually before running the application.")
        error = True
    else:
        print("Repository updated successfully.")

    return error

def main():
    output = subprocess.run(['git', 'pull'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    error_occurred = False

    if output.stderr:
        error_occurred = handle_git_pull_errors(output.stderr)
    else:
        print("Repository updated successfully.")

    if not error_occurred:
        launch_honfigurator()
    else:
        pause()

if __name__ == "__main__":
    main()
