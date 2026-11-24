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
        return self.remaining_demand_kwh() <= 1e-9
class Billing_Engine:
    PEAK_RATE = 0.55
    OFF_PEAK_RATE = 0.30
    OFF_PEAK_END_HOUR = 6
    OFF_PEAK_START_HOUR = 22
    VIP_DISCOUNT = 0.8
    IDLE_FEE_RATE = 0.5 # dollars per minute after grace period
    GRACE_PERIOD_SECONDS = 900 # 15 minutes
    FAST_CHARGE_MULTIPLIER = 1.5
    @classmethod
    def get_electricity_rate(cls,time_stamp):
        seconds_in_day = time_stamp % 86400
        hours_in_day = seconds_in_day /3600
        if hours_in_day <6 or hours_in_day >=22:
            return cls.OFF_PEAK_RATE
        else:
            return cls.PEAK_RATE
    @classmethod
    def next_rate_boundary(cls, t):
        day_start = t - (t%86400)
        hour = (t - day_start)/3600
        if hour < cls.OFF_PEAK_END_HOUR:
            return day_start + cls.OFF_PEAK_END_HOUR * 3600
        elif hour < cls.OFF_PEAK_START_HOUR:
            return day_start + cls.OFF_PEAK_START_HOUR * 3600
        return day_start + 86400 + cls.OFF_PEAK_END_HOUR * 3600


    @classmethod
    def calculate_interval_cost(cls, start, end, power_kw):
        """Cost of charging at power_kw from start to end, split at peak/off-peak boundaries."""
        cost = 0.0
        t = start
        while t <end:
            seg_end= min(end, cls.next_rate_boundary(t))
            cost += power_kw * (((seg_end - t)/3600) * cls.get_electricity_rate(t))
            t = seg_end
        return cost
    @classmethod
    def calculate_charging_cost(cls, start,end,power_kw,port_type):
        cost = cls.calculate_interval_cost(start,end,power_kw)
        if port_type == "FAST":
            cost *= cls.FAST_CHARGE_MULTIPLIER
        return cost
            


    @classmethod
    def calculate_idlefee(cls,vehicle,unplug_timestamp):
        idle_time = unplug_timestamp- vehicle.completed_timestamp if vehicle.completed_timestamp is not None else 0.0
        idle_fee = (idle_time-cls.GRACE_PERIOD_SECONDS) *(cls.IDLE_FEE_RATE/60)  if idle_time >cls.GRACE_PERIOD_SECONDS else 0.0
        return idle_fee

    @classmethod
    def calculate_discounted_energy_bill(cls,vehicle):
        raw_energy_cost = vehicle.total_energy_cost * cls.VIP_DISCOUNT if vehicle.user_tier == "VIP" else vehicle.total_energy_cost
        return raw_energy_cost

class AllocationPolicy:
    def allocate(self, requests, capacity_kw,now = None):
        raise NotImplementedError
class ProportionalSharePolicy(AllocationPolicy):
    def allocate(self,requests,capacity_kw,now = None):
        total_power_demanded = sum([max_kw for _,_,max_kw in requests])
        if total_power_demanded ==0:
            return {}
        if total_power_demanded <= capacity_kw:
            return {port_id: max_kw for port_id,_,max_kw in requests}
        rebalanced_power = {}
        for port_id,_,max_kw in requests:
            rebalanced_power[port_id] = (max_kw / total_power_demanded) * capacity_kw
        return rebalanced_power
class WeightedProportionalPolicy(AllocationPolicy):
    DEFAULT_WEIGHTS = {"VIP": 2, "REGULAR":1}
    def __init__(self,tier_weights = None):
        self.tier_weights = dict(tier_weights) if tier_weights is not None else dict(self.DEFAULT_WEIGHTS)
    def allocate(self,requests,capacity_kw,now = None):
        total_power_demanded = sum([max_kw for _,_,max_kw in requests])
        total_weighted_power_demanded = 0.0
        for _,vehicle,max_kw in requests:
            total_weighted_power_demanded += max_kw * self.tier_weights.get(vehicle.user_tier,1.0)
        if total_power_demanded <= capacity_kw:
            return {port_id:max_kw for port_id,_,max_kw in requests}
        rebalanced_power = {}
        for port_id,vehicle,max_kw in requests:
            share = (self.tier_weights.get(vehicle.user_tier,1.0) * max_kw)/total_weighted_power_demanded
            rebalanced_power[port_id] = min(max_kw,capacity_kw * share)
        return rebalanced_power



            



        
            
                        




