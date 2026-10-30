"""Local worker timing and process identity evidence for parallel tests."""
import asyncio
import os
import time
from taskweave.plugins.demo import DemoPlugin, Echo, TextPlugin
from taskweave.plugins.registry import Registry
from taskweave.core.capability_contracts import CapabilitySpec


class Timed(Echo):
    spec = CapabilitySpec("demo.timed", "Local timed action", {"type": "object"}, {"type": "object"}, "READ")

    async def execute(self, ctx, inputs):
        started = time.monotonic()
        await asyncio.sleep(inputs.get("seconds", 0))
        return {"started": started, "finished": time.monotonic(), "pid": os.getpid()}


class ParallelDemo(DemoPlugin):
    def actions(self):
        return {**super().actions(), "demo.timed": Timed()}


def build_registry():
    return Registry([ParallelDemo(), TextPlugin()])
