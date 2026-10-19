import unittest
from taskweave.presentation.catalog import CatalogFilter, CategoryFilter, filter_tasks, filter_plans


class CatalogTests(unittest.TestCase):
    def test_description_favorites_category_and_casefold_match(self):
        tasks = [{'name': 'A', 'description': 'Hello', 'is_favorite': True, 'category_id': 'c'}, {'name': 'B', 'description': 'other'}]
        self.assertEqual(filter_tasks(tasks, ' hello ', favorite=True, category_id='c'), tasks[:1])
        plans = [{'name': 'A', 'plan_description': 'Hello', 'is_favorite': True, 'category_id': 'c'}]
        self.assertEqual(filter_plans(plans, ' HELLO ', category_id='c'), plans)
        state = CatalogFilter(query='HELLO', category='favorites')
        self.assertEqual(state.tasks(tasks), tasks[:1])
        state.category = 'missing'
        state.retain_categories({'', 'favorites', 'c'})
        self.assertEqual(state.category, '')
        self.assertEqual(state.query, 'HELLO')

    def test_category_reset_keeps_search_and_plain_selection(self):
        state = CatalogFilter(query='saved', category='c')
        state.reset_category()
        self.assertEqual((state.query, state.category), ('saved', ''))
        selected = CategoryFilter(category='favorites')
        self.assertTrue(selected.favorite)
        self.assertIsNone(selected.category_id)

    def test_catalog_runs_with_gui_imports_forbidden(self):
        import subprocess
        import sys
        result = subprocess.run([sys.executable, '-c', """
import importlib.abc, sys
class Boundary(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(('taskweave.desktop', 'nicegui', 'webview')):
            raise AssertionError(fullname)
sys.meta_path.insert(0, Boundary())
from taskweave.presentation.catalog import CatalogFilter, filter_plans
state = CatalogFilter(query='DESCription', category='favorites')
records = [{'name': 'task', 'description': 'Description', 'is_favorite': True}]
assert state.tasks(records) == records
assert filter_plans([{'name': 'plan', 'plan_description': 'Description'}], 'description')
state.reset_category()
assert state.query == 'DESCription'
"""], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
