"""Bounded uploads and scoped native-dialog handling owned by one browser action."""
import asyncio
import base64
import binascii

from playwright.async_api import Error
from taskweave.plugins.sdk import PluginError
from .protocol import reply


SPECIAL_WRITES = {'page_upload', 'page_dialog'}
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * MAX_FILE_BYTES
MAX_BASE64 = 4 * ((MAX_FILE_BYTES + 2) // 3)
KEYS = ['Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp', 'Space']


def entries(schema, locator):
    file = {'type': 'object', 'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 255, 'pattern': r'^[^/\\\x00-\x1f]+$'},
        'mime_type': {'type': 'string', 'minLength': 3, 'maxLength': 128, 'pattern': r'^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$'},
        'content_base64': {'type': 'string', 'maxLength': MAX_BASE64}},
        'required': ['name', 'mime_type', 'content_base64'], 'additionalProperties': False}
    file_info = {'type': 'object', 'properties': {'name': {'type': 'string'}, 'mime_type': {'type': 'string'},
        'size_bytes': {'type': 'integer', 'minimum': 0, 'maximum': MAX_FILE_BYTES}},
        'required': ['name', 'mime_type', 'size_bytes'], 'additionalProperties': False}
    upload = ('page_upload', 'Set or clear files using explicit Base64 contents, not host paths; max 10 files, 1MiB each/8MiB total; input or triggered chooser mode',
        schema({'selector': locator, 'mode': {'enum': ['input', 'chooser']},
            'files': {'type': 'array', 'maxItems': 10, 'items': file}}, ['selector', 'files']),
        {'type': 'object', 'properties': {'files': {'type': 'array', 'items': file_info},
            'total_bytes': {'type': 'integer', 'minimum': 0, 'maximum': MAX_TOTAL_BYTES}},
            'required': ['files', 'total_bytes'], 'additionalProperties': False}, 'WRITE')
    expected = {'type': 'object', 'properties': {
        'type': {'enum': ['alert', 'confirm', 'prompt', 'beforeunload']},
        'message': {'type': 'string', 'maxLength': 4096},
        'response': {'enum': ['accept', 'dismiss']},
        'prompt_text': {'type': 'string', 'maxLength': 4096}},
        'required': ['type', 'message', 'response'], 'additionalProperties': False}
    dialog = ('page_dialog', 'Before an observed click/double-click/press install a bounded dialog sequence handler; match exact type/message; dismiss mismatches; always release handlers',
        schema({'selector': locator, 'trigger': {'enum': ['click', 'double_click', 'press']},
            'key': {'enum': KEYS}, 'dialogs': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'items': expected}}, ['selector', 'dialogs']),
        {'type': 'object', 'properties': {'handled': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'type': {'enum': ['alert', 'confirm', 'prompt', 'beforeunload']}, 'response': {'enum': ['accept', 'dismiss']}},
            'required': ['type', 'response'], 'additionalProperties': False}}, 'completed': {'const': True}},
            'required': ['handled', 'completed'], 'additionalProperties': False}, 'WRITE')
    return [upload, dialog]


def upload_files(files):
    """Validate the complete batch before opening a chooser or changing an input."""
    prepared, information, total = [], [], 0
    for file in files:
        if file['name'] in {'.', '..'} or '/' in file['name'] or '\\' in file['name']:
            raise PluginError('UPLOAD_FILE_INVALID', 'Upload name must be a filename, never a local path')
        encoded = file['content_base64']
        if len(encoded) > MAX_BASE64:
            raise PluginError('UPLOAD_TOO_LARGE', 'Uploaded file exceeds 1MiB')
        try:
            buffer = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PluginError('UPLOAD_FILE_INVALID', 'Upload content must be complete standard Base64') from exc
        total += len(buffer)
        if len(buffer) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise PluginError('UPLOAD_TOO_LARGE', 'Upload limit is 1MiB per file and 8MiB per batch')
        prepared.append({'name': file['name'], 'mimeType': file['mime_type'], 'buffer': buffer})
        information.append({'name': file['name'], 'mime_type': file['mime_type'], 'size_bytes': len(buffer)})
    return prepared, {'files': information, 'total_bytes': total}


