"""Task and plan catalog filtering over ordinary records and input state."""
from dataclasses import dataclass


def _filter(records, query, description_key, favorite, category_id):
    query = (query or '').strip().casefold()
    return [record for record in records
            if (not query or query in (record.get('name') or '').casefold()
                or query in (record.get(description_key) or '').casefold())
            and (favorite is not True or record.get('is_favorite'))
            and (not category_id or record.get('category_id') == category_id)]


def filter_tasks(tasks, query, favorite=None, category_id=None):
    return _filter(tasks, query, 'description', favorite, category_id)


def filter_plans(plans, query, favorite=None, category_id=None):
    return _filter(plans, query, 'plan_description', favorite, category_id)


@dataclass
class CategoryFilter:
    category: str = ''

    @property
    def favorite(self):
        return True if self.category == 'favorites' else None

    @property
    def category_id(self):
        return self.category if self.category not in {'', 'favorites'} else None

    def retain_categories(self, options):
        if self.category not in options:
            self.reset_category()

    def reset_category(self):
        self.category = ''


@dataclass
class CatalogFilter(CategoryFilter):
    query: str = ''

    def tasks(self, tasks):
        return filter_tasks(tasks, self.query, self.favorite, self.category_id)
