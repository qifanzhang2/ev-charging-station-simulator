from email.utils import parsedate_to_datetime
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from simulator import ChargingSession
def load_acn_sessions(path):
    all_sessions = []
    with open(path,"r") as f:
        data = json.load(f)
    LA = ZoneInfo(data[0]["timezone"])
    start = datetime(2018,9,1,tzinfo = LA)
    skipped = {"absence of disconnectTime": 0,
               "invalid energy":0,
               "invalid time":0}
    for session in data:
        if session["disconnectTime"] is None:
            skipped["absence of disconnectTime"] += 1
            continue
        if session["kWhDelivered"] is None or session["kWhDelivered"]<= 0:
            skipped["invalid energy"]+= 1
            continue
        charging_session = dissect_one_record(session,start)
        if charging_session.departure_time <= charging_session.arrival_time:
            skipped["invalid time"]+= 1
            continue
        all_sessions.append(charging_session)
    return all_sessions,skipped


def dissect_one_record(session,start):
    connection_time = session["connectionTime"]
    disconnect_time = session["disconnectTime"]
    data_connection_time = parsedate_to_datetime(connection_time)
    data_disconnect_time = parsedate_to_datetime(disconnect_time)
    tdf_connection = data_connection_time - start
    tdf_disconnection = data_disconnect_time - start
    arrival_time = tdf_connection.total_seconds()
    departure_time = tdf_disconnection.total_seconds()
    port_id = session["stationID"]
    vehicle_id = session["sessionID"]
    energy_requested_kwh = session["kWhDelivered"]
    new_charging_session = ChargingSession(arrival_time=arrival_time, 
                                            port_id=port_id, 
                                            vehicle_id=vehicle_id,
                                            max_rate_kw=6.656,
                                            departure_time=departure_time,
                                            energy_requested_kwh=energy_requested_kwh)
    return new_charging_session
if __name__ == "__main__":
    file_path = "data/caltech201809.json"
    all_sessions,skipped = load_acn_sessions(file_path)
    print(f"Successfully transcribed: {len(all_sessions)} \nskipped: {skipped}")



