---
name: build-deploy
description: Frozen builds/launchers — PyInstaller, dist/, Start Scheduler.bat. Use when user needs .exe or can't see updates.
---

# Build & Deploy Subagent

## Source vs frozen (critical user gotcha)

**Latest code always runs from project root:**

```bash
python main.py
# or
Start Scheduler.bat
```

**Stale copies** (do not use unless rebuilt):

- `dist\Dodgeville_PD_Scheduler\Dodgeville_PD_Scheduler.exe`
- `C:\Users\Windows\Dodgeville_PD_Scheduler_Frozen_*`

## Build commands

| Script | Purpose |
|--------|---------|
| `build_quick.bat` | PyInstaller onedir, skip tests, copy launcher |
| `build_test.bat` | Full build with `dev.py check` first |
| `build.bat` | Production build |
| `scripts/build_frozen_eval.py` | Evaluation package helper |

## Required assets (project root)

- `logo.png`
- `team_photo.jpg`
- `roster_seed.json`

PyInstaller `--add-data` bundles these; `paths.resource_path()` resolves at runtime.

## Launchers

| File | Target |
|------|--------|
| `Start Scheduler.bat` | `python main.py` from project root |
| `docs/deploy/Start Dodgeville Scheduler (Local).bat` | Local dev |
| Desktop `Start Dodgeville Scheduler (Latest).bat` | Points to MyProject |

## Workflow

1. Confirm user runs **source** not old `.exe`
2. `python dev.py doctor` â€” assets and deps OK
3. `python dev.py check` before eval build
4. `build_quick.bat` or `build_test.bat`
5. Copy `Start Dodgeville Scheduler.bat` into `dist\`
6. Tell user exact path to new `.exe`

## Do not

- Point users to `\\PD-SERVER\...` network paths for local dev
- Ship frozen build without bundled images
- Change `main.py` entry â€” always `ui.app.run()`
