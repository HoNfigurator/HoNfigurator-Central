<img align="right" width="120" height="120" style="margin-top: -15px;margin-right:20px" src="https://i.ibb.co/YdSTNV9/Hon-Figurator-Icon1c.png">

# HoNfigurator Server Manager & API (early access)
This project operates as the game server manager for hon game server instances.

It negotiates TCP connections between game server instances and upstream HoN authentication services.

There is a rest API built in, to allow interaction from external services.

This guide provides steps for linking the configured HoNfigurator server to a front end management webui.

## Installation
<details>
<summary>Windows</summary>

1. Download the self-installer script
    - [All-in-One Installer](https://honfigurator.app/honfigurator-manager-installer.bat)
1. Copy the downloaded file ``honfigurator-manager-installer.bat`` to a location where HoNfigurator should be installed to, such as ``C:\Program Files``.
1. Run ``honfigurator-manager-installer.bat``
1. This should launch an installer like below:
	![image](https://user-images.githubusercontent.com/82205454/187016190-3192a4be-b35f-48ee-992e-819db303a778.png)  
	It may take some time to install Chocolatey.
1. When prompted, you may opt to install a clean HoN client.
	- Answer ``y/n`` to the prompt.
1. When the install is complete, HoNfigurator will open.
1. Enter the first run configuration values. Defaults are provided for guidance.

> **Note** HoN should automatically patch after opening for the first time. 
If there are any issues, [Contact me](https://discordapp.com/users/197967989964800000)

</details>

<details>
<summary>Linux (coming soon)</summary>
<installer here>
# Install Server <br>
1. curl https://eco.superbjorn.de/install-server.py | sudo python -<br>
2. Install Launcher (this repo)

</details>

## Remote Management - Web UI Front End
### Linking your server
> **Note** You require a discord account to use this service.
1. Browse to https://management.honfigurator.app
1. Log in with Discord
1. Select ``Add server to manage``
1. Provide the name, and address (DNS or IP) of your server.
1. Select OK
> **Warning** If it fails, please follow the steps in the warning message. 

#### Managing your server
Page Overview:
- Home
  - Central hub. View stats, skipped frame data.
- Server Status
  - See all configured server panels. Stop and Start commands.
- Server Control
  - Modify server configuration settings, add or remove servers from your server pool.
- Users & Roles
  - Manage allowed users. Delegate access or control to different people. Discord ID is mandatory for users you want to add.

This project is an early release, and the website is the bare minimum for functionality. Many more features will be added.
	
Please submit any feature requests, or issues, via the [Issues](https://github.com/frankthetank001/HoNfigurator-Central/issues) page for this repository.
