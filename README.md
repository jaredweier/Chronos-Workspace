# Dodgeville Police Department Scheduler

A desktop application for managing 24/7 shift schedules, day-off requests, shift swaps, and payroll for the Dodgeville Police Department.

**Project status, recent changes, and resume guide:** see [`docs/PROJECT_README.md`](docs/PROJECT_README.md).
**Agent session handoff:** see [`docs/HANDOFF.md`](docs/HANDOFF.md).
**Full project dump (single file):** [`docs/FULL_PROJECT_CODE.txt`](docs/FULL_PROJECT_CODE.txt) — source, database, build/cache (~29 MB; binaries base64; `dist/` omitted). Regenerate: `python scr[...]`
**Multi-PC deployment:** [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — shared network install for up to 8 computers; launcher in [`docs/deploy/`](docs/deploy/).

## 🌐 Remote Access via Cloudflare

Share your scheduler securely with officers using your Cloudflare domain:

- **[Cloudflare Tunnel Setup Guide](TUNNEL_SETUP.md)** — Access your scheduler from anywhere without port forwarding
- **Quick start (macOS/Linux):** `bash tunnel-setup.sh`
- **Quick start (Windows):** `tunnel-setup.bat`

## Project Structure

```
Dodgeville_PD_Scheduler/
├── main.py
├── logic.py
├── database.py
├── models.py
├── config.py
├── cli.py
├── build.bat
├── requirements.txt
├── README.md
├── logo.png
└── dodgeville_scheduler.db
```

## Features

- 14-day rotating schedule (2-2-3-2-2-3 pattern)
- Cascading bumping logic with night minimum protection
- Shift swap requests with conflict detection
- Full Payroll system (Overtime, Holiday Pay 2.5x/3.0x, Night Differential)
- Officer Profile management with photo upload
- Gantt Timeline and Monthly Schedule views
- Notifications system
- Admin CLI tool

## How to Run

```bash
pip install -r requirements.txt
python main.py
```

## Admin CLI

```bash
# List officers
python cli.py officers list

# Add new officer
python cli.py officers add --name "John Doe" --seniority 4 --squad A --shift-start "06:00" --shift-end "17:00"

# View pending requests
python cli.py requests pending

# Approve a request
python cli.py requests approve 15

# Backup database
python cli.py backup
```
