# openclaw-media-request

An [OpenClaw](https://openclaw.ai) skill that turns "get me The Bear, season 3" into a
Radarr/Sonarr request — lookup with disambiguation, add with the right quality profile and
root folder, targeted season search, and download status in plain words.

Standard library only. One script, JSON out.

## Why not just call the Radarr/Sonarr API?

Because the failure modes of a naive integration are expensive: adding the wrong "Dune",
adding a fifteen-season show when one season was asked for, re-adding something already in
the library and getting an opaque 400. The rules in [SKILL.md](SKILL.md) exist to prevent
exactly those.

## Install

```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/GrewingM/openclaw-media-request media-request
```

Add the keys to the gateway environment (e.g. `~/.openclaw/gateway.systemd.env`):

```
RADARR_API_KEY=…
SONARR_API_KEY=…
# optional
RADARR_URL=http://localhost:7878
SONARR_URL=http://localhost:8989
RADARR_QUALITY_PROFILE=HD-1080p
SONARR_QUALITY_PROFILE=HD-1080p
RADARR_ROOT=/shield/MOVIES
SONARR_ROOT_TV=/shield/TV-SHOWS
SONARR_ROOT_ANIME=/shield/ANIME
```

and enable the skill in `openclaw.json`:

```json
"media-request": { "enabled": true, "env": { "RADARR_API_KEY": "${RADARR_API_KEY}", "SONARR_API_KEY": "${SONARR_API_KEY}" } }
```

Test from a shell:

```bash
python3 scripts/media.py --text lookup movie "inception"
python3 scripts/media.py --text queue
```

Plex: configure Radarr → Settings → Connect → Plex Media Server (and the same in Sonarr) with
*Update Library* on import, so new downloads appear without a manual scan.

## Commands

| Command | Does |
|---|---|
| `lookup movie\|series "<term>" [--limit 3]` | candidates with year, `inLibrary`, ids — no changes |
| `add movie <tmdbId> [--profile] [--root]` | add + search; returns status instead if already present |
| `add series <tvdbId> --seasons 1\|1-3\|2,4\|latest\|all [--anime]` | add with only those seasons monitored, `SeasonSearch` per season |
| `status movie\|series --id <n> \| --term "<t>"` | on-disk state + anything downloading for it |
| `queue` | both download queues with percent and time left |
| `recent movie\|series` | last imports |
| `remove movie\|series <id> [--delete-files]` | remove; files kept unless asked |

Tested against Radarr 5 / Sonarr 4 (`/api/v3`). `languageProfileId` is not used — it no
longer exists in current versions.

## Credits

The idea of a stdlib-only Radarr/Sonarr skill and the shape of the API clients come from
[melionka/radarr-sonarr](https://github.com/melionka/radarr-sonarr) (MIT). This is a
rewrite rather than a fork: different agent contract, season handling, disambiguation and
library-aware adds.

## Licence

MIT — see [LICENSE](LICENSE).
