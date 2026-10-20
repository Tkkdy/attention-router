# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Keep cancellation from abandoning a still-running synchronous operation."""
import asyncio


async def run_worker(function, *args):
    worker = asyncio.create_task(asyncio.to_thread(function, *args))
    cancelled = False
    while not worker.done():
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Python cannot stop the thread. Drain it before releasing caller locks
            # or completing shutdown; repeated cancellation must not bypass this.
            cancelled = True
        except Exception:
            if not cancelled:
                raise
            break
    if cancelled:
        if not worker.cancelled():
            worker.exception()  # Consume a failure during cancellation.
        raise asyncio.CancelledError
    return worker.result()
