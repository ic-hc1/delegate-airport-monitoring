#!/usr/bin/env python3
"""Fetch live arrival status for the delegates' flights and write docs/live.json.

Runs from GitHub Actions on a timer. It only spends API calls when delegate
flights are due, tracks the units used per month, and stops at the free-plan
budget. Providers: aerodatabox (default, RapidAPI) or aeroapi (FlightAware).

  python3 live/fetch_live.py            # normal run (needs a provider key in the environment)
  python3 live/fetch_live.py --force    # ignore the polling interval (still respects the budget)
  python3 live/fetch_live.py --dry-run  # plan only, no API call, no file write

Environment:
  LIVE_PROVIDER         aerodatabox | aeroapi            (default aerodatabox)
  AERODATABOX_KEY       RapidAPI key for AeroDataBox
  AEROAPI_KEY           FlightAware AeroAPI key
  LIVE_MONTHLY_UNITS    units the plan allows per month (default 400 for AeroDataBox Basic)
  LIVE_UNITS_PER_CALL   units one airport-board call costs (default 2; check the endpoint's tier)
  LIVE_AIRPORTS         comma list, default MNL,CRK
"""
import os, sys, json, re, pathlib, datetime as dt, urllib.request, urllib.parse, urllib.error
from zoneinfo import ZoneInfo

MANILA = ZoneInfo("Asia/Manila")
ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEDULE = ROOT / "docs" / "schedule.json"
LIVE = ROOT / "docs" / "live.json"
PROVIDER = os.environ.get("LIVE_PROVIDER", "aerodatabox").strip().lower()
BUDGET = int(os.environ.get("LIVE_MONTHLY_UNITS", "400"))
UNITS_PER_CALL = int(os.environ.get("LIVE_UNITS_PER_CALL", "2"))
AIRPORTS = [a.strip().upper() for a in os.environ.get("LIVE_AIRPORTS", "MNL,CRK").split(",") if a.strip()]
FORCE, DRY = "--force" in sys.argv, "--dry-run" in sys.argv
LOOKBACK = dt.timedelta(hours=5)          # refresh flights that landed since the previous poll, even when polls are hours apart
WINDOW = dt.timedelta(hours=11, minutes=55)   # AeroDataBox allows at most 12 h per call

def norm_flight(s):
    """Canonical flight number: no spaces, upper case, no leading zeros in the number (BR 0271 -> BR271)."""
    s = re.sub(r"\s+", "", str(s or "")).upper()
    m = re.match(r"^([A-Z][A-Z0-9]|[0-9][A-Z])([A-Z]?)0*(\d+)([A-Z]?)$", s)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}" if m else s

def airline_code(fl):
    m = re.match(r"^([A-Z][A-Z0-9]|[0-9][A-Z])", fl or "")
    return m.group(1) if m else ""

def hm(local_str):
    """'2026-10-25 05:30+08:00' or ISO -> ('2026-10-25', '05:30') in Manila time."""
    if not local_str: return None, None
    s = str(local_str).strip().replace("T", " ")
    try:
        if s.endswith("Z"): s = s[:-1] + "+00:00"
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None: d = d.replace(tzinfo=MANILA)
        d = d.astimezone(MANILA)
        return d.strftime("%Y-%m-%d"), d.strftime("%H:%M")
    except ValueError:
        return s[:10], s[11:16]

def simple_status(raw, sched_hm, est_hm):
    r = (raw or "").lower()
    if "cancel" in r: return "cancelled"
    if "divert" in r: return "diverted"
    if "landed" in r or "arrived" in r or "gate arrival" in r or "taxiing" in r: return "landed"
    if "delay" in r: return "delayed"
    if sched_hm and est_hm and est_hm != sched_hm:
        s, e = [int(x[:2]) * 60 + int(x[3:5]) for x in (sched_hm, est_hm)]
        if (e - s) % (24 * 60) >= 15 and (e - s) % (24 * 60) < 12 * 60: return "delayed"
    if "route" in r or "approach" in r or "depart" in r or "active" in r or "airborne" in r: return "active"
    return "scheduled"

# ---------------------------------------------------------------- providers
def fetch_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp), resp.headers

def aerodatabox(airport, start, end):
    key = os.environ.get("AERODATABOX_KEY", "")
    if not key: raise SystemExit("AERODATABOX_KEY is not set")
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M")
    url = (f"https://aerodatabox.p.rapidapi.com/flights/airports/iata/{airport}/{fmt(start)}/{fmt(end)}"
           "?direction=Arrival&withLeg=false&withCancelled=true&withCodeshared=true&withCargo=false&withPrivate=false&withLocation=false")
    data, headers = fetch_json(url, {"X-RapidAPI-Key": key, "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com"})
    found = normalize_aerodatabox(data)
    DIAG.append(describe_response(data, headers))
    return found, UNITS_PER_CALL

