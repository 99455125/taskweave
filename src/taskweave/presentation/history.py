"""On-demand history log request ownership, without dialog handles."""


class HistoryLoadState:
    def __init__(self, identity: tuple):
        self.identity = identity
        self.sequence = 0
        self.active = None

    @property
    def loading(self):
        return self.active is not None

    def begin(self, identity: tuple, *, visible: bool):
        if self.loading or not visible or identity != self.identity:
            return None
        self.sequence += 1
        self.active = (self.sequence, identity)
        return self.active

    def accepts(self, token, identity: tuple, *, visible: bool):
        return token is not None and token == self.active and identity == self.identity and visible

    def finish(self, token):
        if token == self.active:
            self.active = None
