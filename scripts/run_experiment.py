from ev_sim.data_loader import load_acn_sessions
from ev_sim.manager import ChargingStationManager
from ev_sim.policies import EDFPolicy
from ev_sim.simulator import Simulator
def add_ports_to_manager(total_capacity_grid,policy,port_ids):
    manager = ChargingStationManager(total_capacity_grid,policy = policy)
    for port_id in port_ids:
        manager.add_port(port_id,"STANDARD")
    return manager


if __name__ == "__main__":
    file_path =  "data/caltech201809.json"
    data,_ = load_acn_sessions(file_path)
    total_capacity_grid = 10000
    policy = EDFPolicy()
    port_ids = set()
    for session in data:
        port_ids.add(session.port_id)
    manager = add_ports_to_manager(total_capacity_grid=total_capacity_grid,policy=policy,port_ids=port_ids)
    sim = Simulator(manager, data)
    records = sim.run()
    total_delivered_kWh = sum(record.delivered_kwh for record in records)
    total_requested_kWh = sum(record.requested_kwh for record in records)
    energy_satisfied_rate = total_delivered_kWh/total_requested_kWh
    print(f'{len(port_ids)}')
    print(len(records))
    print(energy_satisfied_rate * 100)
    time_sensitive_satisfied_ratio = sum(1 for record in records if record.satisfied)/len(records)
    print(f"ratio of users who were satisfied: {time_sensitive_satisfied_ratio}")


    


    
