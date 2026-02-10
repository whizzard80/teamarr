# Agent Instructions - Teamarr

## Overview

Sports EPG generator. Uses **bd (beads)** for issue tracking. Start with `bd ready`.

## CRITICAL: Database Safety

**NEVER delete `teamarr.db` or `data/teamarr.db`.** The database contains user-configured teams, templates, settings, and history that cannot be recreated. Schema changes use migrations (`INSERT OR REPLACE`, `ALTER TABLE`) - deleting the database is NEVER required and will cause data loss.

**Stack**: Python 3.11+, FastAPI, SQLite | Frontend: React + TypeScript + Vite + Tailwind

## Start of Session

1. Re-read this file and follow it exactly
2. Switch to `dev` branch: `git checkout dev && git pull`
3. Check for work: `bd ready`

If you forget this workflow after a context compaction, re-read this file before continuing.

## Local Testing

Run `./dev.sh` to start both servers in one terminal:

```bash
./dev.sh                 # fast restart — skips cache refresh
./dev.sh --update-cache  # restart with full cache refresh
```

- **Backend** (FastAPI): `http://localhost:9195` — Python venv, `app.py`
- **Frontend** (Vite HMR): `http://localhost:5173` — proxies `/api` → `:9195`

Use `:5173` during development for hot-reload. `Ctrl+C` stops both.
Re-running `./dev.sh` kills existing servers first, so it doubles as a restart.

By default the script skips the startup cache refresh for fast restarts. Pass `--update-cache` when you need fresh team/league data from providers. Cache can also be refreshed manually via the UI button.

**Always use `./dev.sh` to start or restart the dev environment.** It handles cleanup of old processes automatically.

**When to restart:**
- After making backend (Python) code changes
- If Playwright browser automation can't connect to `localhost:5173`
- After schema or configuration changes

## Quick Reference Commands

```bash
bd ready                              # Find available work
bd show <id>                          # View issue details
bd update <id> --status in_progress   # Claim work
bd close <id>                         # Complete work
bd sync                               # Sync beads data
```

## Development Workflow

**Critical:** Work from `dev` branch, not `main`.

### Development Steps

1. **Check for work**: `bd ready` or `bd list`
2. **Claim work**: `bd update <id> --status in_progress`
3. **Implement the change**
4. **Run quality gates** (MANDATORY when shipping):
   ```bash
   ruff check teamarr/
   pytest tests/ -v
   cd frontend && npm run build
   ```
5. **Close the bead**: `bd close <id>`
6. **Push to dev** (MANDATORY):
   ```bash
   git add <changed-files>
   git commit -m "Brief description"
   git push origin dev
   ```

**Critical shipping rules:**
- Work is incomplete until `git push` succeeds
- Never stop before pushing—it leaves work stranded locally
- Never say "ready to push when you are"—YOU must push

### Roadmap & Feature Planning

Use beads epics to plan larger features:

```bash
bd create "Feature name" --type epic --label roadmap
bd create "Implementation step 1" --parent <epic-id>
bd create "Implementation step 2" --parent <epic-id>
bd dep add <step2-id> <step1-id>    # step 2 blocked by step 1
```

When asked to plan a feature, create an epic with implementation beads that have proper blockers and predecessors. Use `bd list --label roadmap` to see the roadmap.

### Release Workflow (`/release`)

When the user says **"release"**, **"/release"**, or **"version bump"**, execute this workflow:

1. **Determine scope** — `git log upstream/main..upstream/dev --oneline` to see all commits in the release
2. **Ask version** — suggest patch (x.y.Z) vs minor (x.Y.0) based on scope. User decides.
3. **Quality gates** (MANDATORY):
   ```bash
   source .venv/bin/activate
   ruff check teamarr/
   pytest tests/ -v
   cd frontend && npm run build
   ```
4. **Version bump** — edit `pyproject.toml` line 7, commit "Bump version to x.y.z"
5. **Push dev** — push to both origin and upstream dev
6. **Merge to main** — fast-forward merge:
   ```bash
   git checkout main && git pull upstream main
   git merge dev --no-edit
   git push upstream main && git push origin main
   git checkout dev
   ```
7. **Create GitHub release** — `gh release create v<version> --repo Pharaoh-Labs/teamarr --target main` with summarized release notes (not commit-by-commit — group into categories)
8. **Generate Discord changelog** — use the Release Template below, output ready to paste
9. **Update plans/STATUS.md** — add release to changelog, update version

**Rules:**
- Never release with failing tests or lint errors
- Release notes should be human-readable summaries, not raw commit messages
- Group related commits into single bullet points

## Changelog Format

When asked for a changelog, **always** produce Discord-ready markdown. Two templates:

### Dev Push Template

Get version from `pyproject.toml` line 7, append `-dev+<short_hash>` of HEAD commit.

