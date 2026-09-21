import inspect
import asyncio
from collections import defaultdict

class EventEmitter:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Any]]] = defaultdict(list)
 
    def subscribe(self, event_name: str, handler: Callable[..., Any]) -> None:
        """Register a handler (sync or async) for an event."""
        self._subscribers[event_name].append(handler)
 
    def unsubscribe(self, event_name: str, handler: Callable[..., Any]) -> None:
        self._subscribers[event_name].remove(handler)
 
    async def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Call every subscriber for event_name, passing args/kwargs.
 
        Async handlers are awaited concurrently; sync handlers run inline.
        """
        handlers = self._subscribers.get(event_name, [])
        if not handlers:
            return
 
        coros: list[Coroutine[Any, Any, Any]] = []
        for handler in handlers:
            if inspect.iscoroutinefunction(handler):
                coros.append(handler(*args, **kwargs))
            else:
                handler(*args, **kwargs)  # run sync handlers immediately
 
        if coros:
            await asyncio.gather(*coros)
 
    def emit_nowait(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        """Fire-and-forget version: schedules emit() as a background task."""
        asyncio.create_task(self.emit(event_name, *args, **kwargs))
