# Delegate Arrivals dashboard

Airport-team board for meeting arriving delegates, built from the eleven
`*_Hotel_Delegates_Master_List.xlsx` workbooks.

- `template.html` – the page (styles, markup, script). `__DATA__` is replaced at build time.
- `build.py` – merges every workbook's **Master List** sheet into the page.
- `arrivals.html` – the built page that is published as the artifact.

Rebuild after a new export:

```
python3 -I build.py arrivals.html template.html /path/to/*_Hotel_Delegates_Master_List.xlsx
```

Then republish `arrivals.html` to the same artifact URL. Shared tracking
(flight status, met checks, notes) lives in the artifact's database and is
keyed by delegate code, so it survives a rebuild.

## Live flight status (free plan)

The board can show each flight's live status, estimated or actual landing
time, terminal, gate and baggage belt next to the listed time. The manual
status a volunteer sets is never overwritten by it.

A GitHub Actions job (`live-status.yml`) runs every 30 minutes. It reads
`docs/schedule.json`, and only when a delegate flight is due within 2.5 hours
or landed in the last 90 minutes does it spend one call per airport, pulling
the whole arrivals board for the next 12 hours. It polls every 30 minutes at
the Oct 25 and 26 peaks, hourly otherwise, every two hours at night, and
Clark at most every three hours. It keeps a running count of API units used
this month and stops at the budget. Simulated over the event week that is
about 150 calls, roughly 300 units if a board call costs 2 units.

Setup with the AeroDataBox free plan (via RapidAPI):

1. Sign up at <https://rapidapi.com/aedbx-aedbx/api/aerodatabox>, subscribe to the **Basic** (free) plan and copy your RapidAPI key.
2. In the repository, **Settings → Secrets and variables → Actions → New repository secret**: name `AERODATABOX_KEY`, value the key.
3. Check the plan's monthly unit allowance and the unit cost of the *airport departures and arrivals (FIDS)* endpoint on the RapidAPI page. If they differ from 400 units and 2 units per call, add repository **variables** `LIVE_MONTHLY_UNITS` and `LIVE_UNITS_PER_CALL` with the right numbers. The job never spends past `LIVE_MONTHLY_UNITS`.
4. Run the workflow once by hand (**Actions → Live flight status → Run workflow**) to confirm it commits `docs/live.json`.

FlightAware AeroAPI is supported as an alternative (`LIVE_PROVIDER=aeroapi`,
secret `AEROAPI_KEY`, units are result pages), but that path has not been run
against the real service.

Each GitHub Pages deploy after a poll takes about a minute, and the Pages
cache can add up to ten minutes, so the badge shows how old the data is.

## Rebookings (flight changes after the export)

When a delegate's flight changes, the board does not need a rebuild. A shared
record `delegates/<code>` in Firestore with `moved: true` and an `override`
block (`d`, `t`, `fl`, `checkin`, `note`, `ticket`, plus the old `oldD`,
`oldT`, `oldFl`) moves that delegate to the new date, time and flight on every
device within seconds. The delegate row shows "Rebooked" with the old flight and
the note; the flight row shows "N rebooked". A rebooking with no date yet lands
in the needs-checking list with its note. Deleting the record restores the
original. The delegate code is the sheet's Delegate ID without the `G-` prefix
and hyphens.

## NAIA terminals

Each MNL flight row shows its terminal after the airport code: `T3` when it
comes from the live feed for that flight, `T3?` when it is the terminal this
flight number used on another day or the airline's usual terminal (learned from
the feed as it runs; seeded from arrivals seen on 23 Oct 2026). The "NAIA
terminal" tile totals delegates per terminal for the selected view.
