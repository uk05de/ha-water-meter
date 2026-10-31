"""Standalone tests for the virtual meter delta logic (no HA install needed).

Run from the repo root: python3 -m unittest discover tests
or from anywhere: python3 path/to/tests/test_virtual_delta.py
"""

import importlib.util
import random
import unittest
from pathlib import Path

# Load the module by path: importing the package would pull in homeassistant
_PATH = Path(__file__).parent.parent / "custom_components" / "water_meter" / "virtual_delta.py"
_spec = importlib.util.spec_from_file_location("virtual_delta", _PATH)
virtual_delta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(virtual_delta)

apply_delta = virtual_delta.apply_delta
VirtualMeterState = virtual_delta.VirtualMeterState
EXPIRY = virtual_delta.DEFICIT_EXPIRY_SECONDS
BASE = virtual_delta.ROLE_BASE
SUB = virtual_delta.ROLE_SUBTRACT


def impulses(role, liters_per_hour, start, seconds, jitter=0.0, rng=None):
    """Evenly spaced 1 L impulses of one meter as (time, role) events."""
    interval = 3600 / liters_per_hour
    count = int(seconds / interval)
    return [
        (start + (i + 1) * interval + (rng.uniform(-jitter, jitter) if rng else 0), role)
        for i in range(count)
    ]


def replay(state, events):
    """Apply 1 L events in time order. Returns liters dropped by expiry."""
    dropped = 0
    for t, role in sorted(events):
        dropped += state.apply(role, 1, t)
    return dropped


class ApplyDeltaTest(unittest.TestCase):
    def test_base_increment_adds(self):
        self.assertEqual(apply_delta(100, 0, BASE, 5), (105, 0))

    def test_subtract_never_lowers_total(self):
        self.assertEqual(apply_delta(100, 0, SUB, 3), (100, 3))

    def test_subtract_on_zero_total(self):
        self.assertEqual(apply_delta(0, 0, SUB, 10), (0, 10))

    def test_base_pays_off_deficit_partially(self):
        self.assertEqual(apply_delta(100, 10, BASE, 4), (100, 6))

    def test_base_pays_off_deficit_with_remainder(self):
        self.assertEqual(apply_delta(100, 10, BASE, 15), (105, 0))

    def test_base_corrected_down_becomes_deficit(self):
        self.assertEqual(apply_delta(100, 2, BASE, -50), (100, 52))

    def test_subtract_corrected_down_pays_off_then_adds(self):
        self.assertEqual(apply_delta(100, 5, SUB, -8), (103, 0))

    def test_incident_2026_04_30(self):
        """Garden counted 69 + 78 + 84 L while main had not (yet) counted."""
        total, deficit = 50000, 0
        for garden in (69, 78, 84):
            total, deficit = apply_delta(total, deficit, SUB, garden)
            self.assertEqual(total, 50000)
        self.assertEqual(deficit, 231)
        # Main catches up later: deficit is paid off before the total moves
        total, deficit = apply_delta(total, deficit, BASE, 200)
        self.assertEqual((total, deficit), (50000, 31))
        total, deficit = apply_delta(total, deficit, BASE, 40)
        self.assertEqual((total, deficit), (50009, 0))

    def test_interleaved_impulses_balance(self):
        """Garden watering: main and garden impulses arrive in either order."""
        total, deficit = 1000, 0
        for _ in range(100):
            total, deficit = apply_delta(total, deficit, SUB, 1)
            total, deficit = apply_delta(total, deficit, BASE, 1)
        self.assertEqual((total, deficit), (1000, 0))

    def test_random_sequence_monotonic_and_balanced(self):
        rng = random.Random(42)
        total, deficit = 0, 0
        net_sum = 0
        for _ in range(10000):
            role = rng.choice((BASE, SUB))
            delta = rng.randint(-20, 50)
            prev_total = total
            total, deficit = apply_delta(total, deficit, role, delta)
            net_sum += delta if role == BASE else -delta
            self.assertGreaterEqual(total, prev_total)
            self.assertGreaterEqual(deficit, 0)
            self.assertEqual(total - deficit, net_sum)



