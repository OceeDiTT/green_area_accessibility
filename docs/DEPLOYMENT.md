# Deployment guide

> **No budget / no credit card?** Use **`docs/FREE_DEPLOYMENT.md`** (GitHub Actions + Streamlit Community Cloud). This guide is for a paid server.

```
 internet ──► Caddy (HTTPS, :80/:443) ──► /      → dashboard (Streamlit)
                                       └─► /api/* → API (FastAPI, read-only)
                                                       ▲ read-only volume
                  scheduler (pipeline job, monthly) ───┘ writes new runs after the quality gate
```

**Status:** the pipeline, API and dashboard have been run on a Windows machine with conda. The **Docker images and this production
stack have not been built or run yet** — Step 1 below is how you find out, cheaply, before paying for a server.

---

## Step 1 — Test the containers on your own PC (about 30 minutes, free)

1. Install **Docker Desktop** (Windows: WSL 2 backend) and start it.
2. In the project folder:
   ```bat
   copy deploy\.env.example deploy\.env
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
   ```
   The first build takes several minutes (it downloads the geospatial libraries).
3. The `scheduler` container performs the **first data load** automatically (about 10 minutes, it downloads from the portal and
   Overpass). Watch it:
   ```bat
   docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs -f scheduler
   ```
4. Open **http://localhost/** (dashboard) and **http://localhost/api/docs** (API docs).

**Pass criteria** — all must hold before going further:
- [ ] all 4 containers show `running` / `healthy` in `docker compose ... ps`
- [ ] `http://localhost/api/ready` returns `{"status":"ready", ...}` after the load
- [ ] the dashboard shows the same ranking as your local run (e.g. Vallvidrera last, Diagonal Mar first)
- [ ] the map and every dashboard page load (the websocket works through the proxy)
- [ ] `docker compose ... restart` keeps the data (it lives in the `greenspace_data` volume)

Useful: `docker stats` during the data load shows the pipeline's real memory use (not measured yet; the limit is
`PIPELINE_MEM_LIMIT`, default 4 GB). Reset everything: `docker compose ... down -v`.

If a build or start fails, send me the error text; fixing packaging problems is expected at this stage.

---

## Step 2 — Put it on a server

**What you need**
- A small Linux VM: **2 vCPU, 4 GB RAM, ~40 GB disk, Ubuntu 24.04 LTS** (any provider; check current prices — a VM of this size is
  typically a few euros/dollars a month). 4 GB is a starting point because the pipeline's peak memory is unmeasured.
- A **domain name** (or a subdomain, e.g. `greenspace.yourdomain.org`) with an **A record pointing to the server's IP**.
- SSH key access to the server.

**Steps**
1. Secure the server: SSH keys only, firewall allowing only ports **22, 80, 443** (`ufw allow 22,80,443/tcp && ufw enable`),
   automatic security updates (`unattended-upgrades`).
2. Install Docker Engine (official docs: docs.docker.com/engine/install/ubuntu) and Docker Compose plugin.
3. Get the code onto the server (`git clone` your repository).
4. Configure:
   ```bash
   cp deploy/.env.example deploy/.env
   nano deploy/.env        # SITE_ADDRESS=greenspace.yourdomain.org   CORS_ORIGINS=https://greenspace.yourdomain.org
   ```
5. Start: `make prod-up` (or the full `docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build`).
6. Caddy obtains the HTTPS certificate automatically on first request (DNS must already point at the server).
7. Wait for the first data load (`make prod-logs`), then open `https://greenspace.yourdomain.org`.

**Private instead of public?** Either keep `SITE_ADDRESS=:80` and reach it over a VPN / SSH tunnel (`ssh -L 8080:localhost:80 server`),
or enable the `basic_auth` block in `deploy/Caddyfile`.

---

## Step 3 — Operate it

| Task | Command |
|---|---|
| Deploy a new version | `git pull && make prod-up` |
| See what is running | `make prod-status` · `make prod-logs` |
| Refresh the data now | `make prod-load` (the scheduler does it every 30 days by itself) |
| Check the live run | `curl https://<domain>/api/v1/meta` |
| Roll back to an older run | edit `latest.json` in the data volume: `docker compose -f deploy/docker-compose.yml --env-file deploy/.env run --rm --entrypoint sh pipeline -c 'ls /data/runs/barcelona; echo "{\"run_id\": \"<OLD_RUN_ID>\"}" > /data/runs/barcelona/latest.json'` |
| Back up | the data is reproducible from the public APIs, but to keep published runs: `docker run --rm -v greenspace_data:/data -v $PWD:/backup alpine tar czf /backup/greenspace-data.tgz /data` |

**Monitoring (free tier of any uptime service is enough)**
- Check `https://<domain>/api/ready` every 5 minutes: it returns 503 when no run is published.
- The same response contains **`data_age_days`**: alert if it exceeds ~45 days (the scheduler is stuck or Overpass keeps failing).
- A failed refresh never replaces the live data; look at `docker compose ... logs scheduler` and the `*.failed` run folder
  (`checks.json`, `error.txt`). See `docs/RUNBOOK.md`.

---

## Step 4 — Before announcing it

**Security (the app handles no personal data and has no login, so the surface is small)**
- [ ] only ports 22/80/443 open; SSH password login disabled
- [ ] `CORS_ORIGINS` set to your domain, or deliberately `*`
- [ ] API and dashboard are not exposed directly (only Caddy publishes ports) — true in the shipped compose file
- [ ] containers run as a non-root user with dropped capabilities — true in the shipped compose file
- [ ] **No rate limiting yet.** For a public launch put Cloudflare (free tier) in front, or add a rate-limit module to Caddy
- [ ] Caddy's access logs contain visitor IP addresses — mention this in a privacy note if you publish in the EU

**Legal (not legal advice; please check with whoever is responsible at your organisation)**
- [ ] **Attribution** is shown in the dashboard sidebar and on *Method & data*: Ajuntament de Barcelona – Open Data BCN (CC BY 4.0)
      and © OpenStreetMap contributors (ODbL). Keep it.
- [ ] **OpenStreetMap share-alike:** the green-space polygons are built from OpenStreetMap, and `/api/v1/layers/green` publishes them.
      If you do not want to offer a derived OSM database under the ODbL, set `EXPOSE_GREEN_LAYER=false` (the dashboard does not need it).
- [x] **Code licence:** MIT (`LICENSE`). Replace `<YOUR NAME>` in that file. The data keep their own licences (CC BY 4.0, ODbL).

**Content**
- [ ] A domain expert (urban planner / GIS) has reviewed the method and the ranking of the 10 best and 10 worst barris
- [ ] The weights and thresholds are signed off (decision log: `docs/DECISIONS.md`)
- [ ] The limitations are visible to readers: straight-line distances, income is a barri average, official park layer is from 2019,
      Collserola excluded by design (Vallvidrera/Torre Baró flagged)
- [ ] A contact / feedback channel exists

## Known gaps
No rate limiting or login by default · single server (no high availability) · Docker images untested until Step 1 is done ·
pipeline memory use unmeasured · no automated deploy pipeline (deploys are `git pull && make prod-up`).

## Alternatives to a VM
| Option | Fit |
|---|---|
| **One VM + Docker Compose (this guide)** | Best fit: the design is file-based, one small server is enough, full control, lowest cost |
| Managed container platforms (Cloud Run, Fly.io, Render, Railway) | Possible, but the API/dashboard read a shared data volume; you would first move the run store to object storage |
| Streamlit Community Cloud (dashboard only) | Free, but the API must still be hosted publicly somewhere else |
