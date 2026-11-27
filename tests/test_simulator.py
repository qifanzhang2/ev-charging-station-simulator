import pytest
from ev_sim import ChargingStationManager
from ev_sim.simulator import ChargingSession, Simulator

def test_single_session_is_served():
    m = ChargingStationManager(100)
    m.add_port("P1", "FAST")
    sessions = [ChargingSession(0, "P1", "V1", 50, 10, 3600)]

    records = Simulator(m, sessions).run()

    assert len(records) == 1
    assert records[0].delivered_kwh == pytest.approx(10)
    assert records[0].satisfied