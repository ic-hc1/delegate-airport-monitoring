"""Offline checks for the live-status job: normalizers and the polling planner."""
import datetime as dt, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_live as fl

ADB = {"arrivals": [
  {"number": "PR 113", "status": "Landed", "codeshareStatus": "IsOperator",
   "airline": {"name": "Philippine Airlines", "iata": "PR"},
   "departure": {"airport": {"iata": "LAX", "name": "Los Angeles"}},
   "arrival": {"scheduledTime": {"utc": "2026-10-24 21:30Z", "local": "2026-10-25 05:30+08:00"},
               "revisedTime": {"local": "2026-10-25 05:52+08:00"}, "runwayTime": {"local": "2026-10-25 05:49+08:00"},
               "terminal": "1", "gate": "", "baggageBelt": "7"}},
  {"number": "UA 809", "status": "Expected", "codeshareStatus": "IsOperator",
   "airline": {"name": "United Airlines"}, "departure": {"airport": {"iata": "GUM"}},
   "arrival": {"scheduledTime": {"local": "2026-10-25 10:35+08:00"}, "revisedTime": {"local": "2026-10-25 11:10+08:00"}, "terminal": "3"}},
  {"number": "OZ 701", "status": "Canceled", "departure": {"airport": {"iata": "ICN"}},
   "arrival": {"scheduledTime": {"local": "2026-10-25 10:35+08:00"}}},
  {"number": "NH 5261", "status": "Expected", "codeshareStatus": "IsCodeshared", "departure": {"airport": {"iata": "NRT"}},
   "arrival": {"scheduledTime": {"local": "2026-10-25 11:00+08:00"}}},
]}
out = fl.normalize_aerodatabox(ADB)
assert out["2026-10-25_PR113"]["st"] == "landed" and out["2026-10-25_PR113"]["act"] == "05:49" and out["2026-10-25_PR113"]["belt"] == "7", out
assert out["2026-10-25_UA809"]["st"] == "delayed" and out["2026-10-25_UA809"]["est"] == "11:10" and out["2026-10-25_UA809"]["term"] == "3", out
assert out["2026-10-25_OZ701"]["st"] == "cancelled"
assert out["2026-10-25_NH5261"]["cs"] is True

AERO = [{"ident_iata": "PR113", "codeshares_iata": ["QR4947"], "status": "Landed / Taxiing", "scheduled_in": "2026-10-24T21:30:00Z",
         "estimated_in": "2026-10-24T21:52:00Z", "actual_on": "2026-10-24T21:49:00Z", "terminal_destination": "1", "baggage_claim": "7",
         "origin": {"code_iata": "LAX"}, "operator_iata": "PR"}]
out = fl.normalize_aeroapi(AERO)
assert out["2026-10-25_PR113"]["st"] == "landed" and out["2026-10-25_PR113"]["sch"] == "05:30" and out["2026-10-25_PR113"]["act"] == "05:49", out
assert out["2026-10-25_QR4947"]["cs"] is True

sched = [{"d": "2026-10-25", "fl": "PR113", "ap": "MNL", "t": "05:30", "n": 85}, {"d": "2026-10-25", "fl": "Q926", "ap": "CRK", "t": "09:00", "n": 1}]
now = dt.datetime(2026, 10, 25, 4, 0, tzinfo=fl.MANILA)
assert fl.plan("MNL", now, sched, None)[0] == 60, fl.plan("MNL", now, sched, None)
assert fl.plan("MNL", now, sched + [{"d": "2026-10-25", "fl": "OZ701", "ap": "MNL", "t": "06:00", "n": 70}], None)[0] == 30
assert fl.plan("MNL", now, sched, now - dt.timedelta(minutes=10))[0] is None
assert fl.plan("CRK", dt.datetime(2026, 10, 25, 7, 0, tzinfo=fl.MANILA), sched, None)[0] == 180
assert fl.plan("CRK", now, sched, None)[0] is None
assert fl.plan("MNL", dt.datetime(2026, 10, 25, 23, 0, tzinfo=fl.MANILA), sched, None)[0] is None
assert fl.simple_status("Expected", "10:35", "10:40") == "scheduled"
print("fetch_live checks passed")
