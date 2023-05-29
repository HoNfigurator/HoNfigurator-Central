
from cogs.handlers.events import stop_event, get_logger
from cogs.misc.logger import get_logger, get_misc
from cogs.misc.exceptions import HoNPatchError
import asyncio
import traceback
import os
import re
from datetime import datetime

LOGGER = get_logger()
MISC = get_misc()

class HealthCheckManager:
    def __init__(self, game_servers, event_bus, callback_check_upstream_patch, callback_resubmit_match_stats, global_config):
        self.game_servers = game_servers
        self.event_bus = event_bus
        self.check_upstream_patch = callback_check_upstream_patch
        self.resubmit_match_stats = callback_resubmit_match_stats
        self.global_config = global_config
        self.patching = False
        self.tasks = {
            'hon_update_check': None,
            'honfigurator_update_check': None,
            'game_stats_resubmission': None,

        }
    
    def schedule_task(self, coro, name, override = False):
        existing_task = self.tasks.get(name)  # Get existing task if any

        if existing_task is not None:
            if not isinstance(existing_task, asyncio.Task):
                LOGGER.error(f"Item '{name}' in tasks is not a Task object.")
                # Choose one of the following lines, depending on your requirements:
                # raise ValueError(f"Item '{name}' in tasks is not a Task object.")  # Option 1: raise an error
                existing_task = None  # Option 2: ignore the non-Task item and overwrite it later

        if existing_task:
            if existing_task.done():
                if not existing_task.cancelled():
                    # If the task has finished and was not cancelled, retrieve any possible exception to avoid 'unretrieved exception' warnings
                    exception = existing_task.exception()
                    if exception:
                        LOGGER.error(f"The previous task '{name}' raised an exception: {exception}. We are scheduling a new one.")
                else:
                    LOGGER.info(f"The previous task '{name}' was cancelled.")
            else:
                if not override:
                    # Task is still running
                    LOGGER.warning(f"Task '{name}' is still running, new task not scheduled.")
                    return existing_task  # Return existing task

        # Create and register the new task
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: setattr(t, 'end_time', datetime.now()))
        self.tasks[name] = task
        return task

    async def public_ip_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['manager']['public_ip_healthcheck'])
            for game_server in self.game_servers.values():
                # Perform the public IP health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.public_ip_healthcheck)
                pass

    async def general_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['manager']['general_healthcheck'])
            for game_server in self.game_servers.values():
                # Perform the general health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.general_healthcheck)
                pass

    async def lag_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['manager']['lag_healthcheck'])
            for game_server in self.game_servers.values():
                # Perform the lag health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.lag_healthcheck)
                pass

    async def patch_version_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['manager']['check_for_hon_update'])
            try:
                if not MISC.get_os_platform() == "win32": # TODO: not checking patch on linux yet
                    return
                if await self.check_upstream_patch():
                    await self.event_bus.emit('patch_server',source='healthcheck')
            except Exception:
                print(traceback.format_exc())
    
    async def honfigurator_version_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['manager']['check_for_honfigurator_update'])
            try:
                await self.event_bus.emit('update')
            except Exception:
                LOGGER.error(traceback.format_exc())
    
    async def poll_for_game_stats(self):
        while not stop_event.is_set():
            await asyncio.sleep(10)
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
    
    async def remove_old_proxy_processes(self):
        while not stop_event.is_set():
            await asyncio.sleep(self.global_config['application_data']['timers']['general_healthcheck'])

    async def run_health_checks(self):
        """
            Schedule and run healthchecks defined in this class.

            If health check functions are not wrapped in try
        """
        # Create tasks using schedule_task method
        self.tasks['hon_update_check'] = self.schedule_task(self.patch_version_healthcheck(), 'hon_update_check')
        self.tasks['honfigurator_update_check'] = self.schedule_task(self.honfigurator_version_healthcheck(), 'honfigurator_update_check')

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

            # Sleep for a bit before checking tasks again
            await asyncio.sleep(10)
