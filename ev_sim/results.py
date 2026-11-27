from dataclasses import dataclass
@dataclass
class SessionResult:
    vehicle_id: str
    requested_kwh: float
    delivered_kwh: float
    @property
    def satisfied(self):
        return self.requested_kwh - self.delivered_kwh < 1e-6
    