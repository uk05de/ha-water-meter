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
BASE = virtual_delta.ROLE_BASE
SUB = virtual_delta.ROLE_SUBTRACT


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


if __name__ == "__main__":
    unittest.main()
