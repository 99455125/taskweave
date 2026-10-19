"""Two legacy instrumentation hooks retained at the package import path.

Existing embedders/tests replace taskweave_playwright.async_playwright and
snapshot. Resolve only these hooks at call time; implementation modules otherwise
import their owners directly. Canonical implementations are safe fallbacks during
package initialization. This bridge can disappear when those hooks are retired.
"""
import sys
from playwright.async_api import async_playwright
from .locators import snapshot as page_snapshot


def runtime_factory():
    package = sys.modules.get(__package__)
    return getattr(package, 'async_playwright', async_playwright)()


async def snapshot(page, scope='runtime'):
    package = sys.modules.get(__package__)
    observe = getattr(package, 'snapshot', page_snapshot)
    return await observe(page, scope=scope)
