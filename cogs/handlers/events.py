import asyncio
from cogs.misc.logging import get_logger

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
                    else:
                        callback(*args, **kwargs)
                except Exception as e:
                    LOGGER.exception(f"An error occurred while emitting the event '{event_type}' and executing the callback '{callback.__name__}': {e}")
        return task
    
    async def get_tasks(self):
        return self.tasks