def _t(obj, *keys):
    """First present time among nested {local, utc} objects or flat strings."""
    for k in keys:
        v = obj.get(k)
        if isinstance(v, dict): v = v.get("local") or v.get("utc")
        if v: return v
    return None

def normalize_aerodatabox(data):
    out = {}
    if isinstance(data, list): flights = data
    elif isinstance(data, dict): flights = (data.get("arrivals") or data.get("departures") or data.get("flights") or [])
    else: flights = []
    for f in flights:
        if not isinstance(f, dict): continue
        num = norm_flight(f.get("number"))
        if not num: continue
        if "arrival" in f or "departure" in f:
            arr, dep = f.get("arrival") or {}, f.get("departure") or {}
        else:   # pre-2023 flat shape: one "movement" block describing the other end of the flight
            arr, dep = f.get("movement") or {}, {"airport": (f.get("movement") or {}).get("airport") or {}}
        sd, st = hm(_t(arr, "scheduledTime", "scheduledTimeLocal", "scheduledTimeUtc"))
        _, est = hm(_t(arr, "revisedTime", "predictedTime", "estimatedTimeLocal", "actualTimeLocal", "actualTimeUtc"))
        _, act = hm(_t(arr, "runwayTime", "actualTimeLocal", "actualTimeUtc"))
        if not sd: continue
        raw = f.get("status") or ""
        out[f"{sd}_{num}"] = {
            "st": simple_status(raw, st, est or act), "raw": raw, "sch": st, "est": est, "act": act,
            "term": str(arr.get("terminal") or ""), "gate": str(arr.get("gate") or ""), "belt": str(arr.get("baggageBelt") or ""),
            "from": (dep.get("airport") or {}).get("iata") or (dep.get("airport") or {}).get("name") or "",
            "al": (f.get("airline") or {}).get("name") or "", "cs": (f.get("codeshareStatus") or "") == "IsCodeshared",
        }
    return out

def aeroapi(airport, start, end):
    key = os.environ.get("AEROAPI_KEY", "")
    if not key: raise SystemExit("AEROAPI_KEY is not set")
    iso = lambda d: d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pages, out = 0, {}
    for kind in ("scheduled_arrivals", "arrivals"):
        url = f"https://aeroapi.flightaware.com/aeroapi/airports/{airport}/flights/{kind}?start={iso(start)}&end={iso(end)}&max_pages=12"
        data, _ = fetch_json(url, {"x-apikey": key})
        pages += int(data.get("num_pages") or 1)
        out.update(normalize_aeroapi(data.get(kind, []) or []))
    return out, pages

def normalize_aeroapi(flights):
    out = {}
    for f in flights:
        nums = [norm_flight(f.get("ident_iata") or f.get("ident"))] + [norm_flight(c) for c in (f.get("codeshares_iata") or [])]
        sd, st = hm(f.get("scheduled_in") or f.get("scheduled_on"))
        _, est = hm(f.get("estimated_in") or f.get("estimated_on"))
        _, act = hm(f.get("actual_on") or f.get("actual_in"))
        if not sd: continue
        raw = f.get("status") or ""
        rec = {"st": simple_status(raw, st, est or act), "raw": raw, "sch": st, "est": est, "act": act,
               "term": str(f.get("terminal_destination") or ""), "gate": str(f.get("gate_destination") or ""), "belt": str(f.get("baggage_claim") or ""),
               "from": (f.get("origin") or {}).get("code_iata") or "", "al": f.get("operator_iata") or "", "cs": False}
        for i, n in enumerate(n for n in nums if n):
            out[f"{sd}_{n}"] = dict(rec, cs=i > 0)
    return out

DIAG = []
def describe_response(data, headers):
    """A compact description of what the provider sent, for the run log and live.json."""
    d = {"type": type(data).__name__}
    if isinstance(data, dict):
        d["keys"] = sorted(data.keys())[:12]
        d["counts"] = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        first = next((v[0] for v in data.values() if isinstance(v, list) and v), None)
    elif isinstance(data, list):
        d["count"] = len(data); first = data[0] if data else None
    else:
        first = None; d["value"] = str(data)[:200]
    if isinstance(first, dict):
        d["firstKeys"] = sorted(first.keys())
        d["firstNumber"] = first.get("number"); d["firstStatus"] = first.get("status")
        for side in ("arrival", "departure", "movement"):
            if isinstance(first.get(side), dict): d[side + "Keys"] = sorted(first[side].keys())
    d["rateLimit"] = {k: v for k, v in headers.items() if "ratelimit" in k.lower()}
    print("provider response:", json.dumps(d))
    return d

PROVIDERS = {"aerodatabox": aerodatabox, "aeroapi": aeroapi}

# ---------------------------------------------------------------- planning
def load(path, default):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return default

