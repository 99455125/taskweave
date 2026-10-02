"""Observe a single protocol reply even when its caller stops waiting."""
import asyncio

_pending = set()


async def reply(awaitable):
    # Playwright's Python cancellation does not cancel the browser command.
    # Cancelling its Channel waiter abandons the eventual protocol Future.
    # Keep only this already-issued call alive, never the rest of an action.
    caller = asyncio.current_task()
    cancellations = caller.cancelling()

    async def issue():
        # A cancellation already queued before this task starts must not issue
        # a new command merely because the waiter has been shielded.
        if caller.cancelled() or caller.cancelling() > cancellations:
            awaitable.close()
            raise asyncio.CancelledError
        return await awaitable

    pending = asyncio.create_task(issue())
    _pending.add(pending)

    def observed(done):
        _pending.discard(done)
        if not done.cancelled():
            done.exception()

    pending.add_done_callback(observed)
    return await asyncio.shield(pending)
