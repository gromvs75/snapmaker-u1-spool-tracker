import pytest

from tool_mapping import MappingError, physical_weights, validate_mapping


def test_multiple_logical_tools_can_share_one_physical_head():
    assert physical_weights([10, 20, 30, 40], [1, 1, 3, 0] + [0] * 28) == [40, 30, 0, 30]


@pytest.mark.parametrize("mapping", [None, [], [0, 1, 2], [0, 1, 2, 4], [0, 1, 2, True], [0, 1, 2, "3"]])
def test_missing_or_invalid_mapping_fails_closed(mapping):
    with pytest.raises(MappingError):
        validate_mapping(mapping)
