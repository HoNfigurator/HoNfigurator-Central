
from cogs.handlers.events import stop_event, get_logger
from cogs.misc.logger import get_logger, get_misc, get_roles_database
from cogs.handlers.events import GameStatus
from utilities.filebeat import main as filebeat_setup
import asyncio
import traceback
import os
import shutil
import re
import socket
from datetime import datetime

# Initialize loggers and miscellaneous utilities
LOGGER = get_logger()
MISC = get_misc()

class HealthCheckManager:
    """
    Manages health checks for game servers. This includes regular checks for game patches, server status,
    IP changes, and more. It schedules and manages various asynchronous tasks to monitor and maintain server health.
    """

    def __init__(self, game_servers, event_bus, callback_check_upstream_patch, 
             callback_resubmit_match_stats, callback_notify_discord_admin, 
             global_config, auto_ping_listener):
        self.game_servers = game_servers
        self.event_bus = event_bus
        self.check_upstream_patch = callback_check_upstream_patch
        self.resubmit_match_stats = callback_resubmit_match_stats
        self.notify_discord_admin = callback_notify_discord_admin
        self.global_config = global_config
        self.auto_ping_listener = auto_ping_listener  # Store a reference, not inside config
        self.patching = False
        self.tasks = {
            'hon_update_check': None,
            'honfigurator_update_check': None,
            'game_stats_resubmission': None,
            'public_ip_changed_check': None,
            'filebeat_verification': None,
            'spawned_filebeat_setup': None,
            'general_healthcheck': None,
            'disk_utilisation_healthcheck': None
        }

        get_roles_database().add_default_alerts_data()
    
    def schedule_task(self, coro, name, override=False):
        """
        Schedules an asynchronous task, with the option to override existing tasks.

        :param coro: Coroutine representing the task to be scheduled.
        :param name: Name of the task, used for tracking and logging.
        :param override: Boolean indicating whether to override an existing task of the same name.
        :return: The scheduled asyncio Task object.
        """
        existing_task = self.tasks.get(name)

        # Validate and manage the existing task
        if existing_task:
            if isinstance(existing_task, asyncio.Task):
                if existing_task.done():
                    if not existing_task.cancelled():
                        exception = existing_task.exception()
                        if exception:
                            LOGGER.error(f"The previous task '{name}' raised an exception: {exception}. We are scheduling a new one.")
                    else:
                        LOGGER.info(f"The previous task '{name}' was cancelled.")
                else:
                    if not override:
                        LOGGER.debug(f"Task '{name}' is still running, new task not scheduled.")
                        return existing_task
                    else:
                        try:
                            existing_task.cancel()
                        except Exception:
                            LOGGER.error(f"Failed to cancel existing task: {name}")
                            LOGGER.error(traceback.format_exc())
            else:
                LOGGER.error(f"Item '{name}' in tasks is not a Task object.")
                existing_task = None

        # Create and register the new task
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: setattr(t, 'end_time', datetime.now()))
        self.tasks[name] = task
        return task

    async def public_ip_healthcheck(self):
        """
        Periodically checks for changes in the public IP address. If a change is detected, it triggers a restart check.

        This method runs in a loop that can be interrupted by the 'stop_event'. It waits for a predefined interval and
        then checks for a change in the public IP address.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['public_ip_healthcheck']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            public_ip = await MISC.lookup_public_ip_async()
            if public_ip and public_ip != self.global_config['hon_data']['svr_ip']:
                self.global_config['hon_data']['svr_ip'] = public_ip
                await self.event_bus.emit('check_for_restart_required')

    async def general_healthcheck(self):
        """
        Performs a general health check on all game servers. This includes checking for idle or stuck servers,
        terminating orphan proxy processes, and other general maintenance tasks.

        This method runs in a loop that can be interrupted by the 'stop_event'. It checks each game server's status
        and performs necessary actions based on the server's condition.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['general_healthcheck']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)

            proxy_procs = []
            if MISC.get_os_platform() == "win32":
                # proxy process cleanup
                proxy_procs = MISC.get_proc("proxy.exe")

            for game_server in self.game_servers.values():
                if game_server._proxy_process:
                    # Capture the game_server._proxy_process in a local variable
                    server_proxy_process = game_server._proxy_process

                    # Create a new list without the game_server._proxy_process if it exists in the proxy_procs list
                    proxy_procs = [proc for proc in proxy_procs if proc != server_proxy_process]

                    # Perform the general health check for each game server
                    # Example: self.perform_health_check(game_server, HealthChecks.general_healthcheck)
                    pass

                status_value = game_server.get_dict_value('status')

                if status_value not in GameStatus._value2member_map_ and not game_server.client_connection and game_server._proc:
                    LOGGER.info(f"GameServer #{game_server.id} - Idle / stuck game server.")
                    await self.event_bus.emit('cmd_shutdown_server',game_server, disable=False, kill=True)
                

            for proc in proxy_procs:
                proc.terminate()
    
    async def disk_utilisation_healthcheck(self):
        """
        Checks for disk utilisation on the server. If the disk utilisation exceeds a certain threshold, it triggers a restart check.

        This method runs in a loop that can be interrupted by the 'stop_event'. It waits for a predefined interval and
        then checks the disk utilisation.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['disk_utilisation_healthcheck']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            # Retrieve the path from the global_config dictionary.
            path = self.global_config['hon_data']['hon_artefacts_directory']
            
            # Normalize the path to ensure compatibility across platforms
            normalized_path = os.path.abspath(path)
            
            # Check if the path exists to avoid errors
            if not os.path.exists(normalized_path):
                raise ValueError(f"The path {normalized_path} does not exist.")
            
            # On Unix-like systems, the root partition is a good default. On Windows, this will be empty.
            drive = os.path.splitdrive(normalized_path)[0] or '/'
            
            # For Unix-like systems, find the mount point
            if os.name == 'posix':
                while not os.path.ismount(drive):
                    drive = os.path.dirname(drive)
            
            # Use shutil.disk_usage to get disk usage statistics.
            total, used, free = shutil.disk_usage(drive)
            
            # Calculate the percentage of disk used.
            percent_used = round((used / total) * 100, 2)

            alert_activated = get_roles_database().update_disk_utilization_alerts(percent_used)
            if alert_activated:
                if await self.notify_discord_admin(type='disk_alert',disk_space=f"{str(percent_used)}%",severity=alert_activated['severity']):
                    get_roles_database().update_alert_with_notified(alert_activated['id'])

    async def lag_healthcheck(self):
        """
        Continuously checks for lag in each game server. This method can be expanded to implement specific lag detection logic.

        Runs in a loop that can be interrupted by the 'stop_event'. It waits for a predefined interval before 
        performing the next check.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['lag_healthcheck']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            for game_server in self.game_servers.values():
                # Perform the lag health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.lag_healthcheck)
                pass

    async def patch_version_healthcheck(self):
        """
        Regularly checks for new game patches. If a new patch is found, it triggers the patching process.

        Runs in a loop that can be interrupted by the 'stop_event'. Waits for a predefined interval before
        checking for new patches.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['check_for_hon_update']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            try:
                if await self.check_upstream_patch():
                    await self.event_bus.emit('patch_server',source='healthcheck')
            except Exception:
                print(traceback.format_exc())

                
    async def filebeat_verification(self):
        """
        Periodically verifies and sets up Filebeat for log file monitoring. Schedules a task for Filebeat setup.

        Runs in a loop that can be interrupted by the 'stop_event'. Waits for a predefined interval before
        performing the verification.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['filebeat_verification']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            try:
                # await filebeat_setup(self.global_config)
                self.schedule_task(filebeat_setup(self.global_config, from_main=False),'spawned_filebeat_setup', override=True)

            except Exception:
                LOGGER.error(traceback.format_exc())
    
    async def honfigurator_version_healthcheck(self):
        """
        Checks for updates to the 'honfigurator' component. If an update is available, it triggers the update process.

        Runs in a loop that can be interrupted by the 'stop_event'. Waits for a predefined interval before
        performing the check.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager']['check_for_honfigurator_update']):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            try:
                await self.event_bus.emit('update')
            except Exception:
                LOGGER.error(traceback.format_exc())

    async def autoping_listener_healthcheck(self):
        """
        Periodically checks if the AutoPing UDP listener is responsive.
        Uses the listener's built-in health check capability.
        """
        while not stop_event.is_set():
            for _ in range(self.global_config['application_data']['timers']['manager'].get('autoping_listener_healthcheck', 60)):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            
            try:
                if not self.auto_ping_listener:
                    LOGGER.warn("AutoPing listener object not found")
                    continue
                    
                if not self.auto_ping_listener.check_health():
                    LOGGER.warn("AutoPing listener health check failed, triggering restart...")
                    await self.event_bus.emit('restart_autoping_listener')
                else:
                    LOGGER.debug("AutoPing listener is healthy")
            except Exception as e:
                LOGGER.error(f"Error during AutoPing listener health check: {e}")
                LOGGER.error(traceback.format_exc())

    async def poll_for_game_stats(self):
        """
        Regularly polls the game statistics and processes them. Handles and resubmits match stats to the master server.

        Runs in a loop that can be interrupted by the 'stop_event'. Waits for a short interval before
        checking the game stats directory for new files.
        """
        while not stop_event.is_set():
            for _ in range(10):
                if stop_event.is_set():
                    return
                await asyncio.sleep(1)
            try:
                for file_name in os.listdir(self.global_config['hon_data']['hon_logs_directory']):
                    if file_name.endswith(".stats"):
                        match_id = re.search(r'([0-9]+)', file_name) # Extract match_id from file name (M<match_id>.stats)
                        match_id = match_id.group(0)
                        file_path = os.path.join(self.global_config['hon_data']['hon_logs_directory'], file_name)
                        # await self.event_bus.emit('resubmit_match_stats_to_masterserver',match_id, file_path)
                        if await self.resubmit_match_stats(match_id, file_path):
                            print(f"Removing {file_path}")
                            os.remove(file_path)  # Remove the .stats file after processing
            except Exception as e:
                LOGGER.error(f"Error while polling stats directory: {e}")
                traceback.print_exc()

    async def run_health_checks(self):
        """
        Schedules and manages the execution of all health check tasks. This method ensures that each health check
        is run periodically and handles any exceptions that occur during their execution.

        If a task encounters an exception, it is logged, and the task is rescheduled.
        """
        # Create tasks using schedule_task method
        self.tasks['hon_update_check'] = self.schedule_task(self.patch_version_healthcheck(), 'hon_update_check')
        self.tasks['honfigurator_update_check'] = self.schedule_task(self.honfigurator_version_healthcheck(), 'honfigurator_update_check')
        self.tasks['game_stats_resubmission'] = self.schedule_task(self.poll_for_game_stats(), 'game_stats_resubmission')
        self.tasks['public_ip_changed_check'] = self.schedule_task(self.public_ip_healthcheck(), 'public_ip_changed_check')
        self.tasks['filebeat_verification'] = self.schedule_task(self.filebeat_verification(), 'filebeat_verification')
        self.tasks['general_healthcheck'] = self.schedule_task(self.general_healthcheck(), 'general_healthcheck')
        self.tasks['disk_utilisation_healthcheck'] = self.schedule_task(self.disk_utilisation_healthcheck(), 'disk_utilisation_healthcheck')
        self.tasks['autoping_listener_healthcheck'] = self.schedule_task(self.autoping_listener_healthcheck(), 'autoping_listener_healthcheck')

        while not stop_event.is_set():
            for task_name, task in self.tasks.items():
                if task is None or task.done():
                    if task and task.exception():
                        exc = task.exception()
                        LOGGER.exception(f"An exception occurred in task '{task_name}': {exc}")
                        traceback.print_exception(type(exc), exc, exc.__traceback__)
                    
                    # Schedule task again
                    if task_name == 'hon_update_check':
                        self.tasks[task_name] = self.schedule_task(self.patch_version_healthcheck(), task_name)
                    elif task_name == 'honfigurator_update_check':
                        self.tasks[task_name] = self.schedule_task(self.honfigurator_version_healthcheck(), task_name)
                    elif task_name == 'game_stats_resubmission':
                        self.tasks[task_name] = self.schedule_task(self.poll_for_game_stats(), task_name)
                    elif task_name == 'public_ip_changed_check':
                        self.tasks[task_name] = self.schedule_task(self.public_ip_healthcheck(), task_name)
                    # elif task_name == 'filebeat_verification':
                        self.tasks[task_name] = self.schedule_task(self.filebeat_verification(), task_name)
                    elif task_name == 'general_healthcheck':
                        self.tasks[task_name] = self.schedule_task(self.general_healthcheck(), task_name)
                    elif task_name == 'disk_utilisation_healthcheck':
                        self.tasks[task_name] = self.schedule_task(self.disk_utilisation_healthcheck(), task_name)
                    elif task_name == 'autoping_listener_healthcheck':
                        self.tasks[task_name] = self.schedule_task(self.autoping_listener_healthcheck(), task_name)

            # Sleep for a bit before checking tasks again
            for _ in range(10):
                if stop_event.is_set():
                    LOGGER.info("Stopping HealthCheck Manager")
                    return
                await asyncio.sleep(1)