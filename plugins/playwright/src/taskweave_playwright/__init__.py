"""Public API and legacy import paths for the Playwright plugin.

The entry point and pre-split class names remain importable, including pickle
GLOBAL references created before the implementation acquired dedicated modules.
"""

from .schemas import schema, STRING, NULL, LOCATOR, INSPECT_PARAMETERS
from .session import BrowserSession, page_for, _live_context_targets
from .locators import locate, target_state, snapshot
from .browser_actions import BrowserAction, ReadTool
from .results import FileResult
from .plugin import PlaywrightPlugin

# Legacy runtime instrumentation hook; consumed by _compat.runtime_factory.
from playwright.async_api import async_playwright
