import pytest

from EV_ChargingStation_Simulation_System import (
    Billing_Engine,
    ChargingStationManager,
    Vehicle,
)

HOUR = 3600


# ---------- helpers ----------

def make_station(capacity, n_ports=3, port_type="FAST"):
    m = ChargingStationManager(capacity)
    for i in range(1, n_ports + 1):
        m.add_port(f"P{i}", port_type)
    m.tick(0)
    return m


# ---------- charging & tick ----------

def test_single_vehicle_full_charge():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR")

    assert m.tick(HOUR) == []
    assert m.vehicles["V1"].current_charge_kwh == pytest.approx(50.0)

    logs = m.tick(2 * HOUR)
    assert "CHARGING_COMPLETE:V1" in logs
    assert m.vehicles["V1"].completed_timestamp == pytest.approx(4320.0)
    assert m.vehicles["V1"].current_charge_kwh == pytest.approx(60.0)  # never overcharged


def test_time_going_backwards_raises():
    m = make_station(100, n_ports=1)
    m.tick(1000)
    with pytest.raises(ValueError):
        m.tick(500)


def test_same_timestamp_is_noop():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR")
    m.tick(HOUR)
    charge = m.vehicles["V1"].current_charge_kwh
    assert m.tick(HOUR) == []
    assert m.vehicles["V1"].current_charge_kwh == charge


# ---------- load balancing ----------

def test_weighted_allocation_when_grid_is_short():
    m = make_station(100)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "VIP")
    m.plug_in(0, "P2", "V2", 60, 0, 50, "REGULAR")
    m.plug_in(0, "P3", "V3", 60, 0, 50, "REGULAR")

    # weighted demand = 50*2 + 50 + 50 = 200
    assert m.ports["P1"].power == pytest.approx(50.0)
    assert m.ports["P2"].power == pytest.approx(25.0)
    assert m.ports["P3"].power == pytest.approx(25.0)
    assert sum(p.power for p in m.ports.values()) == pytest.approx(100.0)


def test_everyone_gets_full_power_when_grid_is_sufficient():
    # real demand 90 kW < 100 kW, even though weighted demand (150) is larger
    m = make_station(100)
    m.plug_in(0, "P1", "V1", 60, 0, 30, "VIP")
    m.plug_in(0, "P2", "V2", 60, 0, 30, "VIP")
    m.plug_in(0, "P3", "V3", 60, 0, 30, "REGULAR")
    for pid in ("P1", "P2", "P3"):
        assert m.ports[pid].power == pytest.approx(30.0)


def test_grid_drop_to_zero_stops_all_charging():
    m = make_station(100, n_ports=2)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "VIP")
    m.plug_in(0, "P2", "V2", 60, 0, 50, "REGULAR")
    m.update_grid_capacity(0, 0)
    for p in m.ports.values():
        assert p.power == pytest.approx(0.0)
        assert p.state == "WAITING"


# ---------- billing: rates ----------

def test_rate_boundaries_are_left_closed():
    assert Billing_Engine.get_electricity_rate(6 * HOUR) == Billing_Engine.PEAK_RATE
    assert Billing_Engine.get_electricity_rate(22 * HOUR) == Billing_Engine.OFF_PEAK_RATE
    assert Billing_Engine.get_electricity_rate(5.99 * HOUR) == Billing_Engine.OFF_PEAK_RATE


@pytest.mark.parametrize(
    "t, expected",
    [
        (3 * HOUR, 6 * HOUR),               # 3:00  -> today 6:00
        (6 * HOUR, 22 * HOUR),              # 6:00  -> today 22:00 (boundary belongs to next segment)
        (10 * HOUR, 22 * HOUR),             # 10:00 -> today 22:00
        (23 * HOUR, 24 * HOUR + 6 * HOUR),  # 23:00 -> tomorrow 6:00
        (25 * HOUR, 24 * HOUR + 6 * HOUR),  # day 2, 1:00 -> day 2, 6:00
    ],
)
def test_next_rate_boundary(t, expected):
    assert Billing_Engine.next_rate_boundary(t) == pytest.approx(expected)


def test_interval_cost_splits_at_22():
    # 10 kW from 21:30 to 24:00: 0.5h peak + 2h off-peak
    cost = Billing_Engine.calculate_interval_cost(21.5 * HOUR, 24 * HOUR, 10)
    assert cost == pytest.approx(
        10 * 0.5 * Billing_Engine.PEAK_RATE + 10 * 2 * Billing_Engine.OFF_PEAK_RATE
    )


