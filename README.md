<img align="right" width="120" height="120" style="margin-top: -15px;margin-right:20px" src="https://i.ibb.co/YdSTNV9/Hon-Figurator-Icon1c.png">

# HoNfigurator Server Manager & API (Beta)
This project operates as the game server manager for hon game server instances.

It negotiates TCP connections between game server instances and upstream HoN authentication services, much like the K2 Server Manager.

There is a restful API built in, to allow interaction from external services. Such as a pre-built remote management front end website.

This guide provides steps for linking the configured HoNfigurator server to a modern front end website where you can remotely manage and monitor one or more HoNfigurator instances.

## Authors
[FrankTheGodDamnMother**Tank](https://discordapp.com/users/197967989964800000)  
[Shindara](https://discordapp.com/users/291595808858439680)

## Requirements
1. You must have a registered [Project Kongor](https://kongor.online/) HoN account. **1 per server hosting**
1. You must be a member of the Project Kongor [Discord channel](https://discord.gg/kongor).
> **Note** This is how hosts are onboarded, and given the appropariate roles.
3. You must accept the risks of hosting game servers.
	- Your Public IP will be exposed to players connecting to your server.
	- Hosting private game servers could have legal issues as it requires server files not public to original HoN. They are not provided in this repository.
1. You must be willing to submit match logs to upstream services. These are logs of occurances during games played on your server.
	- We want to ensure that trends from games can be analysed in monitoring tools, and that a fair experienced is had by all players.
 	- How it works: [Monitoring](docs/monitoring.md)

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
<summary>Linux</summary>

1. Install: curl sudo screen (e.g. ``apt install curl sudo screen -y``)
2. ``curl https://kongor.superbjorn.de/scripts/las/installer.sh | sudo bash -``
3. HoNfigurator should clone into /opt/hon/honfigurator once the installer completes.
> **Warning** its strongly recommended to run the manager in screen  
3. Switch to your HoNfigurator-Central directory and execute ./main.py
	- ``cd /opt/hon/honfigurator``
	- ``python3 main.py``

- Building Pipeline (Installation):
  - &cross; CentOS 7 
  - &cross; Debian 10
  - &check; Debian 11
  - &check; Debian 12
  - &check; Ubuntu 22.04
  - &check; Ubuntu 22.10
  - &check; Ubuntu 23.04

- Tested Distributions (Verified running Gameservers)
  - &cross; CentOS 7
  - &cross; Debian 10
  - &check; Debian 11
  - &#x2610; Debian 12
  - &#x2610; Ubuntu 22.04
  - &#x2610; Ubuntu 22.10
  - &check; Ubuntu 23.04

</details>

## Remote Management - Web UI Front End
You must have finished installing your server before linking the website.

### Linking your server
> **Note** You require a discord account to use this service.
1. Browse to https://management.honfigurator.app
1. Log in with Discord
1. Select ``Add server to manage``
1. Provide the name, and address (DNS or IP) of your server.
	- This information is provided at server startup.
1. Select OK
> **Warning** If it fails, please follow the steps in the warning message. 

### Managing your server
Page Overview:
- Home
  - Central hub. View stats, skipped frame data.
- Server Status
  - See all configured server panels. Stop and Start commands.
- Server Control
  - Modify server configuration settings, add or remove servers from your server pool.
- Users & Roles
  - Manage allowed users. Delegate access or control to different people. Discord ID is mandatory for users you want to add.
- Troubleshooting
  - View HoNfigurator logs, and component health reports.

### Role Descriptions
| Role        | Stop/Start Servers | Configuration Changes | Add/Remove Approved Users | View Server Statistics |
|-------------|:------------------:|:---------------------:|:-------------------------:|:---------------------:|
| Superadmin  | :heavy_check_mark: | :heavy_check_mark:    | :heavy_check_mark:        | :heavy_check_mark:    |
| Admin       | :heavy_check_mark: |                       |                           | :heavy_check_mark:    |
| User        |                    |                       |                           | :heavy_check_mark:    |

> **Note** Only grant administrative roles to people that you trust.

> **Warning** Superadmins can view the hon username and password used to configure the server.  


## Final Notes	
Please submit any feature requests, or issues, via the [Issues](https://github.com/frankthetank001/HoNfigurator-Central/issues) page for this repository.  
Reach out and [Contact me](https://discordapp.com/users/197967989964800000) if there are any concerns, or ping me in the Project Kongor discord channel.  
The code is fully open source, so any improvements you want to make to the code, please submit a pull request and I will review.
