
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

class PriorityGreedyPolicy(AllocationPolicy):
    def priority(self,vehicle, max_kw,now = None):
        raise NotImplementedError
    def allocate(self,requests,capacity_kw,now = None):
        ordered = sorted(requests, key = lambda x : (self.priority(x[1],x[2],now),x[0]))
        rebalance_loads = {}
        remaining = capacity_kw
        for port_id,vehicle, max_kw in ordered:
            if remaining<= 0:
                break
            power = min(max_kw,remaining)
            rebalance_loads[port_id] = power
            remaining -= power
        return rebalance_loads
class EDFPolicy(PriorityGreedyPolicy):
    def priority(self,vehicle,max_kw,now = None):
        if vehicle.departure_time is not None:
            return vehicle.departure_time
        return float("inf")
class LLFPolicy(PriorityGreedyPolicy):
    def priority(self,vehicle,max_kw,now = None):
        if vehicle.departure_time is None:
            departure_time = float("inf")
        else:
            departure_time = vehicle.departure_time
        if now is None:
            raise ValueError("Current Timestamp Is Required To Calculate LLF")
        if max_kw == 0:
            raise ValueError("power cannot be zero to calculate LLF")
        laxity = (departure_time - now) - vehicle.remaining_demand_kwh() /max_kw * 3600
        return laxity
