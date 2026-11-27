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
from ev_sim import ProportionalSharePolicy

def test_power_is_released_when_a_vehicle_finishes():
    m = ChargingStationManager(50, policy=ProportionalSharePolicy())
    m.add_port("P1", "FAST")
    m.add_port("P2", "FAST")
    sessions = [
        ChargingSession(0, "P1", "V1", 50, 10, 3 * 3600),
        ChargingSession(0, "P2", "V2", 50, 100, 2 * 3600),
    ]
    records = {r.vehicle_id: r for r in Simulator(m, sessions).run()}
    assert records["V2"].delivered_kwh == pytest.approx(90)