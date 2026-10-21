"""The example's domain projection must keep future values out of public input."""
import unittest
from gymts_data_organization_demo.sources import numerical_sample


class PublicProjection(unittest.TestCase):
    def test_observed_prefix_and_future_are_separate(self):
        public, private = numerical_sample([1, 2, 3, 100, 200], name="fixture", horizon=2)
        self.assertEqual(public["series"][0]["values"], [1, 2, 3])
        self.assertEqual(public["context"], {"horizon": 2})
        self.assertEqual(private["expected_output"]["forecast"], [100, 200])
        self.assertEqual(public["sample_token"], private["sample_token"])
        self.assertNotIn("expected_output", public)