def test_interval_cost_spanning_a_full_day():
    # 1 kW for 24h: 16h peak + 8h off-peak
    cost = Billing_Engine.calculate_interval_cost(0, 24 * HOUR, 1)
    assert cost == pytest.approx(16 * Billing_Engine.PEAK_RATE + 8 * Billing_Engine.OFF_PEAK_RATE)


# ---------- billing: idle fee ----------

def make_completed_vehicle(completed_at):
    v = Vehicle("V1", 60, 60, 50, "REGULAR")
    v.completed_timestamp = completed_at
    return v


@pytest.mark.parametrize(
    "unplug_at, expected_fee",
    [
        (600, 0.0),    # within grace period
        (900, 0.0),    # exactly at grace period
        (960, 0.5),    # 1 minute over
        (1500, 5.0),   # 10 minutes over
    ],
)
def test_idle_fee(unplug_at, expected_fee):
    v = make_completed_vehicle(completed_at=0)  # completion at t=0 must still count
    assert Billing_Engine.calculate_idlefee(v, unplug_at) == pytest.approx(expected_fee)


def test_no_idle_fee_if_never_completed():
    v = Vehicle("V1", 60, 10, 50, "REGULAR")
    assert Billing_Engine.calculate_idlefee(v, 10_000) == 0.0


# ---------- unplug ----------

def test_unplug_settles_last_segment():
    # no tick between plug-in and unplug: unplug must still bill the 30 minutes
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR")
    bill = m.unplug(HOUR / 2, "P1")
    assert "ENERGY:25.00" in bill
    assert m.ports["P1"].state == "UNPLUGGED"


def test_tick_then_unplug_does_not_double_bill():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR")
    m.tick(HOUR / 2)
    bill = m.unplug(HOUR / 2, "P1")
    assert "ENERGY:25.00" in bill  # 25 kWh, not 50


def test_empty_weights_means_equal_priority():
    m = ChargingStationManager(100, tier_weights={})
    for pid in ("P1", "P2", "P3"):
        m.add_port(pid, "FAST")
    m.tick(0)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "VIP")
    m.plug_in(0, "P2", "V2", 60, 0, 50, "REGULAR")
    m.plug_in(0, "P3", "V3", 60, 0, 50, "REGULAR")
    for pid in ("P1", "P2", "P3"):
        assert m.ports[pid].power == pytest.approx(100 / 3)


def test_plug_in_settles_previous_segment():
    m = make_station(50, n_ports=2)
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR")
    m.plug_in(HOUR / 2, "P2", "V2", 100, 0, 50, "REGULAR")
    m.tick(HOUR)
    # V1: 30 min at 50 kW + 30 min at 25 kW = 25 + 12.5
    assert m.vehicles["V1"].current_charge_kwh == pytest.approx(37.5)


def test_grid_change_settles_previous_segment():
    m = make_station(50, n_ports=1)
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR")
    m.update_grid_capacity(HOUR / 2, 10)
    m.tick(HOUR)
    # 30 min at 50 kW + 30 min at 10 kW = 25 + 5
    assert m.vehicles["V1"].current_charge_kwh == pytest.approx(30.0)


def test_failed_plug_in_leaves_station_unchanged():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR")
    with pytest.raises(ValueError):
        m.plug_in(10, "P1", "V2", 60, 0, 50, "REGULAR")  # port occupied
    assert "V2" not in m.vehicles


def test_fast_charging_costs_more_than_standard():
    fast = Billing_Engine.calculate_charging_cost(0, HOUR, 7.2, "FAST")
    standard = Billing_Engine.calculate_charging_cost(0, HOUR, 7.2, "STANDARD")
    assert fast == pytest.approx(standard * Billing_Engine.FAST_CHARGE_MULTIPLIER)


def test_vip_discount_applied_to_bill():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "VIP")
    bill = m.unplug(HOUR, "P1")  # 50 kWh, all off-peak, fast port
    expected = 50 * Billing_Engine.OFF_PEAK_RATE * Billing_Engine.FAST_CHARGE_MULTIPLIER * Billing_Engine.VIP_DISCOUNT
    assert f"COST:{expected:.2f}" in bill
