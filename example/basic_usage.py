from ev_sim import ChargingStationManager
if __name__ == "__main__":
    m = ChargingStationManager(total_grid_capacity_kw=100)
    m.add_port("P1", "FAST")
    m.tick(0)

    m.plug_in(0, "P1", "V1", battery_cap_kwh=60, current_kwh=0, max_rate_kw=50, user_tier="REGULAR")
    print(m.tick(7200))
    # ['CHARGING_COMPLETE:V1', 'STATE_CHANGE:P1=IDLING']

    print(m.unplug(9000, "P1"))
    # VEHICLE:V1|ENERGY:60.00|COST:27.00|IDLE_FEE:31.50