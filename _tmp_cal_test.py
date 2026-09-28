# -*- coding: utf-8 -*-
import json
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

token = json.load(open("config/teams_graph_token.json", encoding="utf-8"))
at = token["access_token"]

now = datetime.now(timezone.utc)
start = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
end = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

url = ("https://graph.microsoft.com/v1.0/me/calendarview?"
       + urllib.parse.urlencode({
           "startDateTime": start,
           "endDateTime": end,
           "$top": 20,
           "$select": "subject,start,end,attendees,organizer,isOnlineMeeting,onlineMeetingProvider,location",
       }))
try:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {at}"})
    body = json.loads(urllib.request.urlopen(req, timeout=30).read())
    events = body.get("value", [])
    print(f"events: {len(events)}")
    for ev in events[:10]:
        att = [a.get("emailAddress", {}).get("name") for a in ev.get("attendees", [])]
        print("-", (ev.get("start") or {}).get("dateTime"), "|",
              ev.get("subject"), "| online:", ev.get("isOnlineMeeting"),
              "| attendees:", att[:6])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read()[:500])
