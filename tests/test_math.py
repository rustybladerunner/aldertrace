"""softmax / confidence invariants."""

from __future__ import annotations

import unittest

from logitpick.mathutil import entropy_confidence, mass_from_logprobs, softmax


class SoftmaxTests(unittest.TestCase):
    def test_two_equal_logprobs_are_half(self) -> None:
        p = softmax([0.0, 0.0])
        self.assertAlmostEqual(p[0], 0.5)
        self.assertAlmostEqual(p[1], 0.5)

    def test_sums_to_one(self) -> None:
        p = softmax([-0.05221666395664215, -3.340428590774536])
        self.assertAlmostEqual(sum(p), 1.0, places=12)
        self.assertGreater(p[0], 0.95)
        self.assertLess(p[1], 0.05)

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            softmax([])


class ConfidenceTests(unittest.TestCase):
    def test_uniform_is_zero(self) -> None:
        self.assertAlmostEqual(entropy_confidence([0.5, 0.5]), 0.0)

    def test_one_hot_is_one(self) -> None:
        self.assertAlmostEqual(entropy_confidence([1.0, 0.0]), 1.0)

    def test_single_option_is_zero(self) -> None:
        self.assertEqual(entropy_confidence([1.0]), 0.0)

    def test_probe_pair_is_peaked(self) -> None:
        p = softmax([-0.05221666395664215, -3.340428590774536])
        conf = entropy_confidence(p)
        self.assertGreater(conf, 0.7)


class MassTests(unittest.TestCase):
    def test_probe_mass_is_not_one(self) -> None:
        # Full-vocab log-softmax leaves leftover mass on Y/N/yes/...
        mass = mass_from_logprobs([-0.05221666395664215, -3.340428590774536])
        self.assertGreater(mass, 0.9)
        self.assertLess(mass, 1.0)


if __name__ == "__main__":
    unittest.main()
