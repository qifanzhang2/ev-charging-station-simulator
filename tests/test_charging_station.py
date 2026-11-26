import pytest

from ev_sim import (
    Billing_Engine,
    ChargingStationManager,
    EDFPolicy,
    LLFPolicy,
    ProportionalSharePolicy,
    Vehicle,
    WeightedProportionalPolicy,
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
    m = ChargingStationManager(100, policy=WeightedProportionalPolicy({}))
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


# ---------- demand-based charging ----------

def test_vehicle_stops_when_demand_is_met():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 20, 50, "REGULAR", energy_requested_kwh=25)
    logs = m.tick(HOUR)
    v = m.vehicles["V1"]
    assert "CHARGING_COMPLETE:V1" in logs
    assert v.total_energy_delivered == pytest.approx(25.0)
    assert v.current_charge_kwh == pytest.approx(45.0)
    assert v.completed_timestamp == pytest.approx(0.5 * HOUR)


def test_target_soc_converts_to_energy_request():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 20, 50, "REGULAR", target_soc=0.8)
    assert m.vehicles["V1"].energy_requested_kwh == pytest.approx(28.0)


def test_already_above_target_soc_completes_immediately():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 51, 50, "REGULAR", target_soc=0.8)
    assert m.vehicles["V1"].is_demand_met()
    assert m.ports["P1"].power == 0.0


def test_vehicle_starting_partially_charged_does_not_overcharge():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 20, 50, "REGULAR")
    m.tick(2 * HOUR)
    assert m.vehicles["V1"].current_charge_kwh == pytest.approx(60.0)


def test_departure_must_be_after_plug_in():
    m = make_station(100, n_ports=1)
    with pytest.raises(ValueError):
        m.plug_in(100, "P1", "V1", 60, 20, 50, "REGULAR", departure_time=100)


def test_idle_fee_starts_at_plug_in_if_already_satisfied():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 51, 50, "REGULAR", target_soc=0.8)
    bill = m.unplug(HOUR, "P1")
    # idle from t=0: (3600 - 900) s = 45 min x $0.50
    assert f"IDLE_FEE:{45 * Billing_Engine.IDLE_FEE_RATE:.2f}" in bill


# ---------- allocation policies (unit tests, no manager needed) ----------

class _V:
    def __init__(self, tier):
        self.user_tier = tier


def test_proportional_share_when_grid_is_short():
    requests = [("P1", _V("REGULAR"), 50), ("P2", _V("REGULAR"), 25)]
    result = ProportionalSharePolicy().allocate(requests, 60)
    assert result["P1"] == pytest.approx(40)
    assert result["P2"] == pytest.approx(20)


def test_proportional_share_when_grid_is_sufficient():
    requests = [("P1", _V("REGULAR"), 20), ("P2", _V("REGULAR"), 20)]
    assert ProportionalSharePolicy().allocate(requests, 100) == {"P1": 20, "P2": 20}


def test_policies_handle_no_requests():
    assert ProportionalSharePolicy().allocate([], 100) == {}
    assert WeightedProportionalPolicy().allocate([], 100) == {}


def test_weighted_share_is_capped_at_max_kw():
    policy = WeightedProportionalPolicy({"VIP": 10, "REGULAR": 1})
    requests = [("P1", _V("VIP"), 7.2), ("P2", _V("REGULAR"), 50)]
    result = policy.allocate(requests, 40)
    assert result["P1"] == pytest.approx(7.2)  # uncapped share would be ~23.6 kW


def test_manager_accepts_custom_policy():
    m = ChargingStationManager(90, policy=ProportionalSharePolicy())
    for pid in ("P1", "P2", "P3"):
        m.add_port(pid, "FAST")
    m.tick(0)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "VIP")
    m.plug_in(0, "P2", "V2", 60, 0, 50, "REGULAR")
    m.plug_in(0, "P3", "V3", 60, 0, 50, "REGULAR")
    for pid in ("P1", "P2", "P3"):
        assert m.ports[pid].power == pytest.approx(30)  # VIP gets no advantage


def test_satisfied_vehicle_enters_idling_state():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 60, 0, 50, "REGULAR", energy_requested_kwh=10)
    logs = m.tick(HOUR)
    assert "STATE_CHANGE:P1=IDLING" in logs


# ---------- priority-based greedy policies (EDF, LLF) ----------

def make_vehicle(vid, departure=None, request=None, current=0, tier="REGULAR"):
    return Vehicle(vid, 100, current, 50, tier, departure_time=departure, energy_requested_kwh=request)


def test_edf_serves_earliest_departure_first():
    a = make_vehicle("A", departure=3 * HOUR)
    b = make_vehicle("B", departure=5 * HOUR)
    requests = [("P1", b, 50), ("P2", a, 50)]
    result = EDFPolicy().allocate(requests, 70, now=0)
    assert result["P2"] == pytest.approx(50)   # A leaves first, gets full power
    assert result["P1"] == pytest.approx(20)   # B gets the leftover


