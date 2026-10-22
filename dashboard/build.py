"""Build the GitHub Pages arrivals board from the hotel master-list workbooks.

Usage:
  ARRIVALS_PASSPHRASE='...' python3 -I build.py <output.html> <template.html> <xlsx files...>

The delegate data is encrypted with the passphrase (PBKDF2-SHA256 -> AES-256-GCM)
before it is embedded, so the published page holds only ciphertext. Volunteers
type the passphrase once to unlock the board on their device.
"""
import sys, os, re, json, base64, hashlib, secrets, datetime, collections, openpyxl
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

out_path, tpl_path, files = sys.argv[1], sys.argv[2], sys.argv[3:]
passphrase = os.environ.get("ARRIVALS_PASSPHRASE", "")
if not passphrase:
    sys.exit("Set ARRIVALS_PASSPHRASE (the passphrase volunteers will use to unlock the board).")

SHORT = {
    "GRANDWEST": "Grand Westside", "SEDA": "Seda", "OKADA": "Okada", "LANSON": "Lanson Place",
    "KINGSFORD": "Kingsford", "TRYP": "TRYP", "CITADINES": "Citadines", "HIEX": "Holiday Inn Express",
    "MANILAHOTEL": "Manila Hotel", "SAVOY": "Savoy", "CONRAD": "Conrad",
}
EVENT_WINDOW = ("2026-10-16", "2026-10-31")   # arrival dates outside this are flagged
PBKDF2_ITER = 200_000

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
    key = os.path.basename(p).split("-", 1)[-1].split("_")[0]
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

# delegate codes must be unique among active rows (they key the shared tracking records)
codes = collections.Counter(r["c"] for r in rows)
for r in rows:
    if codes[r["c"]] > 1:
        r["c"] = r["c"] + "-" + r["h"]

payload = {"hotels": hotels, "rows": rows, "cancelled": cancelled, "generated": generated,
           "window": EVENT_WINDOW}
plain = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITER, 32)
ct = AESGCM(key).encrypt(iv, plain, None)
b64 = lambda b: base64.b64encode(b).decode("ascii")
enc = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct),
       "generated": generated, "rows": len(rows)}
tpl = open(tpl_path, encoding="utf-8").read()
html = tpl.replace("__ENC__", json.dumps(enc, separators=(",", ":")))
os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
open(out_path, "w", encoding="utf-8").write(html)

# Flight schedule for the live-status job: flight numbers, airports and head counts only.
sched = collections.OrderedDict()
for r in rows:
    if r["q"] or not r["fl"] or not r["t"]: continue
    k = (r["d"], r["fl"], r["ap"] or "MNL")
    if k not in sched: sched[k] = {"d": r["d"], "fl": r["fl"], "ap": r["ap"] or "MNL", "t": r["t"], "n": 0, "fid": r["fid"]}
    sched[k]["n"] += 1
sched_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "schedule.json")
json.dump({"generated": generated, "flights": list(sched.values())}, open(sched_path, "w"), separators=(",", ":"))
print(f"schedule: {len(sched)} flight-days -> {sched_path}")
print(f"rows={len(rows)} cancelled={cancelled} hotels={len(hotels)} generated={generated} plain={len(plain)}B page={len(html)}B")
