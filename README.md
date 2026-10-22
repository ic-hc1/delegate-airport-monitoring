# Delegate Arrivals board

Airport-team board for meeting arriving delegates, built from the eleven
`*_Hotel_Delegates_Master_List.xlsx` workbooks and served from GitHub Pages
(`docs/`).

| Path | What it is |
|---|---|
| `dashboard/template.html` | The page: styles, markup, unlock screen, sync layer, board. `__ENC__` is replaced at build time. |
| `dashboard/build.py` | Merges every workbook's **Master List** sheet, encrypts the result with the passphrase and writes the page. |
| `docs/index.html` | The built page GitHub Pages serves. Holds only ciphertext. |
| `docs/config.js` | Shared-sync settings (Firebase). Safe to commit. |

## Publishing

1. In the repository go to **Settings → Pages**, set **Source** to *Deploy from a branch*, pick branch `master` and folder `/docs`, save.
2. The board is then at `https://<owner>.github.io/<repo>/`.

The page is reachable by anyone with the link, which is why the delegate data
inside it is encrypted. Volunteers unlock it with the passphrase once per
device. Give the passphrase to the airport team through a channel you trust,
never in the repository.

## Rebuilding after a new export

```
pip install openpyxl cryptography
ARRIVALS_PASSPHRASE='the passphrase' python3 -I dashboard/build.py docs/index.html dashboard/template.html /path/to/*_Hotel_Delegates_Master_List.xlsx
git add docs/index.html && git commit -m "Rebuild arrivals board" && git push
```

Using a new passphrase is fine; everyone just unlocks again. Tracking records
are keyed by delegate code, so they survive a rebuild.

## Shared tracking between volunteers

Out of the box, met checks, flight status and notes stay on each device
(browser storage), and the **Export / Import** buttons in the top bar pass a
JSON file of records between devices (newer record wins on import).

To make every volunteer see the same state live, give the board a Firebase
project (free tier is more than enough):

1. At <https://console.firebase.google.com> create a project, then add a **Web app** and copy its config object.
2. **Build → Authentication → Sign-in method**: enable **Anonymous**.
3. **Build → Firestore Database**: create a database, then set these rules:

   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /flights/{id}   { allow read, write: if request.auth != null; }
       match /delegates/{id} { allow read, write: if request.auth != null; }
     }
   }
   ```

4. Paste the config into `docs/config.js`:

   ```js
   window.ARRIVALS_CONFIG = {
     firebase: { apiKey: "...", authDomain: "....firebaseapp.com", projectId: "...", appId: "..." },
   };
   ```

5. Commit and push. The top-bar indicator turns to **Live · shared**.

Anyone who has the page URL and the Firebase config can write tracking
records (the records hold met flags, notes and the volunteer's name, not the
delegate data). If that matters, restrict the API key to the Pages domain in
Google Cloud Console → Credentials.

Records: `flights/<date>_<flight>` → `{status, note, by, at}` and
`delegates/<code>` → `{met, note, date, fid, hotel, by, at}`.
