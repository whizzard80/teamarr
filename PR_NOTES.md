# European Football & Combat Sports Matching Improvements

> ⚠️ **Draft PR** - AI-assisted development with Claude (Anthropic) via Cursor IDE

## Summary

This PR improves stream-to-event matching for European football (soccer), UFC, and boxing streams. The changes address parsing issues with common IPTV provider stream name formats that were causing match failures. Additionally, it adds professional EPG filler content with program artwork and game times.

## Changes

### Stream Matching Improvements (`teamarr/consumers/matching/`)

#### `normalizer.py`
- **Added DATE_MASK_WITH_YEAR patterns** - Captures full European-style dates like `23 August 2025` instead of leaving the year behind
- **Added TIME_PATTERN for unusual formats** - Handles `9:pm` format (colon before am/pm) common in some IPTV providers

#### `classifier.py`
- **Enhanced pipe handling** - Strips datetime suffix from team names when format is `Team | Day, Date Time`
  - Before: `FC Barcelona | Saturday, DATE_MASK 2025` → Team2 = broken
  - After: `FC Barcelona` → Team2 = correct
- **Improved fighter name cleaning** - Strips trailing time, fight/rematch numbers, BACKUP/SD tags, and provider suffixes from UFC/boxing streams

### EPG Filler Improvements

#### `database/templates.py`
- **Default channel name format** - When template fields are NULL, use `{away_team} @ {home_team}` instead of empty string
- **Prevents empty display-name tags** in XMLTV output

#### Database Templates (via SQL)
- **All templates updated** with `program_art_url` using jesmann.com sports logos
- **Pregame filler** now shows: "Game Starting at 7:30 PM EST" (includes actual game time!)
- **Postgame filler** shows: "Game Complete" with final score
- **Idle filler** shows upcoming game info with artwork
- **Team aliases** added for major European soccer teams (PSG, Inter, Juventus, Barcelona, Bayern Munich, etc.)

### Configuration
- **docker-compose.yml** - Configured for local development builds
- **Default timezone** - Set to America/New_York

## Test Results

### After Fix
- **Bundesliga**: 17 streams matched ✅
- **Serie A**: 12 streams matched ✅
- **La Liga**: 12 streams matched ✅
- **Premier League**: 23 streams matched ✅
- **Ligue 1**: 9 streams matched ✅
- **UEFA Champions League**: 8 streams matched ✅

### UFC/Boxing
- Fighter names now cleanly extracted: Volkanovski vs Lopes
- Shakur Stevenson vs Teofimo Lopez (fully clean)

## XMLTV Output Validation
- ✅ Valid XML per xmllint
- ✅ UTF-8 encoded
- ✅ Times in UTC with explicit +0000 offset
- ✅ Compatible with Jellyfin, TVHeadend, NextPVR, Plex, Kodi

## Jellyfin Integration Notes

**Important:** When setting up the EPG source in Jellyfin, use the URL with the tvg_id_source parameter:

    http://YOUR_DISPATCHARR_IP:9191/output/epg?tvg_id_source=tvg_id

Without this parameter, Teamarr event channels won't get proper EPG data.

## Filler Content Examples

### Pregame (before game starts)
- **Title**: "Game Starting at 3:00 PM EST"
- **Subtitle**: "New Orleans Pelicans at Charlotte Hornets"
- **Description**: Full venue info with tip-off time
- **Artwork**: Professional matchup cover from jesmann.com

### Postgame (after game ends)
- **Title**: "Game Complete"
- **Subtitle**: Teams that played
- **Description**: Final score included
- **Artwork**: Professional matchup cover

## Development Notes

This PR was developed with AI assistance (Claude/Anthropic via Cursor IDE) for:
- Debugging regex patterns
- Database analysis via MCP SQLite integration
- Testing stream parsing with live data
- XMLTV validation
- Deep dive debugging across Teamarr → Dispatcharr → Jellyfin pipeline

## How to Test

1. Clone this branch
2. Run docker compose up -d --build
3. Trigger EPG generation via UI or API
4. Check match results in the Stats page
5. Verify Jellyfin shows "Game Starting at X:XX PM" instead of generic "Game Starting Soon"

---

# Suggested Documentation Additions

> The following documentation could be added to the README or user guide to help users integrate Teamarr with Dispatcharr and Jellyfin.

---

## Dispatcharr Integration Guide

Teamarr integrates with [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr) to manage IPTV channels and EPG data. This guide covers setup and best practices.

### Prerequisites

- Dispatcharr installed and running
- At least one M3U provider configured in Dispatcharr
- A dedicated user account for Teamarr (recommended)

### Initial Setup

1. **Create a Dispatcharr user for Teamarr** (optional but recommended):
   - Go to Dispatcharr → Settings → Users
   - Create a new user (e.g., `teamarr`)
   - This isolates Teamarr's API access

2. **Configure Teamarr's Dispatcharr connection**:
   - Go to Teamarr → Settings → Dispatcharr
   - Enter your Dispatcharr URL: `http://YOUR_DISPATCHARR_IP:9191`
   - Enter username and password
   - Click "Test Connection"

3. **Select Channel Profiles**:
   - In Teamarr Settings, select which Dispatcharr Channel Profiles to use
   - These determine which M3U providers Teamarr scans for sports streams

