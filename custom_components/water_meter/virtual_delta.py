"""Delta logic for virtual meters — pure functions, no Home Assistant imports.

Kept free of HA dependencies so it can be tested standalone.
"""

from dataclasses import dataclass

ROLE_BASE = "base"
ROLE_SUBTRACT = "subtract"

# A deficit only bridges the jitter between subtract and base impulses for the
# same liter. Once the subtract meters have been idle this long, what is left
# is meter deviation (garden meter counts ~5 % more at high flow) and is dropped.
DEFICIT_EXPIRY_SECONDS = 600


def apply_delta(total: int, deficit: int, role: str, delta: int) -> tuple[int, int]:
    """Apply a source meter delta to a virtual meter.

    Returns the new (total, deficit). The total never decreases: any change
    that would lower it (subtract meter counting up, base meter corrected
    down) is booked as deficit instead. Later increases (base meter counting
    up, subtract meter corrected down) first pay off the deficit and only
    the remainder is added to the total.
    """
    net = delta if role == ROLE_BASE else -delta

    if net < 0:
        return total, deficit - net

    paid = min(deficit, net)
    return total + net - paid, deficit - paid


@dataclass
class VirtualMeterState:
    """Total, deficit and last subtract activity of a virtual meter.

    Timestamps are seconds (e.g. UTC epoch). Invariant: total - deficit
    moves by exactly the net change, except for deficits dropped by expire().
    """

    total: int = 0
    deficit: int = 0
    last_subtract_at: float | None = None

    def expire(self, now: float) -> int:
        """Drop the deficit if the subtract meters have been idle long enough.

        A deficit without a known subtract timestamp (e.g. restored from a
        version that did not store it) is dropped as well. Returns the
        dropped liters.
        """
        if not self.deficit:
            return 0
        if (
            self.last_subtract_at is not None
            and now - self.last_subtract_at < DEFICIT_EXPIRY_SECONDS
        ):
            return 0
        dropped = self.deficit
        self.deficit = 0
        return dropped

    def apply(self, role: str, delta: int, now: float) -> int:
        """Expire a stale deficit, then apply the delta. Returns dropped liters."""
        dropped = self.expire(now)
        self.total, self.deficit = apply_delta(self.total, self.deficit, role, delta)
        if role == ROLE_SUBTRACT:
            self.last_subtract_at = now
        return dropped

    def expires_at(self) -> float | None:
        """When the current deficit would expire (None = no deficit)."""
        if not self.deficit:
            return None
        if self.last_subtract_at is None:
            return 0.0
        return self.last_subtract_at + DEFICIT_EXPIRY_SECONDS
