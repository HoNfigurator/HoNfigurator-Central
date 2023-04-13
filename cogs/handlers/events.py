import asyncio
from cogs.misc.logging import get_logger
from enum import Enum

LOGGER = get_logger()

stop_event = asyncio.Event()

class EventBus:
    def __init__(self):
        self._subscribers = {}
        self.tasks = []

    def subscribe(self, event_type, callback):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    async def emit(self, event_type, *args, **kwargs):
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        # await callback(*args, **kwargs)
                        task = asyncio.create_task(callback(*args, **kwargs))
                        self.tasks.append(task)
                        return task
                    else:
                        callback(*args, **kwargs)
                except Exception as e:
                    LOGGER.exception(f"An error occurred while emitting the event '{event_type}' and executing the callback '{callback.__name__}': {e}")
    
    async def get_tasks(self):
        return self.tasks

# Define an Enum class for health checks
class HealthChecks(Enum):
    public_ip_healthcheck = 1
    general_healthcheck = 2
    lag_healthcheck = 3
class ReplayStatus(Enum):
    NONE = -1
    GENERAL_FAILURE = 0
    DOES_NOT_EXIST = 1
    INVALID_HOST = 2
    ALREADY_UPLOADED = 3
    ALREADY_QUEUED = 4
    QUEUED = 5
    UPLOADING = 6
    UPLOAD_COMPLETE = 7

class GameStatus(Enum):
    SLEEPING = 0
    READY = 1
    OCCUPIED = 3 # in lobby / game
    STARTING = 4 # Starting (added by me)
    QUEUED = 5 # Queued for start (added by me)