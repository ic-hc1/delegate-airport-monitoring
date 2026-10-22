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
