"""Accumulate instinct→soul messages and apply drop policy on instinct changes.

The buffering and drop semantics are deliberately localized here so policy
changes (debounce, rate-limit, different drop rules) stay in this file rather
than spreading through spine.py / sim_spine.py / future analysis tooling.
"""


class MessageBuffer:
    """Holds pending messages between reflections. Drops stale ones when the
    instinct code has just been replaced.

    Parameters
    ----------
    drop_after_instinct_change:
        When True, calling `on_instinct_changed()` discards buffered messages
        that were produced by the previous instinct. These messages don't
        reflect the new code's behavior and would mislead the next reflection.
    spare_operator:
        When True, `OPERATOR:`-prefixed messages survive the drop. They're
        explicit human input, not artifacts of the old instinct.
    """

    def __init__(self, *,
                 drop_after_instinct_change: bool = True,
                 spare_operator: bool = True):
        self._buffer: list[dict] = []
        self.drop_after_instinct_change = drop_after_instinct_change
        self.spare_operator = spare_operator

    def add(self, msg: dict) -> None:
        self._buffer.append(msg)

    def drain(self) -> list[dict]:
        """Atomically remove and return all pending messages."""
        msgs, self._buffer = self._buffer, []
        return msgs

    def has_pending(self) -> bool:
        return bool(self._buffer)

    def on_instinct_changed(self) -> list[dict]:
        """Called after a successful instinct deployment. Drops the messages
        that arrived during the just-finished reflection (still in buffer for
        the next cycle). Returns the dropped list so the caller can persist
        it in the reflection record — research data, not silently lost."""
        if not self.drop_after_instinct_change:
            return []
        keep: list[dict] = []
        drop: list[dict] = []
        for m in self._buffer:
            if self.spare_operator and str(m.get("content", "")).startswith("OPERATOR:"):
                keep.append(m)
            else:
                drop.append(m)
        self._buffer = keep
        return drop