4. **Create EPG Source in Dispatcharr**:
   - Go to Dispatcharr → EPG Sources → Add
   - Name: `Teamarr`
   - URL: `http://YOUR_TEAMARR_IP:9195/api/v1/epg/xmltv`
   - Refresh: 6-8 hours
   - Note the EPG Source ID (you'll need it)

5. **Set EPG Source ID in Teamarr**:
   - Go to Teamarr → Settings → Dispatcharr
   - Enter the EPG Source ID from step 4

### How It Works

```
┌─────────────┐     Scans M3U      ┌─────────────┐
│ Dispatcharr │ ◄─────────────────► │   Teamarr   │
│   (M3U/EPG) │                     │ (EPG Gen)   │
└──────┬──────┘                     └──────┬──────┘
       │                                   │
       │  Creates/Deletes Channels         │
       │  Assigns EPG Data                 │
       │◄──────────────────────────────────┘
       │
       ▼
┌─────────────┐
│  Jellyfin   │ ◄── Pulls EPG from Dispatcharr
│  (Client)   │
└─────────────┘
```

### Recommended Refresh Schedule

| System | Setting | Recommended | Why |
|--------|---------|-------------|-----|
| **Dispatcharr** | M3U Refresh | 12-24 hours | Prevents provider rate limiting |
| **Dispatcharr** | Teamarr EPG Source | 6-8 hours | Match Teamarr's generation |
| **Teamarr** | EPG Cron | `0 */6 * * *` | Every 6 hours |
| **Teamarr** | Scheduler Interval | 30 min | Stream availability checks |
| **Jellyfin** | Guide Refresh | 4-6 hours | After Dispatcharr syncs |

**Important**: Stagger these refreshes to create a chain:
```
M3U Provider (24h) → Dispatcharr EPG (8h) → Teamarr (6h) → Jellyfin (4h)
```

---

## Jellyfin Setup

### Adding Teamarr Channels to Jellyfin

1. **Add Tuner in Jellyfin**:
   - Dashboard → Live TV → Add Tuner
   - Tuner Type: M3U
   - URL: `http://YOUR_DISPATCHARR_IP:9191/output/m3u`

2. **Add EPG Source in Jellyfin** (⚠️ Critical):
   - Dashboard → Live TV → Add Guide Provider
   - Type: XMLTV
   - **URL**: 
     ```
     http://YOUR_DISPATCHARR_IP:9191/output/epg?tvg_id_source=tvg_id
     ```

   > ⚠️ **The `?tvg_id_source=tvg_id` parameter is REQUIRED!**
   > Without it, Jellyfin won't match EPG data to Teamarr channels.

3. **Refresh the Guide**:
   - Dashboard → Scheduled Tasks → Refresh Guide → Run

### Recommended Jellyfin Settings

| Setting | Recommended | Why |
|---------|-------------|-----|
| Guide Days | 7 | Full week of events |
| Pre-padding | 5 minutes | Catch pre-game, prevent missing tip-off |
| Post-padding | 30-60 minutes | Games run over (OT, delays) |

### Troubleshooting

**Problem**: Channels show "Postgame Recap" or generic titles instead of game info

**Solutions**:
1. Verify EPG URL includes `?tvg_id_source=tvg_id`
2. Delete and re-add the EPG provider in Jellyfin
3. Force refresh the guide
4. Check Dispatcharr timezone matches your local timezone

**Problem**: Channels disappear during games

**Solutions**:
1. In Teamarr Settings, ensure `Channel Delete Timing` is set to `day_after`
2. Don't refresh M3U during game times
3. Increase Jellyfin's post-padding to 60 minutes

---

## Timezone Configuration

**All three systems should use the same timezone** for consistent EPG times.

### Teamarr
```yaml
# docker-compose.yml
environment:
  - TZ=America/New_York
```

### Dispatcharr
- Settings → General → Timezone → Select your timezone

### Jellyfin
- Dashboard → Settings → General → Display → Time zone

---

## Channel Lifecycle

Teamarr manages channels automatically based on game schedules:

| Timing | Behavior |
|--------|----------|
| **same_day** | Channels created day of the game |
| **day_before** | Channels created 24h before |
| **day_after** | Channels deleted day after game ends |

### Preventing Mid-Stream Interruptions

To prevent channels from disappearing while watching/recording:

1. Set `Channel Delete Timing` to `day_after`
2. Schedule M3U refreshes during off-peak hours (4-6 AM)
3. Use generous Jellyfin padding (60 min post-padding)

---

## EPG Filler Content

Teamarr generates professional filler content for times before/after games:

### Pregame Filler
- **Title**: "Game Starting at 7:30 PM EST"
- **Description**: Venue, teams, and tip-off time
- **Artwork**: Professional matchup graphic

### Postgame Filler  
- **Title**: "Game Complete"
- **Description**: Final score
- **Artwork**: Professional matchup graphic

### Customizing Templates

Templates can be customized in Teamarr → Settings → Templates. Available variables include:

| Variable | Example |
|----------|---------|
| `{home_team}` | Boston Celtics |
| `{away_team}` | Los Angeles Lakers |
| `{game_time}` | 7:30 PM EST |
| `{venue_full}` | TD Garden, Boston, MA |
| `{league_name}` | NBA |
| `{home_record}` | 25-14 |
| `{away_record}` | 14-17 |

---

## Common Issues & Quirks

### IPTV Provider Rate Limiting
Some providers limit how often you can refresh. Symptoms:
- "Too many attempts" errors
- 50% of streams show as "stale"
- **Solution**: Wait 1-2 hours, then manually refresh in Dispatcharr

### Multi-Sport Channels (ESPN, Sky Sports, etc.)
Static channel names (e.g., "Sky Sports 1 HD") can't be matched to specific events because the stream name doesn't contain game info.
- **Solution**: Use external EPG sources for these channels
- Disable these channels in Teamarr's event groups

### European Date Formats
Some providers use European date formats that can confuse parsing:
- `23/01/2026` vs `01/23/2026`
- This PR includes fixes for common European date patterns

### Fighter Names in UFC/Boxing
Combat sports streams often include extra info that needs stripping:
- `Volkanovski vs Lopes 2 9:pm BACKUP`
- This PR cleans these to: `Volkanovski vs Lopes`
