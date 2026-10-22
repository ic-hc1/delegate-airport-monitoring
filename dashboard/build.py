"""Build dashboard/arrivals.html from the 11 hotel master-list workbooks.

Usage: python3 -I build.py <output.html> <template.html> <xlsx files...>
"""
import sys, json, re, os, datetime, collections, openpyxl

out_path, tpl_path, files = sys.argv[1], sys.argv[2], sys.argv[3:]

SHORT = {
    "GRANDWEST": "Grand Westside", "SEDA": "Seda", "OKADA": "Okada", "LANSON": "Lanson Place",
    "KINGSFORD": "Kingsford", "TRYP": "TRYP", "CITADINES": "Citadines", "HIEX": "Holiday Inn Express",
    "MANILAHOTEL": "Manila Hotel", "SAVOY": "Savoy", "CONRAD": "Conrad",
}
EVENT_WINDOW = ("2026-10-16", "2026-10-31")   # arrival dates outside this are flagged

def dt(v):
    if v is None: return None
    if isinstance(v, (datetime.datetime, datetime.date)): return v.strftime("%Y-%m-%d")
    return str(v)[:10]

def tm(v):
    if v is None: return None
    if isinstance(v, (datetime.time, datetime.datetime)): return v.strftime("%H:%M")
    return str(v)[:5]

def norm_flight(f):
    if not f: return None
    s = re.sub(r"\s+", "", str(f)).upper()
    return s or None

def path_safe(s):
    return re.sub(r"[^A-Za-z0-9_\-.~:@+]", "-", s)

hotels, rows, cancelled, generated = {}, [], 0, None
for p in files:
    wb = openpyxl.load_workbook(p, data_only=True)
    ws = wb["Master List"]
    data = list(ws.iter_rows(values_only=True))
    key = os.path.basename(p).split("-", 1)[1].split("_")[0]
    full = str(data[0][0]).split("|")[0].strip()
    hotels[key] = {"name": full, "short": SHORT.get(key, full)}
    m = re.search(r"Generated: ([^|]+)", str(data[1][0]))
    if m: generated = m.group(1).strip()
    hdr = list(data[3])
    for r in data[4:]:
        if r[1] is None: continue
        d = dict(zip(hdr, r))
        if d.get("Status"):
            cancelled += 1
            continue
        fl = norm_flight(d["Flight No."])
        ad = dt(d["Arrival Date"])
        q = []
        if not ad: q.append("nodate")
        elif not (EVENT_WINDOW[0] <= ad <= EVENT_WINDOW[1]): q.append("odddate")
        if not fl: q.append("noflight")
        rows.append({
            "h": key, "n": d["Name (Last, First)"], "g": d["Group Code"], "c": d["Delegate Code"],
            "gc": 1 if d["Group Contact"] == "Yes" else 0, "s": d["Gender"], "a": d["Age"],
            "m": 1 if d["Minor"] == "Yes" else 0, "b": d["Branch"], "f": 1 if d["SFTS"] == "Yes" else 0,
            "l": d["Primary Language"], "ci": dt(d["Check-in"]), "d": ad, "t": tm(d["Arrival Time"]),
            "ap": d["Airport"], "al": d["Airline"], "fl": fl, "fr": d["Flight No."],
            "fid": (ad or "nodate") + "_" + path_safe(fl or "NOFLIGHT"),
            "gp": d["Gap Nights"], "r": d["Special Rooming"], "q": q,
        })

# delegate codes must be unique among active rows (they key the shared tracking docs)
codes = collections.Counter(r["c"] for r in rows)
for r in rows:
    if codes[r["c"]] > 1:
        r["c"] = r["c"] + "-" + r["h"]

payload = {"hotels": hotels, "rows": rows, "cancelled": cancelled, "generated": generated,
           "window": EVENT_WINDOW}
tpl = open(tpl_path, encoding="utf-8").read()
html = tpl.replace("__DATA__", json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
open(out_path, "w", encoding="utf-8").write(html)
print(f"rows={len(rows)} cancelled={cancelled} hotels={len(hotels)} generated={generated} bytes={len(html)}")
