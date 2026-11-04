# Free, cashless deployment (no server, no credit card)

```
 GitHub Actions (monthly, free) ──► greenspace run ──► greenspace publish ──► commits  published/  (about 0.5-2 MB)
                                                                                        │ push
 Visitors ──► Streamlit Community Cloud (free) ◄── redeploys on every push, reads published/ directly
```

| Piece | Service | Cost | Needs a card? |
|---|---|---|---|
| Code, data snapshot, automation | **GitHub** (public repository + Actions) | free | no |
| Dashboard hosting | **Streamlit Community Cloud** | free | sign-in is with GitHub; see the note in "Caveats" |

There is **no REST API server** in this setup (nothing runs 24/7). The same data is public in the repository
(`published/.../barris.csv` and `barris.geojson`), which works as an open-data download. The REST API and Docker stack remain available
in `docs/DEPLOYMENT.md` if you later get a server.

> Free-tier rules change. The facts below were checked against the providers' documentation in November 2026; re-check them before relying on them.

---

## One-time setup (about 45 minutes)

### 1. Create the public repository
1. Create a free **GitHub** account (if you do not have one) and a **new public repository**, e.g. `barcelona-green-access`.
   Streamlit's free tier requires the repository to be public. The repository holds only code and open data (no secrets).
2. The project ships with an MIT `LICENSE` file. Open it and replace `<YOUR NAME>` with your name (or organisation) before you push.

### 2. Publish your current data from your PC
You already have a validated run, so the dashboard can go live straight away:
```bat
greenspace publish
```
This copies the live run into `published\` (about 1 MB: ranking table, polygons, run information, quality checks). The large layers
(green-space polygons, stations, GeoPackage) are deliberately not published.

### 3. Push the project to GitHub
```bat
git init
git add .
git status
```
Check that `git status` does **not** list the `data\` folder (it is in `.gitignore`) and **does** list `published\`. Then:
```bat
git commit -m "Green space accessibility: initial release"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```
(If the folder is already a repository connected to GitHub, just `git add . && git commit && git push`.)

### 4. Deploy the dashboard on Streamlit Community Cloud
1. Go to **share.streamlit.io** and sign in **with GitHub**. Allow access to your repository.
2. **Create app** → *From existing repo*:
   - Repository: your repository · Branch: `main`
   - Main file path: **`src/greenspace/dashboard/app.py`**
   - Advanced settings → Python **3.12**
3. **Deploy.** The first build takes a few minutes. You get a public URL like `https://<name>.streamlit.app`.

The app finds no `API_URL`, so it reads `published/` directly. Dependencies come from `requirements.txt`.

> **Important:** the repository root must **not** contain an `environment.yml` (conda), `Pipfile` or `poetry.lock`. If several dependency
> files exist, Streamlit picks one by its own priority (conda first), and a heavy conda file makes the build run for ~45 minutes and fail.
> Keep a local conda file under another name, e.g. `conda-environment.yml`.

### 5. Switch on the monthly refresh
1. Repository → **Settings → Actions → General → Workflow permissions** → *Read and write permissions* → Save.
2. Repository → **Actions** tab → enable workflows if asked.
3. Open **refresh-data** → **Run workflow** once to test it. Expect about 15-25 minutes (it downloads from the portal and Overpass).
4. When it finishes, a commit "data: refresh YYYY-MM" appears and the dashboard updates within a minute or two.

From then on it runs by itself at 03:17 UTC on the 1st of every month.

---

## Operating it

| Situation | What happens / what to do |
|---|---|
| The refresh fails the quality checks or Overpass is down | The job fails (GitHub emails you), **nothing is committed**, the old data stays live. Download the `failed-run` artifact from the Actions run (contains `checks.json` / `error.txt`) and see `docs/RUNBOOK.md`. Re-run via *Run workflow* |
| Nobody opened the dashboard for 12 hours | Streamlit puts the app to sleep; the next visitor wakes it in about half a minute |
| You change the config (weights etc.) | Edit `configs/barcelona.yaml`, push, run the workflow manually, record the approval in `docs/DECISIONS.md` |
| You want to preview locally without a server | `set GREENSPACE_PUBLISHED_DIR=data` then `streamlit run src\greenspace\dashboard\app.py` |
| Roll back the data | `git revert` the last "data: refresh" commit and push |

## Caveats of the free setup
- **Sleeping:** Streamlit Community Cloud hibernates apps after 12 hours without visitors, and gives roughly 1 GB of memory (sources quote 0.7-2.7 GB, shared). The dashboard is light, but if it ever hits the limit the app is throttled.
- **GitHub disables scheduled workflows after 60 days without repository activity** in a public repo. The monthly data commit counts as activity in normal use, but if you ever see the workflow switched off, re-enable it in the Actions tab. I could not confirm whether commits made by the workflow itself reset that timer, so check the Actions tab after two months.
- **Overpass from GitHub's servers:** shared IP addresses can be rate-limited. The pipeline retries and alternates servers; if a run still fails, run the workflow again later.
- **No custom domain** (the URL ends in `.streamlit.app`) and no REST API.
- **Public by design:** code and data are public. Attribution to Open Data BCN (CC BY 4.0) and OpenStreetMap (ODbL) is shown in the dashboard.
- **Card at sign-up:** the official flow is sign-in with GitHub, but one third-party site claims Streamlit asks for a card. If you are asked for payment details at any step, **stop** and use the fallback below.

## Fallback if you hit a limit (or want no sleeping at all)
A **static dashboard on GitHub Pages** (pure HTML + JavaScript reading the same `published/` files). It never sleeps, has no memory limit and needs no card;
the cost is that the dashboard must be rewritten in JavaScript. Ask for it if you want it.

## Troubleshooting (Streamlit Community Cloud)
| Symptom in *Manage app* logs | Cause / fix |
|---|---|
| `More than one requirements file detected ... Used: conda with environment.yml`, a very long "Solving environment", then `Error during processing dependencies` | A conda `environment.yml` is in the repository. Rename it (`git mv environment.yml conda-environment.yml`), push, then *Reboot app* |
| `streamlit: ERROR (spawn error)` / `error restarting streamlit` | Follows a failed dependency install: fix the dependencies first |
| `ModuleNotFoundError: No module named ...` | Add the package to `requirements.txt` and push |
| The app opens with "No published data yet" | The `published/` folder is missing from the repository: run `greenspace publish`, `git add published`, commit and push |
| Wrong Python version | The version is chosen when the app is created (Advanced settings). Delete the app and create it again with Python 3.12 |
