"""Build the GitHub Pages arrivals board from the delegates export.

Usage:
  ARRIVALS_PASSPHRASE='...' python3 -I dashboard/build.py docs/index.html dashboard/template.html \
      --csv Delegates-2026-10-25.csv [--names *_Hotel_Delegates_Master_List.xlsx ...]

The CSV export carries every schedule field but no names; names come from the
hotel master-list workbooks given with --names, matched by delegate code.
The delegate data is encrypted with the passphrase (PBKDF2-SHA256 -> AES-256-GCM)
before it is embedded, so the published page holds only ciphertext.
Also writes schedule.json (flight numbers and head counts only) beside the page.
"""
import sys, os, re, io, csv, json, base64, hashlib, secrets, datetime, collections
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

args = sys.argv[1:]
out_path, tpl_path = args[0], args[1]
csv_path = args[args.index("--csv") + 1]
names_files = args[args.index("--names") + 1:] if "--names" in args else []
passphrase = os.environ.get("ARRIVALS_PASSPHRASE", "")
if not passphrase:
    sys.exit("Set ARRIVALS_PASSPHRASE (the passphrase volunteers will use to unlock the board).")

HOTELS = {
    "GRANDWEST": "Grand Westside Manila Bay", "SEDA": "Seda Manila Bay", "OKADA": "Okada Manila",
    "LANSON": "Lanson Place Mall of Asia", "KINGSFORD": "Kingsford Hotel Manila", "TRYP": "TRYP by Wyndham - Mall of Asia",
    "CITADINES": "Citadines Bay City Manila", "HIEX": "Holiday Inn Express Manila", "MANILAHOTEL": "The Manila Hotel",
    "SAVOY": "Savoy Hotel Manila", "CONRAD": "Conrad Manila",
}
SHORT = {"GRANDWEST": "Grand Westside", "SEDA": "Seda", "OKADA": "Okada", "LANSON": "Lanson Place", "KINGSFORD": "Kingsford",
         "TRYP": "TRYP", "CITADINES": "Citadines", "HIEX": "Holiday Inn Express", "MANILAHOTEL": "Manila Hotel", "SAVOY": "Savoy", "CONRAD": "Conrad"}
ALIASES = {"kingsford hotel": "KINGSFORD", "holiday inn express": "HIEX", "manila hotel": "MANILAHOTEL", "seda manila ba": "SEDA"}
EVENT_WINDOW = ("2026-10-16", "2026-10-31")   # arrival dates outside this are flagged
PBKDF2_ITER = 200_000

def hotel_of(accommodation, pickup):
    """Map 'Kingsford Hotel | IC2026SFTS-016' or a hotel name to (code, rooming note)."""
    text = (accommodation or "").strip()
    name, _, extra = text.partition("|")
    name, extra = name.strip(), extra.strip()
    low = name.lower()
    for code, full in HOTELS.items():
        if low == full.lower(): return code, extra
    for alias, code in ALIASES.items():
        if low.startswith(alias): return code, extra
    for code, full in HOTELS.items():
        if (pickup or "").strip().lower() == full.lower(): return code, (text if text else "")
    return "OTHER", text

def norm_flight(f):
    if not f: return None
    s = re.sub(r"\s+", "", str(f)).upper()
    s = re.sub(r"^([A-Z]{2})O(\d)", r"\g<1>0\2", s)      # BRO261 -> BR0261 (letter O typed for zero)
    m = re.match(r"^([A-Z][A-Z0-9]|[0-9][A-Z])([A-Z]?)0*(\d+)([A-Z]?)$", s)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}" if m else (s or None)

def path_safe(s):
    return re.sub(r"[^A-Za-z0-9_\-.~:@+]", "-", s)

# names by delegate code, from the hotel workbooks
names = {}
if names_files:
    import openpyxl
    for p in names_files:
        ws = openpyxl.load_workbook(p, data_only=True)["Master List"]
        data = list(ws.iter_rows(values_only=True))
        hdr = list(data[3])
        for r in data[4:]:
            d = dict(zip(hdr, r))
            if d.get("Delegate Code") and d.get("Name (Last, First)"): names[str(d["Delegate Code"]).strip()] = str(d["Name (Last, First)"]).strip()

