"""Delta logic for virtual meters — pure functions, no Home Assistant imports.

Kept free of HA dependencies so it can be tested standalone.
"""

ROLE_BASE = "base"
ROLE_SUBTRACT = "subtract"


def apply_delta(total: int, deficit: int, role: str, delta: int) -> tuple[int, int]:
    """Apply a source meter delta to a virtual meter.

    Returns the new (total, deficit). The total never decreases: any change
    that would lower it (subtract meter counting up, base meter corrected
    down) is booked as deficit instead. Later increases (base meter counting
    up, subtract meter corrected down) first pay off the deficit and only
    the remainder is added to the total. Long-term balance is kept:
    total - deficit always moves by exactly the net change.
    """
    net = delta if role == ROLE_BASE else -delta

    if net < 0:
        return total, deficit - net

    paid = min(deficit, net)
    return total + net - paid, deficit - paid
