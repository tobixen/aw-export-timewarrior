from unittest.mock import patch

from aw_export_timewarrior.main import exclusive_overlapping


@patch('aw_export_timewarrior.main.config', {'exclusive': {'fruit': {'tags': ['pears', 'apples', 'cherries']}, 'flavor': {'tags': ['sweet', 'sour', 'salty']}}})
def test_exclusive_overlapping():
    assert not exclusive_overlapping({'sweet', 'cherries', 'berry', 'round'})
    assert exclusive_overlapping({'sweet', 'sour', 'cherries', 'berry', 'round'})
    assert exclusive_overlapping({'sweet', 'cherries', 'pears', 'round'})
