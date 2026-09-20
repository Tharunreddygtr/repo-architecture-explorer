from __future__ import annotations


class CapacityService:
    """Calculate available capacity for a resource."""

    def calculate_capacity(self, planned: int, reserved: int) -> int:
        return max(planned - reserved, 0)
