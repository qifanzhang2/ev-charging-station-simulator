# EV Charging Station Manager

A Python model of an EV charging station that allocates limited grid power across vehicles, tracks charging over time, and bills customers using time-of-use rates, a fast-charging premium, and idle fees.

## Features

- **Weighted load balancing**: when total demand exceeds grid capacity, power is split in proportion to each vehicle's demand multiplied by its tier weight, so VIP users charge faster without starving regular users.
- **Time-of-use billing**: charging cost is split exactly at peak/off-peak boundaries (06:00 and 22:00), including intervals that span midnight or multiple days.
- **Fast-charging premium**: sessions on `FAST` ports are billed at 1.5× the time-of-use rate.
- **VIP discount**: VIP users receive 20% off their energy cost.
- **Exact completion tracking**: if a vehicle fills up partway through a time step, the exact completion time is computed, so idle fees start at the right moment.
- **Idle fees**: vehicles that stay plugged in after charging are billed per minute after a 15-minute grace period.
- **Event-safe updates**: every event (plug-in, unplug, grid capacity change) validates its inputs, settles charging up to that moment, changes the system state, and then reallocates power.

## Design

| Class | Responsibility |
|---|---|
| `Port` | A charger with a type (`FAST` 50 kW, `STANDARD` 7.2 kW), its current power, and state |
| `Vehicle` | Battery capacity, current charge, max accepted power, user tier, and running energy/cost totals |
| `Billing_Engine` | All pricing rules: time-of-use rates, interval cost, fast-charging premium, VIP discount, and idle fees |
| `ChargingStationManager` | Owns ports and vehicles, handles events, advances time, and allocates power |

`rebalance_load()` only decides **how much power each port gets**. `tick()` only computes **what happened over time** (energy delivered, cost, completion). Pricing lives entirely in `Billing_Engine`, layered so that `calculate_interval_cost()` handles time-of-use rates and `calculate_charging_cost()` adds the fast-charging premium on top. Keeping these separate makes each piece easy to test and change.

## Key Design Decisions

**1. Weighted allocation instead of strict priority.**
My first version served VIP vehicles first and gave regular vehicles only the leftover power. Under heavy VIP demand, regular vehicles received zero power indefinitely (starvation). I replaced it with weighted proportional sharing: each vehicle's share is `demand × weight / Σ(demand × weight)`. Strict priority is still available as a limiting case by giving VIP a very large weight, and passing empty weights gives every tier an equal share.

**2. Use real demand to decide *whether* to throttle, weighted demand to decide *how*.**
Grid capacity is a physical limit in kW, so the "is there enough power?" check compares it to the unweighted sum of demand. Weights only matter once power is actually scarce. Using weighted demand for the check would throttle vehicles even when the grid could serve everyone.

**3. Left-closed rate intervals.**
Off-peak is `[22:00, 06:00)` and peak is `[06:00, 22:00)`. An earlier version treated 06:00 itself as off-peak. Because billing splits intervals at 06:00, the following segment started exactly at 06:00, and the entire 06:00–22:00 period was billed at the off-peak rate. A test caught this: a full day of charging was billed at roughly half the correct amount.

**4. Settle before changing state.**
Power allocated by `rebalance_load()` stays constant until the next event. So each event function follows the same order: validate inputs → `tick()` to the event time using the *old* power → change state → `rebalance_load()`. Without this, plugging in a second vehicle would retroactively apply the new, lower power to the first vehicle's earlier charging. Validating first also means a failed event leaves the station unchanged.

## Usage

```python
from EV_ChargingStation_Simulation_System import ChargingStationManager

m = ChargingStationManager(total_grid_capacity_kw=100)
m.add_port("P1", "FAST")
m.tick(0)

m.plug_in(0, "P1", "V1", battery_cap_kwh=60, current_kwh=0, max_rate_kw=50, user_tier="REGULAR")
print(m.tick(7200))
# ['CHARGING_COMPLETE:V1', 'STATE_CHANGE:P1=WAITING']

print(m.unplug(9000, "P1"))
# VEHICLE:V1|ENERGY:60.00|COST:27.00|IDLE_FEE:31.50
```

Timestamps are absolute seconds from the start of the simulation. In this example the vehicle charges off-peak at a fast port (60 kWh × $0.30 × 1.5 = $27.00), finishes at t = 4320 s, and is unplugged 63 minutes after the grace period ends (63 × $0.50 = $31.50).

The bill format is `VEHICLE:<id>|ENERGY:<kWh>|COST:<USD>|IDLE_FEE:<USD>`.

## Tests

```bash
pip install pytest
pytest test_charging_station.py
```

The suite (27 tests) covers:

- Charging to full without overcharging, and exact completion time
- Weighted allocation when the grid is short, full power when it is sufficient, and equal shares with empty weights
- Grid capacity dropping to zero
- Rate boundaries at exactly 06:00 and 22:00, and billing across 22:00 and across a full day
- Fast-charging premium, and VIP discount combined with time-of-use rates
- Idle fees inside, exactly at, and beyond the grace period, including completion at `t = 0`
- Unplugging without a prior tick, and no double billing when `tick()` and `unplug()` happen at the same time
- Settling charging before a plug-in or grid change alters power allocation
- A failed plug-in leaving the station unchanged

Expected costs in the tests are computed from the `Billing_Engine` constants, so the tests stay valid if prices change.

## Limitations

- Prices are illustrative retail rates, not real tariffs.
- Power is assumed constant between events, so a vehicle that fills up mid-interval does not release its power to others until the next event.
- There is no minimum charging power; a vehicle may be assigned a very small amount of power under heavy load.
- Fully charged vehicles share the `WAITING` state with vehicles that are waiting for power.

## Roadmap

- [ ] Event-driven simulator that reads a day of events from CSV and treats vehicle completion as an internal event
- [ ] Compare allocation policies (strict priority, weighted, equal share) on waiting time, completion rate, and revenue
- [ ] Minimum charging power with iterative redistribution
- [ ] Separate `IDLE` state for fully charged vehicles that are still plugged in
