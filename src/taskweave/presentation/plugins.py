"""Plain plugin catalog filtering and selected-item ownership."""

def filter_plugins(plugins, query="", status="all"):
    query = (query or "").strip().casefold()
    visible = [plugin for plugin in plugins if query in plugin["id"].casefold()]
    if status == "enabled":
        visible = [plugin for plugin in visible if plugin["enabled"]]
    elif status == "disabled":
        visible = [plugin for plugin in visible if not plugin["enabled"]]
    return visible


class PluginSelection:
    def __init__(self):
        self.selected_plugin_id = None
        self.search_query = ''
        self.status_filter = 'all'
        self.installed = []

    def load(self, installed):
        self.installed = list(installed)
        self.visible()

    def visible(self):
        rows = filter_plugins(self.installed, self.search_query, self.status_filter)
        if self.selected_plugin_id not in {row['id'] for row in rows}:
            self.selected_plugin_id = rows[0]['id'] if rows else None
        return rows
