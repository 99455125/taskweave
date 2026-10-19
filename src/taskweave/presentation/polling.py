"""Visibility, request identity and bounded log state, independent of timers/UI."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PollToken:
    generation: int
    identity: str | tuple | None


class PollingState:
    def __init__(self):
        self.identity = None
        self.visible = True
        self.generation = 0
        self.next_at = 0.0
        self.pending: PollToken | None = None

    @property
    def loading(self):
        return self.pending is not None

    def observe(self, identity, *, visible):
        if identity != self.identity or visible != self.visible:
            self.generation += 1
            self.next_at = 0
        self.identity, self.visible = identity, visible

    def begin(self, identity, *, now):
        self.observe(identity, visible=self.visible)
        if not self.visible or self.loading or now < self.next_at:
            return None
        self.pending = PollToken(self.generation, identity)
        return self.pending

    def accepts(self, token):
        return self.visible and token == PollToken(self.generation, self.identity)

    def complete(self, token):
        if self.pending == token:
            self.pending = None

    def finish(self, token, *, now=0, running=True):
        self.complete(token)
        if self.accepts(token):
            self.next_at = now + (1 if running else 5)

    def invalidate(self):
        self.generation += 1
        self.next_at = 0


class LogStreamState:
    def __init__(self):
        self.cursor = 0
        self.enabled = False
        self.following = False
        self.text = ''
        self.has_more = False
        self.stopped = False
        self.error_code: str | None = None
        self.polling = PollingState()

    def toggle(self):
        self.enabled = not self.enabled
        self.following = self.enabled
        self.polling.invalidate()
        self.error_code = None

    def apply_page(self, page, addition):
        if page.get('reset'):
            self.text = ''
        self.cursor = page['cursor']
        if addition:
            self.text = (self.text + '\n' + addition).strip()[-24000:]
        self.has_more = page['has_more']
        self.stopped = not self.has_more and page['status'] != 'RUNNING'
        self.following = not self.stopped

    def fail(self, code):
        self.following = False
        self.error_code = code

    def dispose(self):
        self.enabled = self.following = False
        self.polling.observe(None, visible=False)