def plan(airport, now, flights, last_call):
    """Decide whether to spend a call on this airport right now.

    Polls only while a delegate flight is due within the next 2.5 h or landed in
    the last 90 min, every 30 min at the peaks, hourly normally, every 2 h when
    only a handful of delegates are due. Secondary airports poll at most every 3 h.
    """
    soon, recent = [], []
    for f in flights:
        if f["ap"] != airport: continue
        when = dt.datetime.fromisoformat(f["d"] + "T" + f["t"]).replace(tzinfo=MANILA)
        delta = when - now
        if dt.timedelta(0) <= delta <= dt.timedelta(hours=2, minutes=30): soon.append(f["n"])
        elif -dt.timedelta(minutes=90) <= delta < dt.timedelta(0): recent.append(f["n"])
    if not soon and not recent:
        return None, "no delegate arrivals due within 2.5 h or landed in the last 90 min"
    pax = sum(soon) + sum(recent)
    interval = 30 if pax >= 150 else 60 if pax >= 10 else 120
    if airport != "MNL": interval = max(interval, 180)
    if last_call and not FORCE:
        age = (now - last_call).total_seconds() / 60
        if age < interval - 3:
            return None, f"polled {age:.0f} min ago; next poll in {interval - age:.0f} min ({pax} pax due or just landed)"
    return interval, f"{pax} pax due within 2.5 h or just landed -> poll every {interval} min"

def main():
    now = dt.datetime.now(MANILA)
    month = now.strftime("%Y-%m")
    sched = load(SCHEDULE, {}).get("flights", [])
    live = load(LIVE, {})
    live.setdefault("flights", {}); live.setdefault("calls", {}); live.setdefault("usage", {})
    if live.get("month") != month:
        live["usage"] = {}; live["month"] = month
    used = int(live["usage"].get("units", 0))
    live["provider"] = PROVIDER; live["budget"] = BUDGET
    notes, spent = [], 0
    fetch = PROVIDERS.get(PROVIDER)
    if not fetch: raise SystemExit(f"unknown LIVE_PROVIDER {PROVIDER!r}")
    for airport in AIRPORTS:
        last = live["calls"].get(airport, {}).get("at")
        last_dt = dt.datetime.fromisoformat(last).astimezone(MANILA) if last else None
        interval, why = plan(airport, now, sched, last_dt)
        if interval is None:
            notes.append(f"{airport}: skip, {why}"); continue
        if used + spent + UNITS_PER_CALL > BUDGET:
            notes.append(f"{airport}: skip, monthly budget reached ({used + spent}/{BUDGET} units)")
            live["budgetExhausted"] = True; continue
        notes.append(f"{airport}: {why}")
        if DRY: continue
        start = now - LOOKBACK
        try:
            found, cost = fetch(airport, start, start + WINDOW)
        except urllib.error.HTTPError as e:
            body = e.read()[:300].decode("utf-8", "replace")
            notes.append(f"{airport}: HTTP {e.code} from provider: {body}")
            live["calls"][airport] = {"at": now.isoformat(), "error": f"HTTP {e.code}"}
            continue
        spent += cost
        live["calls"][airport] = {"at": now.isoformat(), "found": len(found), "units": cost, "window": [start.strftime("%H:%M"), (start + WINDOW).strftime("%H:%M")]}
        terms = live.setdefault("terminals", {"byFlight": {}, "byAirline": {}})
        for k, v in found.items():
            v["at"] = now.isoformat(); v["ap"] = airport
            live["flights"][k] = v
            if airport == "MNL" and v.get("term"):      # remember which NAIA terminal each flight number and airline uses
                fl = k.split("_", 1)[1]
                terms["byFlight"][fl] = v["term"]
                al = airline_code(fl)
                if al: terms["byAirline"].setdefault(al, {})[v["term"]] = terms["byAirline"].setdefault(al, {}).get(v["term"], 0) + 1
    # prune records more than 36 h past their scheduled date
    cutoff = (now - dt.timedelta(hours=36)).strftime("%Y-%m-%d")
    live["flights"] = {k: v for k, v in live["flights"].items() if k[:10] >= cutoff}
    live["usage"]["units"] = used + spent
    if DIAG:
        live["lastResponse"] = DIAG[-1]
        hdr = {k.lower(): v for k, v in (DIAG[-1].get("rateLimit") or {}).items()}
        rem = hdr.get("x-ratelimit-api-units-remaining")
        if rem is not None and str(rem).isdigit():        # the provider's own count beats ours
            live["remainingUnits"] = int(rem); live["usage"]["units"] = max(0, BUDGET - int(rem))
            if int(rem) < UNITS_PER_CALL: live["budgetExhausted"] = True
    live["updatedAt"] = now.isoformat()
    live["notes"] = notes
    print("\n".join(notes)); print(f"units this month: {used + spent}/{BUDGET}; tracked flights: {len(live['flights'])}")
    if not DRY:
        LIVE.write_text(json.dumps(live, separators=(",", ":"), ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