class DeficitExpiryTest(unittest.TestCase):
    def test_order_jitter_is_offset(self):
        """Same liters on both meters, each impulse up to 2 s early/late."""
        rng = random.Random(1)
        state = VirtualMeterState(total=50000)
        events = impulses(SUB, 1100, 0, 3600, jitter=2.0, rng=rng)
        events += impulses(BASE, 1100, 0, 3600, jitter=2.0, rng=rng)
        # ±2 s on each meter = up to 4 s relative offset, so either meter can
        # lead by up to 2 L. The total rises by at most the main meter's lead,
        # the deficit by at most both leads (main ahead first, garden later).
        for t, role in sorted(events):
            state.apply(role, 1, t)
            self.assertLessEqual(state.total - 50000, 2)
            self.assertLessEqual(state.deficit, 4)
        state.expire(3600 + EXPIRY)
        # At most the main meter's lead stays counted as house water
        self.assertLessEqual(state.total - 50000, 2)

    def test_five_percent_overhang_expires_after_idle(self):
        """Irrigation 1 h: main 1100 L/h, garden counts 5 % more (1155 L/h)."""
        state = VirtualMeterState(total=50000)
        replay(state, impulses(BASE, 1100, 0, 3600) + impulses(SUB, 1155, 0, 3600))
        self.assertEqual(state.total, 50000)
        self.assertEqual(state.deficit, 55)
        last_garden = state.last_subtract_at
        # Still within 10 min after the last garden impulse: kept
        self.assertEqual(state.expire(last_garden + EXPIRY - 1), 0)
        self.assertEqual(state.deficit, 55)
        self.assertEqual(state.expires_at(), last_garden + EXPIRY)
        # 10 min idle: dropped
        self.assertEqual(state.expire(last_garden + EXPIRY), 55)
        self.assertEqual((state.total, state.deficit), (50000, 0))
        self.assertIsNone(state.expires_at())

    def test_house_water_after_irrigation_counts_normally(self):
        state = VirtualMeterState(total=50000)
        replay(state, impulses(BASE, 1100, 0, 3600) + impulses(SUB, 1155, 0, 3600))
        dropped = replay(state, impulses(BASE, 600, 3600 + EXPIRY, 300))
        self.assertEqual(dropped, 55)
        self.assertEqual((state.total, state.deficit), (50050, 0))

    def test_house_water_within_grace_period_offsets_deficit(self):
        """Known trade-off: house water right after irrigation pays off the overhang."""
        state = VirtualMeterState(total=50000)
        replay(state, impulses(BASE, 1100, 0, 3600) + impulses(SUB, 1155, 0, 3600))
        replay(state, impulses(BASE, 600, 3600, 300))
        self.assertEqual((state.total, state.deficit), (50000, 5))

    def test_garden_activity_keeps_deficit(self):
        state = VirtualMeterState(total=100)
        state.apply(SUB, 10, 0)
        state.apply(SUB, 1, EXPIRY - 1)
        self.assertEqual(state.apply(BASE, 5, 2 * EXPIRY - 2), 0)
        self.assertEqual((state.total, state.deficit), (100, 6))

    def test_base_correction_down_expires_without_garden_activity(self):
        state = VirtualMeterState(total=100, last_subtract_at=0)
        state.apply(BASE, -50, 2 * EXPIRY)
        self.assertEqual(state.deficit, 50)
        self.assertEqual(state.apply(BASE, 3, 2 * EXPIRY + 1), 50)
        self.assertEqual((state.total, state.deficit), (103, 0))

    def test_restored_deficit_without_timestamp_is_dropped(self):
        """Deficit restored from v0.2.1, which did not store a timestamp."""
        state = VirtualMeterState(total=100, deficit=231)
        self.assertEqual(state.expires_at(), 0.0)
        self.assertEqual(state.expire(1_800_000_000), 231)
        self.assertEqual((state.total, state.deficit), (100, 0))

    def test_restored_deficit_with_recent_timestamp_is_kept(self):
        """Restart during irrigation: deficit survives."""
        state = VirtualMeterState(total=100, deficit=20, last_subtract_at=1000)
        self.assertEqual(state.expire(1000 + 120), 0)
        self.assertEqual(state.deficit, 20)

    def test_random_sequence_monotonic_and_balanced(self):
        rng = random.Random(7)
        state = VirtualMeterState()
        net_sum = dropped_sum = 0
        t = 0.0
        for _ in range(10000):
            t += rng.expovariate(1 / 120)
            role = rng.choice((BASE, SUB))
            delta = rng.randint(-5, 30)
            prev_total = state.total
            dropped_sum += state.apply(role, delta, t)
            net_sum += delta if role == BASE else -delta
            self.assertGreaterEqual(state.total, prev_total)
            self.assertGreaterEqual(state.deficit, 0)
            self.assertEqual(state.total - state.deficit, net_sum + dropped_sum)


if __name__ == "__main__":
    unittest.main()
