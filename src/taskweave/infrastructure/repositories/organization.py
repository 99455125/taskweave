"""Local favorites and single-level categories for tasks and plans."""

import sqlite3
from taskweave.core.validation import TaskError
from taskweave.infrastructure.storage import now, uid


class OrganizationRepository:
    def __init__(self, store):
        self.store = store

    def categories(self):
        return self.store.query("SELECT * FROM organization_categories ORDER BY name COLLATE NOCASE")

    def create_category(self, name):
        value = (name or "").strip()
        if not value:
            raise TaskError("FORM_INVALID", "分类名称不能为空")
        category_id, stamp = uid(), now()
        try:
            self.store.execute("INSERT INTO organization_categories(category_id,name,created_at,updated_at) VALUES(?,?,?,?)", (category_id, value, stamp, stamp))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" not in str(exc):
                raise
            raise TaskError("FORM_INVALID", "分类名称已存在") from exc
        return self.store.query("SELECT * FROM organization_categories WHERE category_id=?", (category_id,), True)

    def rename_category(self, category_id, name):
        value = (name or "").strip()
        if not value:
            raise TaskError("FORM_INVALID", "分类名称不能为空")
        try:
            changed = self.store.execute("UPDATE organization_categories SET name=?,updated_at=? WHERE category_id=?", (value, now(), category_id))
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed" not in str(exc):
                raise
            raise TaskError("FORM_INVALID", "分类名称已存在") from exc
        if not changed:
            raise TaskError("NOT_FOUND")
        return self.store.query("SELECT * FROM organization_categories WHERE category_id=?", (category_id,), True)

    def delete_category(self, category_id):
        with self.store.transaction() as db:
            if not db.execute("SELECT 1 FROM organization_categories WHERE category_id=?", (category_id,)).fetchone():
                raise TaskError("NOT_FOUND")
            db.execute("DELETE FROM organization_categories WHERE category_id=?", (category_id,))
        return {"deleted": category_id}

    def set_metadata(self, entity, entity_id, is_favorite, category_id):
        table, key = {"task": ("tasks", "task_id"), "plan": ("plans", "plan_id")}.get(entity, (None, None))
        if not table:
            raise TaskError("FORM_INVALID", "未知的组织对象")
        with self.store.transaction() as db:
            if not db.execute(f"SELECT 1 FROM {table} WHERE {key}=?", (entity_id,)).fetchone():
                raise TaskError("NOT_FOUND")
            if category_id is not None and not db.execute("SELECT 1 FROM organization_categories WHERE category_id=?", (category_id,)).fetchone():
                raise TaskError("NOT_FOUND", "分类不存在")
            db.execute(f"UPDATE {table} SET is_favorite=?,category_id=? WHERE {key}=?", (int(bool(is_favorite)), category_id, entity_id))
            return dict(db.execute(f"SELECT * FROM {table} WHERE {key}=?", (entity_id,)).fetchone())
