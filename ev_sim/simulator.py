from dataclasses import dataclass
from itertools import count
import heapq
@dataclass
class ChargingSession:
    arrival_time: float
    port_id: str
    vehicle_id: str
    max_rate_kw: float
    energy_requested_kwh: float
    departure_time: float
    user_tier: str = "REGULAR"
    battery_cap_kwh: float = 1000
    current_kwh: float = 0.0

class Simulator:
    PLUG = 1
    UNPLUG = 0
    def __init__(self,manager,sessions: list[ChargingSession]):
        self.manager = manager
        self.sessions = sessions
        self.heap = []
        self.counter = count()
        for session in self.sessions:
            heapq.heappush(self.heap,(session.arrival_time,self.PLUG,next(self.counter),session))
            heapq.heappush(self.heap,(session.departure_time,self.UNPLUG,next(self.counter),session))


    def run(self):
        self.manager.tick(0)
        while self.heap:
            next_event_time = self.heap[0][0]
            next_completion_time = self.manager.next_completion_time()
            if self.manager.last_timestamp < next_completion_time < next_event_time:
                self.manager.tick(next_completion_time)
                continue
            
            time, event_type, _,session= heapq.heappop(self.heap)
            if event_type == self.PLUG:
                self.manager.plug_in(timestamp= time,
                                     port_id= session.port_id,
                                     vehicle_id= session.vehicle_id,
                                     battery_cap_kwh= session.battery_cap_kwh,
                                     current_kwh= session.current_kwh,
                                     max_rate_kw= session.max_rate_kw,
                                     user_tier= session.user_tier,
                                     departure_time= session.departure_time,
                                     energy_requested_kwh= session.energy_requested_kwh)
            elif event_type == self.UNPLUG:
                self.manager.unplug(timestamp = time,
                                    port_id = session.port_id)
        return self.manager.records