def test_edf_puts_vehicles_without_departure_last():
    a = make_vehicle("A")                      # no departure time
    b = make_vehicle("B", departure=5 * HOUR)
    requests = [("P1", a, 50), ("P2", b, 50)]
    result = EDFPolicy().allocate(requests, 50, now=0)
    assert result["P2"] == pytest.approx(50)
    assert result.get("P1", 0.0) == 0.0


def test_greedy_never_exceeds_capacity():
    vehicles = [make_vehicle(f"V{i}", departure=(i + 1) * HOUR) for i in range(4)]
    requests = [(f"P{i}", v, 50) for i, v in enumerate(vehicles)]
    result = EDFPolicy().allocate(requests, 120, now=0)
    assert sum(result.values()) == pytest.approx(120)
    assert all(p <= 50 + 1e-9 for p in result.values())


def test_greedy_ties_broken_by_port_id():
    a = make_vehicle("A", departure=3 * HOUR)
    b = make_vehicle("B", departure=3 * HOUR)
    requests = [("P2", a, 50), ("P1", b, 50)]
    result = EDFPolicy().allocate(requests, 50, now=0)
    assert result == {"P1": 50}               # same deadline -> lower port_id wins


def test_llf_differs_from_edf():
    # A: leaves in 2h, needs 10 kWh -> laxity 1.8h
    # B: leaves in 3h, needs 100 kWh -> laxity 1.0h
    a = make_vehicle("A", departure=2 * HOUR, request=10)
    b = make_vehicle("B", departure=3 * HOUR, request=100)
    requests = [("P1", a, 50), ("P2", b, 50)]
    assert EDFPolicy().allocate(requests, 50, now=0) == {"P1": 50}
    assert LLFPolicy().allocate(requests, 50, now=0) == {"P2": 50}


def test_llf_uses_remaining_demand_not_battery_space():
    # Battery has 80 kWh of space but the driver only wants 10 kWh
    small = make_vehicle("A", departure=2 * HOUR, request=10, current=20)
    big = make_vehicle("B", departure=3 * HOUR, request=60, current=20)
    policy = LLFPolicy()
    assert policy.priority(small, 50, now=0) == pytest.approx(2 * HOUR - 10 / 50 * HOUR)
    assert policy.priority(big, 50, now=0) == pytest.approx(3 * HOUR - 60 / 50 * HOUR)


def test_llf_laxity_shrinks_over_time():
    v = make_vehicle("A", departure=4 * HOUR, request=50)
    policy = LLFPolicy()
    assert policy.priority(v, 50, now=HOUR) < policy.priority(v, 50, now=0)


def test_llf_requires_current_time():
    v = make_vehicle("A", departure=4 * HOUR, request=50)
    with pytest.raises(ValueError):
        LLFPolicy().allocate([("P1", v, 50)], 50, now=None)


def test_manager_runs_with_llf_policy():
    m = ChargingStationManager(50, policy=LLFPolicy())
    m.add_port("P1", "FAST")
    m.add_port("P2", "FAST")
    m.tick(0)
    m.plug_in(0, "P1", "A", 100, 0, 50, "REGULAR", departure_time=2 * HOUR, energy_requested_kwh=10)
    m.plug_in(0, "P2", "B", 100, 0, 50, "REGULAR", departure_time=3 * HOUR, energy_requested_kwh=100)
    assert m.ports["P2"].power == pytest.approx(50)   # B is more urgent
    assert m.ports["P1"].power == pytest.approx(0)
    assert m.ports["P1"].state == "WAITING"
# ---------- next completion time ----------
 
def test_next_completion_single_vehicle():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR", energy_requested_kwh=10)
    # 10 kWh at 50 kW -> 0.2 h
    assert m.next_completion_time() == pytest.approx(0.2 * HOUR)
 
 
def test_next_completion_returns_earliest_vehicle():
    m = make_station(100, n_ports=2)   # 100 kW so both get the full 50 kW
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR", energy_requested_kwh=10)
    m.plug_in(0, "P2", "V2", 100, 0, 50, "REGULAR", energy_requested_kwh=50)
    # V1: 0.2 h, V2: 1 h -> earliest is V1
    assert m.next_completion_time() == pytest.approx(0.2 * HOUR)
 
 
def test_next_completion_uses_allocated_power():
    m = make_station(50, n_ports=2)    # grid short: each REGULAR car gets 25 kW
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR", energy_requested_kwh=10)
    m.plug_in(0, "P2", "V2", 100, 0, 50, "REGULAR", energy_requested_kwh=50)
    # V1: 10 kWh at 25 kW -> 0.4 h
    assert m.next_completion_time() == pytest.approx(0.4 * HOUR)
 
 
def test_next_completion_is_inf_when_nothing_charging():
    m = make_station(100, n_ports=1)
    m.plug_in(0, "P1", "V1", 100, 0, 50, "REGULAR", energy_requested_kwh=0)  # already satisfied -> IDLING
    assert m.next_completion_time() == float("inf")