class ChargingStationManager:
    def __init__(self, total_grid_capacity_kw: float,policy = None):
        self.total_grid_cap = total_grid_capacity_kw
        self.ports = {}
        self.vehicles = {}
        self.last_timestamp = None
        self.policy = policy if policy is not None else WeightedProportionalPolicy()
        
        


    def add_port(self, port_id: str, port_type: str) -> None:
        """Registers a new port (port_type: 'FAST' or 'STANDARD')."""
        self.ports[port_id] = Port(port_type,port_id)
    def rebalance_load(self,now = None):
        active = []
        for vehicle in self.vehicles.values():
            port = self.ports[vehicle.port_id]
            if vehicle.is_demand_met():
                port.power = 0.0
                port.state = "IDLING"
                continue
            max_kw = min(port.port_maxpower_rate(),vehicle.max_accept_rate_kw)
            active.append((port.port_id,vehicle,max_kw))
        rebalanced_powers = self.policy.allocate(active,self.total_grid_cap,now)
        for port_id,_,_ in active:
            port = self.ports[port_id]
            port.power = rebalanced_powers.get(port_id,0.0)
            port.state = "CHARGING" if port.power > 0.0 else "WAITING"




            

        
            

            

            


    def update_grid_capacity(self, timestamp: float, new_capacity_kw: float) -> None:
        """Updates maximum grid capacity and triggers immediate load re-balancing."""
        if new_capacity_kw <0:
            raise ValueError("capacity number is invalid")
        self.tick(timestamp)
        self.total_grid_cap = new_capacity_kw
        self.rebalance_load(timestamp)
        

    def plug_in(self, timestamp: float, port_id: str, vehicle_id: str, 
                battery_cap_kwh: float, current_kwh: float, max_rate_kw: float, 
                user_tier: str,target_soc = None, departure_time = None, energy_requested_kwh = None) -> None:
        """Plugs a vehicle into a port."""
        if target_soc is not None:
            if target_soc <= 0 or target_soc > 1:
                raise ValueError("target_soc must be between 0 and 1")
            energy_requested_kwh = max(0,(battery_cap_kwh * target_soc) - current_kwh)
        if energy_requested_kwh is not None and energy_requested_kwh < 0:
            raise ValueError("energy_requested_kwh must be non-negative")
        if departure_time is not None and departure_time <= timestamp:
            raise ValueError("departure time must be after plugin time")
        if vehicle_id in self.vehicles:
            raise ValueError("Cannot plug twice")
        
        if port_id in self.ports:
            port = self.ports[port_id]
            if port.state != "UNPLUGGED":
                raise ValueError("Port Already Occupied")
            self.tick(timestamp)
            self.vehicles[vehicle_id] = Vehicle(vehicle_id,battery_cap_kwh,current_kwh,max_rate_kw,user_tier,departure_time,energy_requested_kwh)
            vehicle = self.vehicles[vehicle_id]
            if vehicle.is_demand_met():
                vehicle.completed_timestamp = timestamp
            port.vehicle_id = vehicle_id
            port.state = "WAITING"
            self.vehicles[vehicle_id].port_id = port_id
            
        else:
            raise ValueError("Port Not Exist")
        self.rebalance_load(timestamp)

    def unplug(self, timestamp: float, port_id: str) -> str:
        """Unplugs vehicle, frees port, and returns itemized bill string format: 
        'VEHICLE:<id>|ENERGY:<kwh>|COST:<dollars>|IDLE_FEE:<dollars>'
        """
        if timestamp is None:
            raise ValueError("unplug error, time is not provided")
        elif not port_id or port_id not in self.ports:
            raise ValueError("Port not exist")
        port = self.ports[port_id]
        if not port.vehicle_id:
            raise ValueError("Port Not Connected")
        self.tick(timestamp)
        vehicle = self.vehicles[port.vehicle_id]
        total_cost = Billing_Engine.calculate_discounted_energy_bill(vehicle)
        idle_fee = Billing_Engine.calculate_idlefee(vehicle,timestamp)
        port.vehicle_id = None
        port.power = 0.0
        port.state = "UNPLUGGED"
        del self.vehicles[vehicle.vehicle_id]
        self.rebalance_load(timestamp)
        return f"VEHICLE:{vehicle.vehicle_id}|ENERGY:{vehicle.total_energy_delivered:.2f}|COST:{total_cost:.2f}|IDLE_FEE:{idle_fee:.2f}"
        



    def tick(self, timestamp: float) -> list[str]:
        """Advances time to `timestamp`, updates battery levels, processes state 
        transitions, applies billing, and returns a list of status log updates:
        - 'STATE_CHANGE:port_id=status'
        - 'CHARGING_COMPLETE:vehicle_id'
        """
        log = []
        if self.last_timestamp is None:
            self.last_timestamp = timestamp
            self.rebalance_load(timestamp)
            return log
        dt = timestamp - self.last_timestamp
        if dt < 0:
            raise ValueError("timestamp cannot be sooner than Last timestamp")
        if dt == 0:
            return log
        for vehicle in self.vehicles.values():
            port = self.ports[vehicle.port_id]
            remaining = vehicle.remaining_demand_kwh()
            if port.state != "CHARGING" or port.power <= 0.0:
                continue
            if remaining <= port.power * (dt/3600):
                charge_end = self.last_timestamp + (remaining/port.power) * 3600
                vehicle.total_energy_delivered += remaining
                vehicle.total_energy_cost += Billing_Engine.calculate_charging_cost(self.last_timestamp, charge_end, port.power, port.port_type)
                vehicle.current_charge_kwh += remaining
                vehicle.completed_timestamp = charge_end
                log.append(f"CHARGING_COMPLETE:{vehicle.vehicle_id}") 
            else:
                energy = dt/3600 * port.power
                vehicle.total_energy_delivered += energy
                vehicle.total_energy_cost += Billing_Engine.calculate_charging_cost(self.last_timestamp, timestamp, port.power, port.port_type)
                vehicle.current_charge_kwh += energy
        old_states = {pid:p.state for pid,p in self.ports.items()}
        self.rebalance_load(timestamp)
        for pid,p in self.ports.items():
            if p.state != old_states[pid]:
                log.append(f"STATE_CHANGE:{pid}={p.state}")  
        self.last_timestamp = timestamp
        return log
            
        
if __name__ == "__main__":
    m = ChargingStationManager(total_grid_capacity_kw=100)
    m.add_port("P1", "FAST")
    m.tick(0)

    m.plug_in(0, "P1", "V1", battery_cap_kwh=60, current_kwh=0, max_rate_kw=50, user_tier="REGULAR")
    print(m.tick(7200))
    # ['CHARGING_COMPLETE:V1', 'STATE_CHANGE:P1=IDLING']

    print(m.unplug(9000, "P1"))
    # VEHICLE:V1|ENERGY:60.00|COST:27.00|IDLE_FEE:31.50
        
