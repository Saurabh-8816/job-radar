# Job Radar

A personal alert system for government, PSU and academic job notices — including the
ones that only ever appear on a district website.

Every 4 hours it reads all 33 Chhattisgarh district recruitment pages, CG Vyapam, CGPSC
and other state bodies, central recruiters (UPSC, SSC, ISRO, DRDO, C-DAC, NIELIT…),
PSUs, IITs, NITs, IIITs and central universities, plus state-level boards of MP, Odisha,
Maharashtra and Telangana. It reads the advert PDFs (OCR for scanned Hindi adverts),
decides whether each notice is for you, and sends matches to Telegram. An 8 PM digest
covers everything else, and a dashboard lets you search all of it.

```
fetch pages → parse notices → new? → read advert (PDF / OCR) → classify → Telegram + dashboard
```

## How adverts are read
Every new notice is read **in full**: every page of every attached advert (up to 5 per
notice, blank application forms skipped), OCR for scanned or legacy-font Hindi pages,
and, when a notice is only a link to a detail page (CG Vyapam, SarkariResult), that
page plus the PDFs it links to. So a post buried on page 21 of a "various posts"
advert (DSSSB 03/2026: TGT Computer Science, IT Assistant) still matches, and the
alert quotes where: `📄 advert p.21: …Trained Graduate Teacher (Computer Science)…`.

Typed PDFs cost almost nothing (a 45-page advert reads in ~2 s). OCR is capped at
10 minutes per run to stay inside GitHub's free minutes; anything left over is read
on the next run, never skipped.

## JavaScript-built sites
SSC, NIELIT, MPSC, CG Health and others send an empty page that a browser then fills in.
Sources marked `render: true` are opened in a headless browser (Chromium on GitHub; your
installed Edge on the laptop, after `pip install playwright`). Pages render six at a time
with images blocked, and are captured only once their list of links stops changing.
`tools/discover_careers.py "<name>" --render` finds the careers page inside such a site.

## How notices are sorted

| Tier | Meaning | You get |
|---|---|---|
| **A** | Your profile: IT/computer posts, MCA/BCA/B.Sc IT/M.Sc IT/B.Tech-M.Tech CS-IT, research & project staff in computing, CS teaching, Civil Sub-Engineer/JE | Instant Telegram alert |
| **B** | Any-graduate posts, unclear notices, unreadable adverts | 8 PM digest |
| **C** | Other fields (nurse, pharmacist, driver, ITI trades…) | Dashboard only |

Merit lists, results, claim-objection lists, schedules and corrigenda are marked
**update** and go to the digest, never as an alert. Everything lives in
[`profile.yaml`](profile.yaml): edit keywords there, no code changes needed.

## One-time setup (about 30 minutes)

### 1. Telegram bot
1. In Telegram, open **@BotFather** → `/newbot` → pick a name. It replies with a **token**.
2. Open your new bot and send it `/start` (otherwise the next step shows an empty list).
3. In a browser, visit `https://api.telegram.org/botTOKEN/getUpdates`, replacing `TOKEN`
   with your token. No brackets, no space after `bot`: `…/bot87417…:AAG…/getUpdates`.
   Copy the number at `"chat":{"id": …}`. That's your **chat ID**.

Keep the token private. It goes only into GitHub secrets (step 2), never into code or chat.

### 2. GitHub repository
1. Create a **private** repository on github.com, e.g. `job-radar`.
2. Push this folder:
   ```bash
   git add -A
   git commit -m "Job Radar: initial version"
   git branch -M main
   git remote add origin https://github.com/<you>/job-radar.git
   git push -u origin main
   ```
3. Repository → **Settings → Secrets and variables → Actions → New repository secret**:
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. **Actions** tab → enable workflows.

### 3. Phase 0: reachability check
**Actions → reachability-spike → Run workflow.** The summary lists any site that refuses
GitHub's cloud servers (some Indian government sites block non-Indian IPs). Compare with
your laptop:
```bash
python tools/spike_reachability.py
```
If something important works locally but not in the cloud, see *Blocked sites* below.

### 4. First run
**Actions → radar → Run workflow.** The first run indexes everything already published
(nothing old is replayed) and sends you the matching jobs that are **still open**. Reading
the existing adverts is spread across the next few runs, 40 per run.

From then on it runs by itself every 4 hours, and the digest arrives at 8 PM.

### 5. Dashboard (optional, free)
`site/index.html` is rebuilt every run, and the laptop relay copies the latest one from the
`state` branch each time it runs, so the simplest dashboard is a bookmark:
`file:///C:/Users/ASUS/Downloads/Suru_new/job-radar/site/index.html`.
To see it on your phone too, host it privately:
1. Create a free Cloudflare account → **Workers & Pages → Create → Pages → Direct upload**, name it `job-radar`.
2. Create an API token with **Cloudflare Pages: Edit** permission; note your **Account ID**.
3. Add GitHub secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`. The radar workflow then deploys every run.
4. **Zero Trust → Access → Applications → Add (self-hosted)** for `job-radar.pages.dev`, with a
   policy allowing only your Gmail address. Login becomes an emailed one-time code.

## Telegram commands
Each alert ends with `#ID` and tappable commands:

