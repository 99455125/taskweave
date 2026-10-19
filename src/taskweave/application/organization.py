"""Organization metadata use cases shared by every frontend."""
from taskweave.core.repositories import OrganizationRepository


class OrganizationUseCases:
    def __init__(self, repository: OrganizationRepository):
        self.repository = repository

    def categories(self):
        return self.repository.categories()

    def create_category(self, name):
        return self.repository.create_category(name)

    def rename_category(self, category_id, name):
        return self.repository.rename_category(category_id, name)

    def delete_category(self, category_id):
        return self.repository.delete_category(category_id)

    def set_metadata(self, entity, entity_id, is_favorite, category_id):
        return self.repository.set_metadata(entity, entity_id, is_favorite, category_id)
