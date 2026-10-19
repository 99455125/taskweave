"""Native and browser platform effects for desktop adapters only."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from taskweave.core.validation import TaskError


async def copy_text(text: str, *, native: bool = False):
    if native and sys.platform == 'darwin':
        try:
            await asyncio.to_thread(subprocess.run, ['pbcopy'], input=text.encode('utf-8'), check=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TaskError('CLIPBOARD_FAILED', '复制失败，请在文本框中全选复制') from exc
        return
    from nicegui import ui
    success = await ui.run_javascript("""return await (async () => {
        const text = TEXT;
        try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
        const input = document.createElement('textarea');
        input.value = text; input.style.position = 'fixed'; input.style.opacity = '0';
        document.body.appendChild(input); input.focus(); input.select();
        try { return document.execCommand('copy'); } finally { input.remove(); }
    })();""".replace('TEXT', json.dumps(text)), timeout=10)
    if not success:
        raise TaskError('CLIPBOARD_FAILED', '复制失败，请在文本框中全选复制')


async def open_path(path, *, workspace_home: Path):
    path = Path(path).resolve()
    if not path.is_relative_to(Path(workspace_home).resolve()) or not path.exists():
        raise TaskError("LOCAL_PATH_INVALID")

    def launch():
        if sys.platform == "win32":
            os.startfile(str(path))
        else:
            subprocess.Popen(
                ["open" if sys.platform == "darwin" else "xdg-open", str(path)]
            )

    await asyncio.to_thread(launch)