raw = open(csv_path, "rb").read().decode("utf-8-sig")
export = list(csv.DictReader(io.StringIO(raw)))
m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(csv_path))
generated = datetime.date.fromisoformat(m.group(1)).strftime("%b %d, %Y") if m else datetime.date.today().strftime("%b %d, %Y")

rows, cancelled, hotels_seen = [], 0, set()
for d in export:
    if (d.get("Status") or "Confirmed") != "Confirmed":
        cancelled += 1; continue
    code = d["Delegate Code"].strip()
    h, rooming = hotel_of(d.get("Accommodations"), d.get("Group's Pickup Location"))
    hotels_seen.add(h)
    fl = norm_flight(d.get("Arrival Flight Number"))
    ad = (d.get("Arrival Date") or "").strip() or None
    t = (d.get("Arrival Time") or "").strip()[:5] or None
    mode = (d.get("Arrival Transportation Mode") or "").strip()
    q = []
    if not ad: q.append("nodate")
    elif not (EVENT_WINDOW[0] <= ad <= EVENT_WINDOW[1]): q.append("odddate")
    if mode and mode != "Plane": q.append("notplane")
    if not fl: q.append("noflight")
    sfts = d.get("Special Full-Time Servant") == "Yes"
    rows.append({
        "h": h, "n": names.get(code) or f"(name not in hotel lists) {code}", "g": d["Group Code"].strip(), "c": code,
        "gc": 1 if d.get("Is Group Contact") == "Yes" else 0, "s": d.get("Gender"), "a": int(d["Age"]) if (d.get("Age") or "").isdigit() else None,
        "m": 1 if d.get("Is Minor Or Young Adult") == "Yes" else 0, "b": d.get("Branch"), "f": 1 if sfts else 0,
        "l": d.get("Primary Language"), "ci": (d.get("Check-in") or "").strip() or None, "d": ad, "t": t,
        "ap": (d.get("Arrival Airport") or "").strip() or None, "al": (d.get("Arrival Airline") or "").strip() or None,
        "fl": fl, "fr": (d.get("Arrival Flight Number") or "").strip() or None, "mode": mode,
        "fid": path_safe(f"{ad or 'nodate'}_{fl}") if fl else f"{ad or 'nodate'}_NOFLIGHT-{(t or '').replace(':', '') or 'xx'}",
        "gp": None, "r": rooming or ("Special rooming" if d.get("Has Special Rooming Needs") == "Yes" else None), "q": q,
    })

codes = collections.Counter(r["c"] for r in rows)
assert all(v == 1 for v in codes.values()), "duplicate delegate codes in export"
hotels = {k: {"name": v, "short": SHORT[k]} for k, v in HOTELS.items()}
if "OTHER" in hotels_seen: hotels["OTHER"] = {"name": "Other / not listed", "short": "Other"}

payload = {"hotels": hotels, "rows": rows, "cancelled": cancelled, "generated": generated, "window": EVENT_WINDOW,
           "source": os.path.basename(csv_path)}
plain = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
salt, iv = secrets.token_bytes(16), secrets.token_bytes(12)
key = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITER, 32)
ct = AESGCM(key).encrypt(iv, plain, None)
b64 = lambda b: base64.b64encode(b).decode("ascii")
enc = {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "generated": generated, "rows": len(rows)}
tpl = open(tpl_path, encoding="utf-8").read()
html = tpl.replace("__ENC__", json.dumps(enc, separators=(",", ":")))
os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
open(out_path, "w", encoding="utf-8").write(html)

sched = collections.OrderedDict()
for r in rows:
    if r["q"] or not r["fl"] or not r["t"]: continue
    k = (r["d"], r["fl"], r["ap"] or "MNL")
    if k not in sched: sched[k] = {"d": r["d"], "fl": r["fl"], "ap": r["ap"] or "MNL", "t": r["t"], "n": 0, "fid": r["fid"]}
    sched[k]["n"] += 1
sched_path = os.path.join(os.path.dirname(os.path.abspath(out_path)), "schedule.json")
json.dump({"generated": generated, "flights": list(sched.values())}, open(sched_path, "w"), separators=(",", ":"))
unnamed = sum(1 for r in rows if r["n"].startswith("(name"))
print(f"rows={len(rows)} unnamed={unnamed} other-hotel={sum(1 for r in rows if r['h']=='OTHER')} flagged={sum(1 for r in rows if r['q'])} generated={generated} plain={len(plain)}B page={len(html)}B schedule={len(sched)}")
