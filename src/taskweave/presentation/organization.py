"""Category edit drafts shared by task and planning adapters."""
from typing import Literal, Protocol, TypedDict, overload
from taskweave.core.data_contracts import CommandResult


class CategoryRecord(TypedDict):
    category_id: str
    name: str
    created_at: str
    updated_at: str


class CategoryOperations(Protocol):
    @overload
    async def __call__(self, operation: Literal['organization.category.list']) -> list[CategoryRecord]: ...
    @overload
    async def __call__(self, operation: Literal['organization.category.create'], *, name: str) -> CategoryRecord: ...
    @overload
    async def __call__(self, operation: Literal['organization.category.rename'], *, category_id: str, name: str) -> CategoryRecord: ...
    @overload
    async def __call__(self, operation: Literal['organization.category.delete'], *, category_id: str) -> CommandResult: ...


class CategorySession:
    def __init__(self, call: CategoryOperations):
        self.call = call
        self.new_name = ''
        self.names: dict[str, str] = {}

    async def load(self):
        categories = await self.call('organization.category.list')
        self.names = {row['category_id']: row['name'] for row in categories}
        return categories

    async def create(self):
        return await self.call('organization.category.create', name=self.new_name or '')

    async def rename(self, category_id: str):
        return await self.call('organization.category.rename', category_id=category_id, name=self.names[category_id])

    async def delete(self, category_id: str):
        return await self.call('organization.category.delete', category_id=category_id)