```
## 🚀 v<version>-dev+<hash> — <YYYY-MM-DD>

🐛 **Bug Fixes**
- <one-liner> (`hash`)

✨ **New Features**
- <one-liner> (`hash`)

⚡ **Enhancements**
- <one-liner> (`hash`)

🎨 **UI/UX**
- <one-liner> (`hash`)

🔧 **Under the Hood**
- <one-liner> (`hash`)
```

### Release Template

```
## 🎉 v<version> — <YYYY-MM-DD>

🐛 **Bug Fixes**
- <one-liner>

✨ **New Features**
- <one-liner>

⚡ **Enhancements**
- <one-liner>

🎨 **UI/UX**
- <one-liner>

🔧 **Under the Hood**
- <one-liner>
```

### Rules
- Discord markdown (## headers, **bold**, \`code\`)
- Categories (in order): 🐛 Bug Fixes, ✨ New Features, ⚡ Enhancements, 🎨 UI/UX, 🔧 Under the Hood
- **Omit empty categories** — only include sections that have items
- Dev pushes include commit hashes; releases do not
- Each item is one concise line — no multi-line descriptions
- No extra commentary — just the changelog block ready to paste

## Git Remotes & Preferences

**Two remotes:**
| Remote | Repo | Purpose |
|--------|------|---------|
| `origin` | `Pharaoh-Labs/teamarrv2` | Staging repo for syncing local work |
| `upstream` | `Pharaoh-Labs/teamarr` | Public repo: dev releases for testers, mainline releases |

**Rules:**
- Push to `origin dev` only (never push to `upstream` unless explicitly asked)
- Upstream pushes happen in batches for dev releases
- No commit watermarks or co-authored-by
- Concise, focused commit messages

## Documentation Updates

When making changes, update relevant documentation:

| Change Type | Update |
|-------------|--------|
| New template variable | Add to `teamarr/templates/variables/` docstring |
| New API endpoint | Update route docstring |
| Schema change | Bump version in `schema.sql` comment |
| New provider | Update Architecture section in this file |
| Config/settings change | Update README.md if user-facing |
| New feature | Consider adding to README Features section |

Documentation epic: `bd list --parent teamarrv2-nv4`

## Single Source of Truth

| What | Where |
|------|-------|
| Version | `pyproject.toml` line 7 |
| Dependencies | `pyproject.toml` |
| League configs | `teamarr/database/schema.sql` |
| Schema version | `teamarr/database/schema.sql` (v46) |
| Provider registration | `teamarr/providers/__init__.py` |

## Architecture

```
API Layer        → teamarr/api/routes/ (18 modules)
Consumer Layer   → teamarr/consumers/ (orchestrator, team_epg, event_epg, cache/, lifecycle/, matching/)
Service Layer    → teamarr/services/sports_data.py
Provider Layer   → teamarr/providers/ (espn, hockeytech, cricket_hybrid, tsdb)
```

**Providers** (lower priority = tried first):
- ESPN (0) - Primary, most leagues
- HockeyTech (50) - CHL, AHL, PWHL, USHL
- CricketHybrid (55) - Cricket
- TSDB (100) - Fallback

## Key Subsystems

**Template Engine** (`teamarr/templates/`):
- 165 variables in `variables/` (16 categories)
- 16 condition evaluators in `conditions.py`
- Suffix rules: `.next`, `.last` for multi-game scenarios

**Dynamic Groups** (`teamarr/consumers/lifecycle/dynamic_resolver.py`):
- `{sport}` and `{league}` wildcards
- Auto-creates in Dispatcharr

## Plans & Roadmap

Feature planning lives in beads: `bd list --label roadmap`

Legacy plans in `plans/` (gitignored) may have additional context.

## Code Health Audit (`teamarrv2-5hq`)

**Cyclical epic for keeping the codebase clean.** Run with: `audit`

When the user says **"audit"**, claim the next open child bead under `teamarrv2-5hq` and run the full audit:

1. **Dead API endpoints** — cross-reference every route in `teamarr/api/routes/` against the ENTIRE `frontend/src/` directory (not just `api/` — the frontend uses both structured api clients AND direct `fetch()` calls in pages/components) and backend callers. Only flag as dead if zero hits across all search patterns.
2. **Dead frontend code** — find unused exports in `frontend/src/api/`, `frontend/src/hooks/`, `frontend/src/components/`. Check for dynamic imports and lazy loading in `App.tsx` before flagging components as dead.
3. **Layer separation** — routes should only do request/response; no direct DB queries (`conn.execute`, `cursor`) in routes. Business logic belongs in services/consumers.
4. **Code quality** — god functions (200+ lines), deep nesting (4+ levels), inconsistent logging, magic numbers.
5. **Frontend hygiene** — unused components, dead hooks, stale API client functions.

6. **Test coverage before pruning** — before removing ANY code marked for pruning, verify:
   - Run `pytest tests/ -v` to confirm all existing tests pass first.
   - Search for callers/importers one more time (grep the entire codebase, not just obvious locations).
   - Check git blame — if code was added recently, it may be WIP or needed for an upcoming feature. Ask the user before removing.
   - After pruning, run `pytest tests/ -v` again and `cd frontend && npm run build` to confirm nothing broke.
   - If removing an API endpoint, also check for external consumers (Dispatcharr callbacks, webhook URLs, cron jobs calling the API).
   - **Never prune comments that explain WHY something works a certain way** — only remove commented-out dead code.
   - When in doubt, leave it and mark with `# TODO: PRUNE? — verify with user` instead of removing.

**Evaluation principles (apply these when deciding if code is dead or pruneable):**
- **"Zero callers" is necessary but not sufficient.** Also ask: does removing it lose any capability? If another endpoint/function covers the same functionality, it's safe. If it's the only way to do something, be cautious even if nothing calls it today.
- **Duplicate endpoints:** When GET and POST versions exist doing the same thing, the POST (superset — accepts optional body) is the keeper. The GET adds no unique capability.
- **Consider external consumers** that won't show up in code search: browser bookmarks, monitoring scripts, curl commands, Dispatcharr callbacks, Docker healthchecks, cron jobs. GET endpoints are especially exposed since they're URL-accessible.
- **Frontend has two calling patterns:** structured api clients (`frontend/src/api/*.ts`) and direct `fetch()` calls in pages/components. Always search the ENTIRE `frontend/src/` for URL path strings.
- **Never trust automated dead-code detection without manual verification.** The Q1 2026 audit had a high false-positive rate because agents only searched api client files, missing direct `fetch()` calls.
- **"Is it called?" is the wrong question. "Would we lose capability?" is the right one.**

**Ongoing responsibilities (during normal development):**
- When you encounter dead code while working on features/bugs, mark it with `# TODO: PRUNE — <reason>` immediately.
- When you notice layer violations or code smell, add `# TODO: REFACTOR — <reason>`.
- These TODO markers get cleaned up during the next audit cycle.
- After each audit, update these evaluation principles with any new lessons learned.
- Create the next child bead (e.g., `Code Health Audit — Mar 2026`) when closing the current one.

**Audit epic details:** `bd show teamarrv2-5hq`

## Sync Status

When asked to **"sync status"** or **"update status"**:

1. Query GitHub issues: `gh issue list --state all --limit 50`
2. Query GitHub PRs: `gh pr list --state all --limit 20`
3. Read PR/issue comments for context: `gh api repos/Pharaoh-Labs/teamarr/issues/<id>/comments`
4. Query beads: `bd list`, `bd list --label roadmap`
5. Cross-reference issues ↔ beads (check which issues have epics, which don't)
6. Update `plans/STATUS.md` with:
   - Open issues table (with bead mapping)
   - Open PRs table (with status/notes)
   - Roadmap epics (ready vs blocked)
   - Issues needing beads
   - Recently closed items
   - Change log entry with date
7. Present summary and recommend next steps

## Adding a New League

Add to `INSERT OR REPLACE INTO leagues` in `teamarr/database/schema.sql`. Restart to apply.

## Common Commands

```bash
source .venv/bin/activate
python3 app.py                    # Run on port 9195
pytest tests/ -v                  # Run tests
ruff check teamarr/               # Lint
ruff format teamarr/              # Format
cd frontend && npm run build      # Build frontend
```

## Logging

**Configuration:** `teamarr/utilities/logging.py`

**Log directory detection** (in priority order):
1. `LOG_DIR` env var (if set)
2. `/app/data/logs` (if `/app/data` exists - Docker or host with `/app`)
3. `<project_root>/logs` (local dev fallback)

**IMPORTANT:** On this dev machine, `/app/data/` exists at the system level, so both Docker AND local dev write to `/app/data/logs/` (not `./data/logs/`).

**Log files:**
| File | Contents |
|------|----------|
| `teamarr.log` | Main log (rotating 10MB x 5) |
| `teamarr_errors.log` | Errors only (rotating 10MB x 3) |

**View recent logs:**
```bash
tail -n 100 /app/data/logs/teamarr.log      # On this dev machine
tail -n 100 ./data/logs/teamarr.log         # Standard Docker setup
docker logs --tail 100 teamarr              # Docker container stdout
```

**Environment variables** (set in docker-compose.yml):
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR (default: INFO for console, DEBUG for files)
- `LOG_FORMAT`: "text" or "json" (default: text)
- `LOG_DIR`: Override log directory path

**Note:** `./data/logs/` in the project directory contains stale V1 logs from Dec 2025 - these can be deleted.

## MCP Servers

**Playwright** (`@playwright/mcp`) - Browser automation for testing UI, capturing screenshots, verifying frontend changes. Tools available:
- `browser_navigate` - Navigate to URL
- `browser_click` - Click elements
- `browser_type` - Enter text in fields
- `browser_snapshot` - Get accessibility tree (preferred over screenshots)
- `browser_screenshot` - Capture page screenshot

Use for: Visual verification of UI changes, testing frontend flows, debugging styling issues.

