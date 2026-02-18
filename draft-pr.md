# PR: European Soccer & Stream Matching Improvements

**Branch:** `feature/eu-soccer-dispatcharr` → `main`
**Base:** upstream `Pharaoh-Labs/teamarr` @ `v2.2.0`

## Summary

Significantly improves stream matching for European football (soccer) and international sports streams. The upstream build struggles with EU provider stream formats — different date conventions (DD/MM vs MM/DD), league-prefixed naming, symbol characters, and provider suffixes that break team extraction. These changes bring match rates from near-zero to functional for Ligue 1, Bundesliga, La Liga, Serie A, UEFA competitions, and other international streams.

---

## Changes by File

### `teamarr/consumers/matching/normalizer.py`
**European date handling and stream cleanup**

- Added `prefer_day_first` logic for DD/MM vs MM/DD ambiguity — European football streams use DD/MM format, upstream always assumed MM/DD (US convention), causing date mismatches and missed matches
- Added `_is_day_first()` helper that uses unambiguous values first (e.g., 15/02 is obviously DD/MM), falls back to soccer context hints
- Added `_SOCCER_DATE_HINTS` regex to detect European football context in stream names and prefer DD/MM parsing
- Added date pattern for weekday-prefixed European dates: "Saturday, 23 August 2025 20:30"
- Added date patterns with explicit year for `DD Month YYYY` and `Month DD YYYY` formats
- Added time pattern for unusual `9:pm` / `9:PM` format (common in some IPTV providers)
- Added stripping of symbol characters (®, Ⓡ, ™, ℠) that break parsing — EU streams often use "Bundesliga 06®:" or "La Liga 04®:"
- Added `_TEAM_NOISE_TOKENS` set (fc, cf, ac, sc, afc, ssc) and removal in `normalize_for_matching()` to reduce noise in fuzzy matching

### `teamarr/consumers/matching/classifier.py`
**Better team extraction from EU stream formats**

- Added `extract_teams_from_time_mask()` — extracts teams when time sits between them (e.g., "Napoli TIME_MASK Chelsea")
- Added Step 5 in `classify_stream()` to use time-mask extraction as fallback when no game separator is found
- Added provider suffix stripping in `_clean_team_name()` — removes trailing ":ESPN+ 10", "DAZN", "SKY SPORTS", "BEIN SPORTS", etc. that were polluting team names
- Added European league prefix stripping — handles "Ligue 1 01:", "Bundesliga 07x:", "Serie A 08:", "La Liga 04:", "2. Bundesliga:" etc.
- Added country code + league prefix stripping — handles "IT UEFA Champions League HD", "DE NFL Game Pass", "FR Ligue 1" formats
- Added "Event N |" prefix stripping for multi-sport channels — "DE - Event 12 | NFL | Dolphins"
- Added broadcast prefix stripping — "HNIC IN PUNJABI", "En Español"
- Added datetime noise detection after pipe separators — strips "| Saturday, DATE_MASK 2025 TIME_MASK" suffix from team names
- Added fighter name cleanup: trailing time suffixes, rematch numbers, BACKUP/SD/HD suffixes, provider suffixes

### `teamarr/consumers/matching/team_matcher.py`
**Softer date handling, cleaner matching**

- Changed date mismatch from hard exclusion (`continue`) to a score penalty (`DATE_MISMATCH_PENALTY = 15.0`) — prevents streams with slightly wrong dates from being completely ignored when they're clearly the right event
- Always apply sport hint filtering regardless of league hint presence — upstream skipped sport check when league hint was present, causing cross-sport false positives
- Removed `_check_abbreviation_match()` method — produced false positives with 3-letter abbreviation token matching (e.g., "SWE" matching noise tokens)
- Reordered `MatchContext` fields for clarity

### `teamarr/consumers/matching/constants.py`
**New matching constant**

- Added `DATE_MISMATCH_PENALTY = 15.0` — used by team_matcher to penalize rather than exclude date mismatches

### `teamarr/utilities/constants.py`
**Extended team aliases, separators, and league/sport hints**

- Added Spanish team aliases: Girona FC, Levante UD, RCD Espanyol, Valencia CF, CA Osasuna
- Added German team alias: 1. FC Köln / FC Cologne
- Added `" VS "` (uppercase) and `" - "` (dash) as game separators
- Added `"March Madness"` as league hint for `mens-college-basketball`
- Added UEFA Europa League and Conference League hint patterns (uel, uecl, etc.)
- Added Motorsport sport hints (Formula 1, NASCAR, IndyCar, MotoGP, etc.) to detect and filter non-matchable racing streams

### `teamarr/services/stream_filter.py`
**Motorsport filtering**

- Added "Motorsport" to `UNSUPPORTED_SPORTS` — racing has no team-vs-team matchups
- Added dash separator `" - "` to `BUILTIN_EVENT_PATTERNS`

### `teamarr/templates/variables/identity.py`
**New template variable**

- Added `{league_logo}` variable — returns league logo URL from ESPN CDN, useful for channel logos in Dispatcharr

### `teamarr/services/league_mappings.py`
**League logo support**

- Added `_league_logos` cache and `get_league_logo()` method to serve `{league_logo}` variable
- Loads `logo_url` from league_cache during mapping initialization

### `teamarr/consumers/event_group_processor.py`
**Stream timezone support**

- Added `stream_timezone` parameter passthrough to matcher — enables per-group timezone configuration for interpreting stream dates

### `teamarr/api/routes/settings/stream_filter.py` *(new file)*
**Stream filter settings API**

- New GET/PUT endpoints for global stream filter settings
- Allows UI configuration of default event pattern requirements and include/exclude patterns

### `teamarr/api/routes/settings/models.py` *(new file)*
**API models for stream filter settings**

- Pydantic models for stream filter settings request/response

### `teamarr/api/routes/settings/__init__.py`
**Route registration**

- Added stream filter router to settings API

### Frontend Changes
- `frontend/src/pages/Settings.tsx` — Added stream filter settings UI section
- `frontend/src/api/settings.ts` — API client functions for stream filter endpoints
- `frontend/src/hooks/useSettings.ts` — React hook for stream filter settings
- `frontend/src/components/LeaguePicker.tsx` — Enhanced league picker UI
- Various component cleanups and fixes for pattern state properties

### Other Backend Changes
- `teamarr/consumers/generation.py` — Refactored generation pipeline
- `teamarr/consumers/lifecycle/service.py` — Channel lifecycle improvements
- `teamarr/utilities/cache.py` — Cache improvements
- `teamarr/utilities/xmltv.py` — XMLTV generation fixes
- `teamarr/dispatcharr/client.py` — Client improvements
- `teamarr/database/connection.py` — Connection handling updates

---

## Impact

These changes primarily benefit users with European IPTV providers whose stream naming conventions differ significantly from US providers. The upstream matching engine was optimized for US sports (ESPN-style naming), leaving EU soccer streams largely unmatched. With these changes, streams like:

- `Ligue1 02®: AS Monaco vs. FC Nantes | Friday, 13 February 2026 20:05`
- `Bundesliga 07x: Hamburger SV vs FC Bayern München | Saturday, 14/02/2026 15:30`
- `IT UEFA Champions League HD & Napoli 20:45 Chelsea 11/02`

...are now correctly parsed, classified, and matched to ESPN events.
