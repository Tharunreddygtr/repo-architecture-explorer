from examples.capacity_service import CapacityService


def test_calculate_capacity_does_not_return_negative_values():
    service = CapacityService()

    assert service.calculate_capacity(12, 5) == 7
    assert service.calculate_capacity(3, 5) == 0
