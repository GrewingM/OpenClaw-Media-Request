---
name: media-request
description: Request films and TV series in natural language — looks them up in Radarr/Sonarr, adds them with the right profile and root folder, starts the search, and reports download progress. Use when the user asks to get, download, add, find or check on a movie, film, series, show, season or episode.
allowed-tools: ["exec"]
user-invocable: true
metadata:
  openclaw:
    emoji: 🎬
    requires:
      bins: ["python3"]
    config:
      - id: RADARR_URL
        label: Radarr URL
        type: string
        default: "http://localhost:7878"
      - id: RADARR_API_KEY
        label: Radarr API key
        type: secret
      - id: SONARR_URL
        label: Sonarr URL
        type: string
        default: "http://localhost:8989"
      - id: SONARR_API_KEY
        label: Sonarr API key
        type: secret
---

# media-request

One script, `scripts/media.py`, talks to Radarr (films) and Sonarr (series). It prints
**one JSON object** per call; add `--text` for a one-line human summary. Exit 0 = ok,
1 = not found / ambiguous / refused, 2 = Radarr/Sonarr unreachable or not configured.

Run it as: `python3 {{skill_dir}}/scripts/media.py …`

## The rules

1. **Always `lookup` first, never guess.** Show the user the candidates with their year
   (up to 3). If more than one is plausible ("Dune" 1984 vs 2021), ask which. Only when
   there is a single obvious match, or the user already gave the year, go straight on.
2. **`add` only after the user has confirmed the title** (explicitly, or by having asked
   with enough precision). `add` starts a download — treat it as spending disk space.
3. **Series: never add "all seasons" unless the user said so.** Default to what they asked
   for; if they didn't say, ask "which season(s)?" and suggest `latest`. A long-running
   show added whole can be hundreds of GB.
4. If `lookup` shows `inLibrary: true`, do not add — run `status` and tell the user what
   is already there (downloaded / no file yet / downloading). `add` also protects against
   this and returns the status instead of an error.
5. `remove` needs an explicit request from the user; `--delete-files` needs an explicit
   "and delete the files". Never chain it after a failed add.
6. Report outcomes in the user's language, briefly: what was added, which profile, that
   the search has started, and that it will appear in Plex when the download completes
   (Radarr/Sonarr refresh the Plex library on import).
7. If exit code is 2, say the media server is unreachable and stop; don't retry in a loop.
8. **Quality and language are defaults, not questions.** Quality defaults to the configured
   profile (HD-1080p); language defaults to the original audio (set the Radarr profile Language to *Original*). Films are filed by original language: `RADARR_ROOT_IT` for Italian, `RADARR_ROOT` otherwise. Never ask for them up front.
   Instead, state both in the confirmation line so the user can veto in one word, e.g.
   "Aggiungo *The Fall Guy* (2024)  1080p, audio originale. Dimmi 'in italiano' o '4K' se vuoi altro."
   Then map the reply:

   | User says | Pass |
   |---|---|
   | "in 4K", "UHD" | `--profile Ultra-HD` |
   | "any quality", "anche in bassa qualit" | `--profile Any` |
   | "doppiato in italiano" (a non-Italian film, dubbed  rare) | `--dub it`  profile `HD-1080p ITA` (must exist in Radarr, Language = Italian) + root `RADARR_ROOT_IT` |
   | "in italiano" (series) | `--profile "HD-1080p ITA"`; anime  add `--root /shield/ANIME_ITA` |

   If the requested profile does not exist the script says so (exit 1)  report it, don't fall back silently.

## Commands

```bash
media.py lookup movie  "the bear"                 # up to 3 candidates, tmdbId, year, inLibrary
media.py lookup series "the bear"                 # tvdbId, year, number of seasons, status
media.py add movie  <tmdbId>                      # profile/root from config or Radarr defaults
media.py add series <tvdbId> --seasons 3          # 1 | 1-3 | 2,4 | latest | all
media.py add series <tvdbId> --seasons all --anime
media.py status movie  --term "dune"              # or --id <radarrId>
media.py status series --id 42
media.py queue                                    # everything downloading, both apps
media.py recent movie                             # last imports (what actually arrived)
media.py remove series <sonarrId> [--delete-files]
```

`add` accepts `--profile "<quality profile name>"` and `--root <path>`; otherwise it uses
`RADARR_QUALITY_PROFILE` / `SONARR_QUALITY_PROFILE`, `RADARR_ROOT`, `SONARR_ROOT_TV`,
`SONARR_ROOT_ANIME` from the environment, else the first profile and a root folder chosen by
type (anime → a root containing `ANIME`, otherwise the first non-anime root).

## Worked examples

**"Scaricami The Bear, la terza stagione"**
1. `lookup series "the bear"` → one clear match (2022, 4 seasons).
2. `add series 421378 --seasons 3` → JSON with `seasonsMonitored: [3]`, `searchStarted: true`.
3. Reply: "Aggiunta *The Bear* (2022), stagione 3 — sto cercando gli episodi, compariranno su Plex man mano che arrivano."

**"Get me Dune"**
1. `lookup movie "dune"` → 1984 and 2021 both plausible → ask "the 1984 Lynch or the 2021 Villeneuve?"
2. On answer, `add movie <tmdbId>`.

**"Is Oppenheimer there yet?"**
1. `status movie --term "oppenheimer"` → `hasFile` or `downloading` with percent/timeleft.

## Configuration

Keys are read from the environment: `RADARR_API_KEY`, `SONARR_API_KEY` (and optional
`*_URL`). In OpenClaw, set them in the gateway environment file and reference them in the
skill entry as `"${RADARR_API_KEY}"` — string values only. If the variables are absent, the
script falls back to reading `<ApiKey>` from a `config.xml` found under `~/media-stack`,
`~/services` or `~/docker`, matched by port (7878 / 8989). Keys are sent only in the
`X-Api-Key` header, never in URLs, and never printed.
