"""Application-owned retained authoring requests, independent of UI clients."""
import asyncio
from copy import deepcopy
import logging
from typing import Protocol
from taskweave.core.validation import TaskError


class AuthoringOperation(Protocol):
    async def __call__(self, operation: str, **params: object) -> dict: ...


class ApplicationDispatch(Protocol):
    def dispatch(self, operation: str, params: dict) -> object: ...


class AuthoringRequests:
    def __init__(self, call: AuthoringOperation):
        self.call = call
        self.requests = {}

    def get(self, step_id):
        return self.requests.get(step_id)

    async def submit(self, operation, saved, **params):
        if operation not in {'step.generate', 'step.generate_goal'}:
            raise ValueError('Unsupported step authoring operation')
        step_id = saved['step_id']
        pending = self.get(step_id)
        if pending and not pending['task'].done():
            raise TaskError('AUTHORING_BUSY', '当前步骤的 AI 请求仍在处理中，请查看上次 AI 结果。')
        if step_id not in self.requests and len(self.requests) >= 16:
            completed = next((key for key, value in self.requests.items() if value['task'].done()), None)
            if completed is None:
                raise TaskError('AUTHORING_BUSY', '在途 AI 请求过多，请等待已有请求完成。')
            del self.requests[completed]
        task = asyncio.create_task(self.call(operation, **params))
        self.requests[step_id] = {
            'operation': operation, 'saved': deepcopy(saved), 'params': deepcopy(params), 'task': task,
        }
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)


def bind_application_requests(application: ApplicationDispatch) -> AuthoringRequests:
    async def call(operation, **params):
        logger = logging.getLogger(__name__)
        logger.info('服务操作：%s', operation)
        try:
            return await asyncio.to_thread(application.dispatch, operation, params)
        except Exception as exc:
            logger.error('服务操作失败：%s [%s]', operation, getattr(exc, 'code', type(exc).__name__))
            raise
    return AuthoringRequests(call)
