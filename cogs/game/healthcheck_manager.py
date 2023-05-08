
from cogs.handlers.events import stop_event, get_logger
from cogs.misc.logger import get_logger, get_misc
from cogs.misc.exceptions import HoNPatchError
import asyncio
import traceback
import os
import re

LOGGER = get_logger()
MISC = get_misc()

class HealthCheckManager:
    def __init__(self, game_servers, event_bus, callback_check_upstream_patch, global_config):
        self.game_servers = game_servers
        self.event_bus = event_bus
        self.check_upstream_patch = callback_check_upstream_patch
        self.global_config = global_config
        self.patching = False

    async def public_ip_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the public IP health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.public_ip_healthcheck)
                pass
            await asyncio.sleep(30)

    async def general_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the general health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.general_healthcheck)
                pass
            await asyncio.sleep(60)

    async def lag_healthcheck(self):
        while not stop_event.is_set():
            for game_server in self.game_servers.values():
                # Perform the lag health check for each game server
                # Example: self.perform_health_check(game_server, HealthChecks.lag_healthcheck)
                pass
            await asyncio.sleep(120)

    async def patch_version_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(10)
            try:
                if not MISC.get_os_platform() == "win32": # TODO: not checking patch on linux yet
                    return
                if await self.check_upstream_patch():
                    await self.event_bus.emit('patch_server',source='healthcheck')
            except Exception:
                print(traceback.format_exc())
    
    async def honfigurator_version_healthcheck(self):
        while not stop_event.is_set():
            await asyncio.sleep(120)
            try:
                await self.event_bus.emit('update')
            except Exception:
                LOGGER.error(traceback.format_exc())
    
    async def poll_for_game_stats(self):
        while not stop_event.is_set():
            await asyncio.sleep(20)
            try:
                for file_name in os.listdir(self.global_config['hon_data']['hon_logs_directory']):
                    if file_name.endswith(".stats"):
                        match_id = re.search(r'([0-9]+)', file_name) # Extract match_id from file name (M<match_id>.stats)
                        match_id = match_id.group(0)
                        file_path = os.path.join(self.global_config['hon_data']['hon_logs_directory'], file_name)
                        await self.event_bus.emit('resubmit_match_stats_to_masterserver',match_id, file_path)
                        print("removing now..")
                        # os.remove(file_path)  # Remove the .stats file after processing
            except Exception as e:
                LOGGER.error(f"Error while polling stats directory: {e}")
                traceback.print_exc()

    async def run_health_checks(self):
        """
            Schedule and run healthchecks defined in this class.

            If health check functions are not wrapped in try
        """
        stop_task = asyncio.create_task(stop_event.wait())
        # TODO: implement the poll_for_game_stats function below, once upstream accepts our format.
        done, pending = await asyncio.wait(
            [self.public_ip_healthcheck(), self.general_healthcheck(), self.lag_healthcheck(), self.patch_version_healthcheck(), self.honfigurator_version_healthcheck(), stop_task],
            return_when=asyncio.FIRST_COMPLETED
        )

        # Check for uncaught exceptions in the done tasks
        for task in done:
            exc = task.exception()
            if exc:
                LOGGER.exception(f"An exception occurred in a health check task: {exc}")
                traceback.print_exception(type(exc), exc, exc.__traceback__)

        # Cancel the pending tasks
        for task in pending:
            task.cancel()
