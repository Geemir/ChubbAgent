# Internal Demo Deployment — Windows machine + LAN

Goal: run ChubbAgent on **your Windows machine** and let colleagues on the **same office
network** open it at `http://<your-LAN-IP>:8000`. No authentication (internal demo).

> Access is **unauthenticated** and open on the intranet — fine for a short demo. For
> anything longer-lived, put it behind a reverse proxy with Basic Auth (see the end).

---

## Option A — Native run (recommended for a quick demo, no Docker needed)

This is exactly what we've already verified running; it needs only `uv` + Python.

```bash
cd D:/2026.7Intern/ChubbAgent

# 1. Populate demo data (6 competitors, prices, trends, AI reports)
PYTHONUTF8=1 py -m uv run chubb-ci seed-demo

# 2. Serve on ALL interfaces so the LAN can reach it (note: 0.0.0.0, not 127.0.0.1)
PYTHONUTF8=1 py -m uv run chubb-ci dashboard --host 0.0.0.0 --port 8000
```

On first launch, Windows Defender Firewall will prompt **"Allow python to communicate on
private networks"** → click **Allow**. (Or pre-create the rule — see *Firewall* below.)

Leave that terminal open for the duration of the demo. `Ctrl+C` stops it.

---

## Option B — Docker Compose (reproducible; runs scheduler + dashboard)

Requires **Docker Desktop for Windows** (WSL2 backend) installed and running.

```bash
cd D:/2026.7Intern/ChubbAgent

# Build + start the dashboard (add nothing to also start the scheduler)
docker compose up dashboard --build -d       # dashboard only
# docker compose up --build -d               # dashboard + scheduler

# Populate demo data inside the shared ./data volume
docker compose run --rm dashboard uv run chubb-ci seed-demo
```

Compose already publishes `8000:8000` on all interfaces, so LAN access works the same way.
Stop with `docker compose down` (data persists in `./data`).

---

## Share it on the LAN

1. **Find your machine's LAN IP:**
   ```bash
   ipconfig        # look for "IPv4 Address" on your active adapter, e.g. 192.168.1.42
   ```
2. **Open the firewall port** (if you didn't click "Allow" on the prompt). In an
   **Administrator** PowerShell / CMD:
   ```powershell
   netsh advfirewall firewall add rule name="ChubbAgent 8000" dir=in action=allow protocol=TCP localport=8000
   ```
3. **Send colleagues:** `http://192.168.1.42:8000`  (your IP, not localhost).

> Colleagues must be on the **same network** (office LAN / Wi‑Fi / VPN). Guest Wi‑Fi or a
> different VLAN may be isolated and unable to reach your machine — test with one person first.

---

## Populate data

| Command | Result |
|---|---|
| `chubb-ci seed-demo` | Rich demo: 6 CN competitors, prices, promotions, trend history, AI reports |
| `chubb-ci crawl --kind daily` | Real crawl of the live 官网 (永发 + 迪堡); then `chubb-ci report --daily` for the AI summary |
| **运行抓取** button (top bar) | Triggers a live crawl during the demo |

For a clean walkthrough, `seed-demo` gives the fullest dashboard (real 官网 have no prices,
so a real-only DB shows product line-ups but empty price/promo charts).

---

## Keep the machine awake during the demo

```powershell
powercfg /change standby-timeout-ac 0     # don't sleep on AC power
powercfg /change monitor-timeout-ac 0     # (optional) don't blank the screen
```

---

## Notes & caveats

- **Not on Vercel / public cloud on purpose.** ChubbAgent is a stateful service (SQLite
  file DB + long-running scheduler + crawler/Playwright) and the data is internal
  competitive intelligence — it belongs on an internal host, not a serverless public PaaS.
- **Secrets:** `.env` holds your DeepSeek key and is gitignored. Don't copy the folder
  with `.env` to anyone.
- **Scheduled crawls** (02:30 daily / Mon 03:00) won't fire during a short demo — use
  `seed-demo` or the **运行抓取** button.
- **The preview/dev server** we've been using binds `127.0.0.1` (local only). For the LAN
  demo you must bind `--host 0.0.0.0` as shown above.

### Later: add Basic Auth (if this outlives the demo)

Put Caddy in front (one line does TLS + auth). Example `Caddyfile`:
```
chubbagent.local {
    basic_auth { marketing <bcrypt-hash> }
    reverse_proxy 127.0.0.1:8000
}
```
Then run `caddy run` and point an internal DNS name at the host. Ask me and I'll wire it up.
