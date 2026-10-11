"""Async generators a loop body leaves early are closed by the loop, under qasync.

asyncio's run_forever installs the hooks; qasync's does not.  roomkit leaves
an STT stream with ``break`` to drop an echo: closed by the garbage collector
instead, the stream's ``finally`` could not await, "async generator ignored
GeneratorExit" was printed, and its websocket and audio task stayed open.
"""

import asyncio
import gc
import sys

import qasync

from roomkit_ui.app import install_asyncgen_hooks


def test_a_stream_left_with_break_runs_its_finally_on_the_qasync_loop(qapp):
    loop = qasync.QEventLoop(qapp)
    previous = sys.get_asyncgen_hooks()
    closed: list[bool] = []

    async def stream():
        try:
            for i in range(10):
                yield i
                await asyncio.sleep(0)
        finally:
            await asyncio.sleep(0.01)  # a websocket's close
            closed.append(True)

    async def main():
        async for item in stream():
            if item == 2:
                break  # what roomkit's continuous STT loop does
        gc.collect()
        await asyncio.sleep(0.1)

    try:
        install_asyncgen_hooks(loop)
        loop.run_until_complete(main())
    finally:
        sys.set_asyncgen_hooks(*previous)
        loop.close()
        asyncio.set_event_loop(None)

    assert closed == [True]
