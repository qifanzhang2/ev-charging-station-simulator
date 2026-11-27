class Port:
    def __init__(self,port_type,port_id):
        self.state = "UNPLUGGED"
        self.vehicle_id = None
        self.power = 0
        self.port_type = port_type
        self.port_id = port_id
    def port_maxpower_rate(self):
        if self.port_type == "FAST":
            return 50
        elif self.port_type == "STANDARD":
            return 7.2
        else:
            raise ValueError(f"Port_id:{self.port_id} has invalid port_type")

class Vehicle:
    def __init__(self,vehicle_id,battery_capacity_kwh,current_charge_kwh,max_accept_rate_kw,user_tier,departure_time = None,energy_requested_kwh = None):
        self.vehicle_id = vehicle_id
        self.battery_capacity_kwh = battery_capacity_kwh
        self.current_charge_kwh = current_charge_kwh
        self.max_accept_rate_kw = max_accept_rate_kw
        self.user_tier = user_tier
        self.total_energy_delivered = 0
        self.completed_timestamp = None
        self.total_energy_cost = 0
        self.port_id = None
        self.departure_time = departure_time
        self.energy_requested_kwh = energy_requested_kwh

    def remaining_capacity_kwh(self):
        return max(0.0,self.battery_capacity_kwh - self.current_charge_kwh)
    def remaining_demand_kwh(self):
        if self.energy_requested_kwh is not None:
            return max(0.0,min(self.energy_requested_kwh - self.total_energy_delivered,self.remaining_capacity_kwh()))
        else:
            return self.remaining_capacity_kwh()
    def is_demand_met(self):
        return self.remaining_demand_kwh() <= 1e-6