| Command | Effect |
|---|---|
| `/star_12` | Reminders 3 days and 1 day before #12 closes |
| `/applied_12` | Stop reminding |
| `/hide_12` | Not interested |
| `/unhide_12` | Undo |

Commands are read at the start of each run, so they take effect within 4 hours. Only your own chat ID is obeyed.

## Running locally

```bash
pip install -r requirements.txt
python -m radar.main backtest --only cg          # what would alert today? (sends nothing)
python -m radar.main run --dry-run --only cg     # a normal run, printed instead of sent
python -m radar.main digest --dry-run
python -m pytest
```

OCR needs Tesseract with Hindi. On Windows, install Tesseract, then download
`hin.traineddata` and `eng.traineddata` from
[tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast) into `.tessdata/`.
Without OCR, scanned adverts are marked "check manually" and go to the digest, so nothing is lost.

## Adding sources
- **Any institute or board:** add a line to `sources/candidates.yaml`, then
  `python tools/discover_careers.py "<name>"` finds its careers page and adds it to
  `sources/watch_pages.yaml`. Or write the entry into `watch_pages.yaml` by hand.
- **District sites:** `tools/discover_districts.py` regenerates `sources/s3waas_districts.yaml`.
  Every Indian district uses the same NIC S3WaaS template, so another state is just a
  list of district homepages.
- **Every Union Government body and PSU:** `python tools/import_igod.py` reads the official
  web directory (igod.gov.in) and writes `sources/igod_candidates.yaml` (ministries, offices,
  statutory/autonomous bodies, PSUs/companies, institutes) and `sources/kv_candidates.yaml`
  (Kendriya Vidyalayas). Then:

      python tools/discover_careers.py --from=igod_candidates.yaml --to=watch_igod.yaml --workers=32 --timeout=15
      python tools/discover_careers.py --from=kv_candidates.yaml --to=watch_kv.yaml --workers=10

  These bulk lists are checked less often than `watch_pages.yaml` (every 12 h and daily,
  at most 1,500 sites per run, longest-waiting first; see `WATCH_FILES` in
  `radar/sources.py`). KVs outside CG/MP/OD/MH/TG/DL alert only clear computer posts;
  their other notices stay on the dashboard.

## Health
The digest ends with a coverage line, and flags any source that failed 3 runs in a row or
whose page layout changed. Fix the URL in `sources/` and the next run picks it up.

## Sites that block GitHub: the laptop relay
About 40 sites (CG Vyapam, CGPSC, UPSC, MPPSC, MPESB, NTPC and others) refuse GitHub's
non-Indian servers. They're marked `runner: local` in `sources/watch_pages.yaml`, and your
laptop fetches them instead. **On top of that, anything GitHub failed to reach on its last
run is picked up by the laptop automatically** (e.g. when NIC blocks a district site, or
SarkariResult answers GitHub with 403), so no list needs maintaining:

```
Laptop (every 2h while on)                      GitHub (every 4h, 24/7)
  fetch the blocked sites, read new adverts  ──►  ingest data/inbox/*.json like any other page
  push a small file to data/inbox/                 classify · alert · digest · dashboard
```

The laptop never touches `jobs.db` or needs the Telegram token, and it only adds new
files, so git never conflicts. If the laptop is off, nothing breaks; the 8 PM digest says
when it last checked in.

Install once (PowerShell, in this folder):
```powershell
powershell -ExecutionPolicy Bypass -File tools\install_relay_task.ps1
```
Run it by hand any time with `python -m radar.main relay --push`. The log is in `data/relay.log`.

### 24/7 relay on a free Oracle Cloud server in India (optional)
The laptop relay only runs while the laptop is on. An Oracle Cloud "Always Free" Ubuntu
server in the Mumbai or Hyderabad region can run the same relay around the clock:
```bash
scp -i <ssh-key> tools/oracle_setup.sh ubuntu@<server-ip>:
ssh -i <ssh-key> ubuntu@<server-ip>
bash oracle_setup.sh
```
The script installs everything, asks you to add a GitHub deploy key (write access to this
repo only), tests which sources answer from the server's Indian IP, and schedules the relay
every 2 hours with cron. Both relays can run together; duplicates are merged by GitHub.
To move another site to the laptop, add `runner: local` to its entry.

## Layout
```
profile.yaml              what counts as a match (English + Hindi keywords)
sources/                  district registry, watched pages, candidate lists, bulk IGOD + KV lists
radar/                    fetch · parsers (s3waas, watch) · pdftext (OCR) · classify · store · notify · digest · dashboard
tools/                    source discovery, reachability spike
tests/                    pytest suite with real saved pages and OCR output
.github/workflows/        radar (4-hourly) · digest (8 PM IST) · spike · tests
data/jobs.db              state  } kept on the `state` branch as one commit each run replaces
site/index.html           dashboard } (tools/state.sh), so history doesn't grow by the database
```
