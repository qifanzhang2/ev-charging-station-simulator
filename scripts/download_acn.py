import requests
import os
import time
import json
from secretes_local import token
all_sessions = []
prefix = "https://ev.caltech.edu/api/v1/"
response = requests.get("https://ev.caltech.edu/api/v1/sessions/caltech",params= {"where": 'connectionTime>="Sat, 1 Sep 2018 07:00:00 GMT" and connectionTime<"Mon, 1 Oct 2018 07:00:00 GMT"'},auth = (token,""))
if response.status_code != 200:
    print(response.status_code)
    raise ValueError("Status code incorrect")
max_pages = 1
data = response.json()
total = data["_meta"]["total"]
all_sessions.extend(data["_items"])
while "next" in data["_links"]:
    if max_pages > 100:
        raise ValueError("Page Limit Exceeded")
    nxt_link = prefix + data["_links"]["next"]["href"]
    print(nxt_link)
    response = requests.get(nxt_link,auth = (token,""))
    if response.status_code != 200:
        print(response.status_code)
        break
    data = response.json()
    all_sessions.extend(data["_items"])
    time.sleep(0.3)
    max_pages += 1
print(f"total pages retreived: {len(all_sessions)} \ntotal pages: {total}")
with open("data/caltech201809.json","w") as f:
    json.dump(all_sessions,f,indent= 2)



