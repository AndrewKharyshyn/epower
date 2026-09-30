import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import pytest
from ambient_protocol import canonical, is_canonical


def test_one_value_start_equals_end():
    assert canonical("+10") == [10.0, 10.0]
    assert canonical(13) == [13.0, 13.0]
    assert canonical([27.0]) == [27.0, 27.0]


def test_two_values():
    assert canonical("+12->+13") == [12.0, 13.0]


def test_three_or_more_values_keep_order():
    assert canonical("+17->+19->+17") == [17.0, 19.0, 17.0]
    assert canonical("+12->+9->+10")[-1] == 10.0


def test_domain_and_garbage_rejected():
    for bad in ("+99", "abc", [], None):
        with pytest.raises((ValueError, TypeError)):
            canonical(bad)


def test_is_canonical():
    assert is_canonical([1.0, 2.0]) and not is_canonical(5) and not is_canonical([5.0])