async def upload(page, inputs, locate):
    files, result = upload_files(inputs['files'])
    control = locate(page, inputs['selector'])
    timeout = inputs.get('timeout_ms', 10000)
    async with asyncio.timeout(timeout / 1000):
        if inputs.get('mode', 'input') == 'chooser':
            chosen = asyncio.get_running_loop().create_future()
            choosers = []
            def receive(chooser):
                choosers.append(chooser)
                if not chosen.done():
                    chosen.set_result(chooser)
            page.on('filechooser', receive)
            try:
                await reply(control.click(timeout=timeout))
                chooser = await chosen
                # The click reply and chooser events can be dispatched in
                # separate protocol callbacks. A renderer round trip fences
                # the synchronous trigger without a timing-based sleep.
                await reply(page.evaluate('()=>true'))
                if len(choosers) != 1:
                    raise PluginError('UPLOAD_CHOOSER_AMBIGUOUS', 'Trigger opened multiple file inputs; use an explicit input selector')
                if len(files) > 1 and not chooser.is_multiple():
                    raise PluginError('UPLOAD_MULTIPLE_UNSUPPORTED', 'File chooser accepts only one file')
                if await reply(chooser.element.is_disabled()):
                    raise PluginError('LOCATOR_DISABLED', 'File chooser input is disabled')
                await reply(chooser.set_files(files, timeout=timeout))
            finally:
                page.remove_listener('filechooser', receive)
                if not chosen.done():
                    chosen.cancel()
                for chooser in choosers:
                    try:
                        await asyncio.wait_for(reply(chooser.element.dispose()), .5)
                    except (Error, asyncio.TimeoutError):
                        pass
        else:
            state = await reply(control.evaluate("e=>({file:e.matches('input[type=file]'),multiple:e.multiple})", timeout=timeout))
            if not state['file']:
                raise PluginError('LOCATOR_NOT_FILE_INPUT', 'Input upload mode requires input[type=file]')
            if len(files) > 1 and not state['multiple']:
                raise PluginError('UPLOAD_MULTIPLE_UNSUPPORTED', 'File input accepts only one file')
            await reply(control.set_input_files(files, timeout=timeout))
    return result


async def dialog_action(page, inputs, locate):
    trigger = inputs.get('trigger', 'click')
    if (trigger == 'press') != ('key' in inputs):
        raise PluginError('DIALOG_TRIGGER_INVALID', 'key is required only for a press trigger')
    expected = inputs['dialogs']
    if any('prompt_text' in item and (item['type'] != 'prompt' or item['response'] != 'accept') for item in expected):
        raise PluginError('DIALOG_RESPONSE_INVALID', 'prompt_text is only valid for accepting a prompt')
    control = locate(page, inputs['selector'])
    timeout = inputs.get('timeout_ms', 10000)
    finished = asyncio.Event()
    handled, tasks, open_dialogs = [], set(), set()
    observed, failure, active = 0, None, True

    async def handle(dialog):
        nonlocal observed, failure
        index = observed
        observed += 1
        open_dialogs.add(dialog)
        settled = False
        try:
            specification = expected[index] if index < len(expected) else None
            if not active or failure is not None or specification is None or dialog.type != specification['type'] or dialog.message != specification['message']:
                await reply(dialog.dismiss())
                settled = True
                failure = failure or PluginError('DIALOG_EXPECTATION_MISMATCH', 'Unexpected native dialog; dismissed instead of accepting it')
            else:
                if specification['response'] == 'accept':
                    await reply(dialog.accept(specification.get('prompt_text')))
                else:
                    await reply(dialog.dismiss())
                settled = True
                handled.append({'type': dialog.type, 'response': specification['response']})
        except Error:
            failure = failure or PluginError('BROWSER_ACTION_FAILED', 'Native dialog closed before handling completed')
        finally:
            # Cancellation during accept/dismiss must retain the still-open
            # dialog for action cleanup, otherwise it blocks page execution.
            if settled:
                open_dialogs.discard(dialog)
            if failure is not None or len(handled) == len(expected):
                finished.set()

    def receive(dialog):
        task = asyncio.create_task(handle(dialog))
        tasks.add(task)

    page.on('dialog', receive)
    try:
        async with asyncio.timeout(timeout / 1000):
            if trigger == 'press':
                await reply(control.press(inputs['key'], timeout=timeout))
            elif trigger == 'double_click':
                await reply(control.dblclick(timeout=timeout))
            else:
                await reply(control.click(timeout=timeout))
            await finished.wait()
            # Include any synchronous extra dialog emitted by the triggering
            # action. Do not keep an accepting listener for later actions.
            if tasks:
                await asyncio.gather(*tasks)
        if failure is not None:
            raise failure
        return {'handled': handled, 'completed': True}
    finally:
        active = False
        page.remove_listener('dialog', receive)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for dialog in tuple(open_dialogs):
            try:
                await asyncio.wait_for(reply(dialog.dismiss()), .5)
            except (Error, asyncio.TimeoutError):
                pass


async def perform(name, page, inputs, locate):
    if name == 'page_upload':
        return await upload(page, inputs, locate)
    return await dialog_action(page, inputs, locate)
