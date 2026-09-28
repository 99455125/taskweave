"""Lifecycle contract shared by rendered desktop pages."""


class Page:
    """A page can release subscriptions, timers, and view handles when left."""

    def dispose(self):
        """Pages without page-owned resources have nothing to release."""
