# openclaw-media-request

An [OpenClaw](https://openclaw.ai) skill that turns "get me The Bear, season 3" into a
Radarr/Sonarr request: lookup with disambiguation, add with the right quality profile and
root folder, targeted season search, and download status in plain words.

Standard library only. One script, JSON out. Tested against Radarr 5 / Sonarr 4.

**Scope.** This is a front-end to Radarr/Sonarr, which manage a personal library. It does
not care where the media comes from  that is decided by the indexers and download clients
you configure in Prowlarr/Radarr/Sonarr. Use it for content you are entitled to keep.

---

## How you talk to it

The agent reads [SKILL.md](SKILL.md) and translates what you say into script calls. You
never type flags; you say what you want and the agent maps it. What is *not* said falls
back to the configured defaults and is repeated in the confirmation line, so you can veto
with one word.

| You say (any language) | The agent does |
|---|---|
| "get me Dune" | `lookup movie "dune"`  shows *Dune (2021)* and *Dune (1984)*  asks which |
| "get me Dune 2021" | `lookup`  single match  confirms "Dune (2021), 2160p, original audio"  `add movie 438631` |
| "in 4K" / "UHD" | nothing extra  the configured default profile already targets 2160p (1080p fallback) |
| "in 1080p", "any quality" | `--profile HD-1080p` / `--profile Any` |
| "in Italian", "doppiato" (for a film that is *not* Italian) | `--dub it`  profile `HD-1080p ITA` + root `RADARR_ROOT_IT` (both must exist, otherwise a clear refusal) |
| an Italian/Spanish/ film with no language stated | original audio, filed under `RADARR_ROOT_<ISO>` if set (e.g. `MOVIES_ITA`) |
| "The Bear season 3" | `add series 421378 --seasons 3` |
| "the latest season of Severance" | `--seasons latest` |
| "all of Severance" | `--seasons all`  only when you say so; the agent never assumes whole series |
| "is Oppenheimer there yet?" | `status movie --term oppenheimer`  downloaded / downloading 62 %, 12 min / not found |
| "what's downloading?" | `queue` |
| "what arrived this week?" | `recent movie` / `recent series` |
| "remove X" / "remove X and delete the files" | `remove  ` / `remove  --delete-files`  always confirmed first |

Language and quality are therefore *defaults stated back to you*, not questions asked up
front. The intended setup is one file per title carrying several audio tracks (Radarr/Sonarr
custom formats score MULTi and per-language audio) and Plex/Jellyfin choosing the track per
viewer; see "Recommended profile setup" below.

---

## Commands

All commands print **one JSON object** on stdout. Add `--text` before the command for a
one-line human summary instead. Exit codes: `0` ok  `1` not found / ambiguous / refused 
`2` Radarr/Sonarr unreachable or not configured.

```
python3 scripts/media.py [--text] <command> 
```

### `lookup movie|series "<term>" [--limit N]`
Never changes anything. Returns up to N (default 3) candidates.

```json
{"kind":"movie","term":"dune","candidates":[
  {"tmdbId":438631,"title":"Dune","year":2021,"originalTitle":"Dune","originalLanguage":"English",
   "overview":"Paul Atreides","inLibrary":false,"hasFile":false,"radarrId":null},
  {"tmdbId":841,"title":"Dune","year":1984,"":""}],"ok":true}
```
Series candidates carry `tvdbId`, `seasons` (count), `status` (continuing/ended),
`seriesType` (standard/anime), `network`, `inLibrary`, `sonarrId`.

### `add movie <tmdbId> [--profile NAME] [--root PATH] [--dub ISO]`
Adds and starts a search. If the film is already in the library it does **not** re-add: it
returns its status with `"alreadyInLibrary": true`.

- `--profile` quality profile name; default `RADARR_QUALITY_PROFILE`, else the first profile.
- `--root` root folder; default `RADARR_ROOT_<ISO>` for the film's original language
  (e.g. `RADARR_ROOT_IT`), else `RADARR_ROOT`, else the first root.
- `--dub it` dubbed request: profile `HD-1080p ITA` (or `RADARR_PROFILE_DUB_IT`) **and**
  root `RADARR_ROOT_IT`, refused if either is missing  never half-applied.

```json
{"added":true,"kind":"movie","radarrId":211,"title":"Dune","year":2021,
 "profile":"UHD-2160p","root":"/shield/Movies","searchStarted":true,"ok":true}
```

### `add series <tvdbId> --seasons SPEC [--profile NAME] [--root PATH] [--anime]`
`SPEC` is required: `3`  `1-3`  `2,4`  `latest`  `all`. Only those seasons are
monitored, and a `SeasonSearch` is issued for each. Non-existent seasons are refused with
the list of available ones. If the series already exists, the requested seasons are
monitored and searched on the existing entry (`"alreadyInLibrary": true`,
`"newlyMonitored": [4]`).

- Root: `--root`, else `SONARR_ROOT_ANIME` when the series is anime (or `--anime`), else
  `SONARR_ROOT_TV`, else a root containing `ANIME` / the first non-anime root.

### `status movie|series --id N | --term "<t>"`
On-disk state plus anything currently downloading for that item.

```json
{"sonarrId":42,"title":"The Bear","files":18,"episodes":28,"seasons":[
  {"season":1,"monitored":true,"files":8,"episodes":8},{"season":3,"monitored":true,"files":2,"episodes":10}],
 "downloading":[{"title":"The.Bear.S03E03","percent":62.0,"timeleft":"00:11:40","episode":"S03E03"}],"ok":true}
```

### `queue`
Both download queues: title, status, percent, time left, client, and any status messages
(stalled, import blocked, ).

### `recent movie|series [--limit N]`
Last imports (what actually arrived), with date and quality.

### `remove movie|series <id> [--delete-files]`
`<id>` is the Radarr/Sonarr id (from `lookup`/`status`), **not** tmdb/tvdb. Files are kept
unless `--delete-files`.

---

## Install

```bash
cd ~/.openclaw/workspace/skills
git clone https://github.com/GrewingM/OpenClaw-Media-Request media-request
```

Enable it in `openclaw.json`. API keys are optional: with none set, the script reads
`<ApiKey>` from a `config.xml` found under `~/media-stack`, `~/services` or `~/docker`,
matched by port (7878 / 8989). Keys are sent only in the `X-Api-Key` header, never in URLs,
never printed.

```json
"media-request": {
  "enabled": true,
  "env": {
    "RADARR_QUALITY_PROFILE": "UHD-2160p",
    "SONARR_QUALITY_PROFILE": "UHD-2160p",
    "RADARR_ROOT": "/shield/Movies",
    "RADARR_ROOT_IT": "/shield/MOVIES_ITA",
    "SONARR_ROOT_TV": "/shield/TV-SHOWS",
    "SONARR_ROOT_ANIME": "/shield/ANIME"
  }
}
```

### Configuration reference

| Variable | Default | Meaning |
|---|---|---|
| `RADARR_URL` / `SONARR_URL` | `http://localhost:7878` / `:8989` | where the apps are |
| `RADARR_API_KEY` / `SONARR_API_KEY` | from `config.xml` | use `"${VAR}"` refs in OpenClaw if you keep them in the gateway env |
| `RADARR_QUALITY_PROFILE` / `SONARR_QUALITY_PROFILE` | first profile | default profile name (`add` accepts `--profile` to override) |
| `RADARR_ROOT` | first root | default root for films |
| `RADARR_ROOT_<ISO>` |  | root by original language: `IT`, `EN`, `ES`, `DE`, `FR`, `JA` |
| `RADARR_PROFILE_DUB_<ISO>` | `HD-1080p <ISO>A` (IT  `HD-1080p ITA`) | profile used by `--dub` |
| `SONARR_ROOT_TV` / `SONARR_ROOT_ANIME` | first non-anime / first `ANIME` root | roots by series type |

---

## Recommended profile setup (multilingual household)

- **Quality profile** allowing the resolutions you accept with the highest as cutoff and
  *upgrades allowed* (e.g. 2160p WEB/Bluray, 1080p fallback). Language set to *Any*.
- **Custom formats** that score audio languages: `MULTi` (release-title regex) +200,
  per-language `LanguageSpecification` (Italian/Spanish +100, English +50), and
  `Language: Not Original` (negated `Original`) at 10000 so the original track is always
  present. Radarr then prefers releases with more of your languages and upgrades a
  single-language file when a MULTi one appears.
- **Plex**: one library over all folders; per-account *preferred audio* / *subtitle* /
  *shown with foreign audio*. **Bazarr** for subtitles in every household language.
- Connect Radarr/Sonarr  Plex (*Update Library* on import) so requests appear without a
  manual scan.

Scripts that applied exactly this on the reference setup live in the author's ops notes;
the API shapes are: custom-format `fields` as `[{"name":,"value":}]`, profile
`formatItems` as `[{"format":<cfId>,"name":,"score":}]`.

---

## Testing offline

`tests/mock_arr.py` is a tiny Radarr+Sonarr look-alike; `tests/run.sh` drives every command
against it (disambiguation, already-in-library, invalid season, anime root, remove).

## Credits

The idea of a stdlib-only Radarr/Sonarr skill and the shape of the API clients come from
[melionka/radarr-sonarr](https://github.com/melionka/radarr-sonarr) (MIT). This is a
rewrite: different agent contract, season handling, disambiguation and library-aware adds.

## Licence

MIT  see [LICENSE](LICENSE).
