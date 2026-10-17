import json
import asyncio
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from synctohdd.engine.manager import sync_manager
from synctohdd.utils.logger import logger

router = APIRouter(prefix="/api/events", tags=["Live Events"])

@router.get("")
async def sse_events(request: Request):
    """Server-Sent Events stream for live sync progress."""
    queue = sync_manager.subscribe()

    async def event_generator():
        try:
            # Yield initial status immediately
            status = sync_manager.get_status()
            yield {
                "event": "status",
                "data": json.dumps(status),
            }

            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {
                        "event": "progress",
                        "data": json.dumps(event.__dict__),
                    }
                except asyncio.TimeoutError:
                    # Send keepalive ping to maintain connection
                    yield {
                        "event": "ping",
                        "data": "{}",
                    }
        except asyncio.CancelledError:
            pass
        finally:
            sync_manager.unsubscribe(queue)

    return EventSourceResponse(event_generator())
