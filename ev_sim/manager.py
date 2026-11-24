from ev_sim.models import Port, Vehicle
from ev_sim.billing import Billing_Engine
from ev_sim.policies import WeightedProportionalPolicy
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
         