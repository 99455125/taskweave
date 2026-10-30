"""Local retained-resource fixture; no browser or external system."""
import asyncio
from taskweave.plugins.demo import DemoPlugin, Echo
from taskweave.plugins.registry import Registry
from taskweave.core.capability_contracts import CapabilitySpec


class CounterProvider:
    async def open(self, ctx, role): return {'count': 0}
    async def close(self, resource): pass


class Counter(Echo):
    spec = CapabilitySpec('demo.counter', 'Retained local counter', {'type': 'object'}, {'type': 'object'}, 'READ')

    async def execute(self, ctx, inputs):
        resource = await ctx.resources.acquire('demo.scene', 'main')
        resource['count'] += 1
        await asyncio.sleep(inputs.get('seconds', 0))
        return {'count': resource['count']}


class Plugin(DemoPlugin):
    def actions(self): return {**super().actions(), 'demo.counter': Counter()}
    def resource_providers(self): return {'demo.scene': CounterProvider()}


def build_registry(): return Registry([Plugin()])
