#!/usr/bin/env python3
"""media.py — Radarr/Sonarr request tool for the OpenClaw `media-request` skill.

Design rules (see SKILL.md):
  * `lookup` never changes anything and returns up to N candidates with year — the
    agent confirms with the user before `add`.
  * `add` refuses to re-add something already in the library and returns its status
    instead of an error.
  * Series are added with only the requested seasons monitored; a search is issued
    for exactly those seasons. "all" must be asked for explicitly.
  * Output is JSON on stdout (one object). `--text` prints a short human summary.
  * Only the standard library. Exit code 0 = ok, 1 = user-level problem (not found,
    ambiguous), 2 = connection/config problem.

Radarr/Sonarr client shape adapted from melionka/radarr-sonarr (MIT).
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

# ----------------------------------------------------------------------------- config


def _api_key_from_config_xml(port: str) -> str | None:
    """Fallback: read <ApiKey> from a Radarr/Sonarr config.xml found under common
    compose layouts, matched by <Port>. Never printed."""
    home = os.path.expanduser("~")
    patterns = [
        f"{home}/media-stack/**/config.xml",
        f"{home}/services/**/config.xml",
        f"{home}/docker/**/config.xml",
    ]
    for pat in patterns:
        for path in glob.glob(pat, recursive=True):
            try:
                txt = open(path, encoding="utf-8", errors="ignore").read(20000)
            except OSError:
                continue
            if f"<Port>{port}</Port>" in txt:
                m = re.search(r"<ApiKey>([0-9a-f]{32})</ApiKey>", txt)
                if m:
                    return m.group(1)
    return None


class Arr:
    """Minimal client for the *arr v3 API (Radarr v4/v5, Sonarr v3/v4)."""

    def __init__(self, kind: str):
        self.kind = kind  # "radarr" | "sonarr"
        port = "7878" if kind == "radarr" else "8989"
        self.url = os.environ.get(f"{kind.upper()}_URL", f"http://localhost:{port}").rstrip("/")
        self.key = os.environ.get(f"{kind.upper()}_API_KEY") or _api_key_from_config_xml(port)
        if not self.key:
            raise SystemExit(json.dumps({"ok": False, "error": f"{kind.upper()}_API_KEY not set and no config.xml found"}))

    def _req(self, path: str, method: str = "GET", body: dict | list | None = None):
        url = f"{self.url}/api/v3{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-Api-Key", self.key)  # header only — never in the query string
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="ignore")
            try:
                detail = json.loads(raw)
            except ValueError:
                detail = raw[:300]
            raise ArrError(e.code, detail)
        except (urllib.error.URLError, TimeoutError) as e:
            fail(2, f"{self.kind} unreachable at {self.url}: {e}")

    # --- shared helpers
    def profiles(self):
        return self._req("/qualityprofile")

    def profile_id(self, name: str | None):
        profs = self.profiles()
        if name:
            for p in profs:
                if p["name"].lower() == name.lower():
                    return p["id"], p["name"]
            fail(1, f"quality profile '{name}' not found; available: {[p['name'] for p in profs]}")
        # default: env, else first profile
        want = os.environ.get(f"{self.kind.upper()}_QUALITY_PROFILE")
        if want:
            return self.profile_id(want)
        return profs[0]["id"], profs[0]["name"]

    def root_folders(self):
        return [r["path"] for r in self._req("/rootfolder")]

    def command(self, name: str, **kw):
        return self._req("/command", "POST", {"name": name, **kw})

    def queue(self):
        extra = "includeMovie=true" if self.kind == "radarr" else "includeSeries=true&includeEpisode=true"
        q = self._req(f"/queue?pageSize=100&{extra}")
        out = []
        for rec in q.get("records", []):
            size, left = rec.get("size") or 0, rec.get("sizeleft") or 0
            pct = round(100 * (1 - left / size), 1) if size else None
            item = {
                "title": rec.get("title"),
                "status": rec.get("status"),
                "state": rec.get("trackedDownloadState"),
                "percent": pct,
                "timeleft": rec.get("timeleft"),
                "client": rec.get("downloadClient"),
            }
            if self.kind == "radarr" and rec.get("movie"):
                item["movie"] = f"{rec['movie']['title']} ({rec['movie'].get('year')})"
                item["movieId"] = rec["movie"]["id"]
            if self.kind == "sonarr" and rec.get("series"):
                ep = rec.get("episode") or {}
                item["series"] = rec["series"]["title"]
                item["seriesId"] = rec["series"]["id"]
                item["episode"] = f"S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
            msgs = [m.get("title") for m in rec.get("statusMessages", []) if m.get("title")]
            if msgs:
                item["messages"] = msgs[:3]
            out.append(item)
        return out


class ArrError(Exception):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"HTTP {code}: {detail}")


def fail(code: int, msg: str, **extra):
    print(json.dumps({"ok": False, "error": msg, **extra}, ensure_ascii=False))
    sys.exit(code)


def out(obj: dict, text: str | None = None):
    obj.setdefault("ok", True)
    if ARGS.text and text:
        print(text)
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=None))


# ----------------------------------------------------------------------------- movies


def movie_lookup(term: str, limit: int):
    r = Arr("radarr")
    res = r._req(f"/movie/lookup?term={urllib.parse.quote(term)}")
    cands = []
    for m in res[:limit]:
        cands.append({
            "tmdbId": m.get("tmdbId"),
            "title": m.get("title"),
            "year": m.get("year"),
            "originalTitle": m.get("originalTitle"),
            "overview": (m.get("overview") or "")[:200],
            "originalLanguage": (m.get("originalLanguage") or {}).get("name"),
            "inLibrary": bool(m.get("id")),
            "hasFile": bool(m.get("hasFile")),
            "radarrId": m.get("id") or None,
        })
    text = "\n".join(
        f"{i+1}. {c['title']} ({c['year']}) tmdb:{c['tmdbId']}"
        + ("  [in library" + (", downloaded]" if c["hasFile"] else ", no file yet]") if c["inLibrary"] else "")
        for i, c in enumerate(cands)
    ) or "no matches"
    out({"kind": "movie", "term": term, "candidates": cands}, text)


def movie_status(r: Arr, movie_id: int):
    m = r._req(f"/movie/{movie_id}")
    st = {
        "radarrId": m["id"], "title": m["title"], "year": m.get("year"),
        "monitored": m.get("monitored"), "hasFile": m.get("hasFile"),
        "quality": (m.get("movieFile") or {}).get("quality", {}).get("quality", {}).get("name"),
        "path": m.get("path"),
    }
    q = [x for x in r.queue() if x.get("movieId") == movie_id]
    if q:
        st["downloading"] = q
    return st


def movie_add(tmdb_id: int, profile: str | None, root: str | None, dub: str | None = None):
    if dub:
        # dubbed request: profile + root both follow the requested language, never half of it
        iso = dub.upper()
        profile = profile or os.environ.get(f"RADARR_PROFILE_DUB_{iso}") or f"HD-1080p {iso}A" if iso == "IT" else profile
        root = root or os.environ.get(f"RADARR_ROOT_{iso}")
        if not root:
            fail(1, f"no root folder configured for dubbed '{dub}' (set RADARR_ROOT_{iso})")
    r = Arr("radarr")
    res = r._req(f"/movie/lookup?term=tmdb:{tmdb_id}")
    if not res:
        fail(1, f"tmdb:{tmdb_id} not found")
    m = res[0]
    if m.get("id"):
        st = movie_status(r, m["id"])
        st["alreadyInLibrary"] = True
        out(st, f"Already in the library: {st['title']} ({st['year']}) — "
                + ("downloaded" if st["hasFile"] else "no file yet" + (", downloading" if st.get("downloading") else "")))
        return
    pid, pname = r.profile_id(profile)
    roots = r.root_folders()
    if not root:
        # root by original language: RADARR_ROOT_<ISO> (e.g. RADARR_ROOT_IT) wins, else RADARR_ROOT, else first
        lang = ((m.get("originalLanguage") or {}).get("name") or "").lower()
        iso = {"italian": "IT", "english": "EN", "spanish": "ES", "german": "DE", "french": "FR", "japanese": "JA"}.get(lang)
        root = (os.environ.get(f"RADARR_ROOT_{iso}") if iso else None) or os.environ.get("RADARR_ROOT") or (roots[0] if roots else None)
    if not root or root not in roots:
        fail(1, f"root folder '{root}' unknown; available: {roots}")
    body = {**m, "qualityProfileId": pid, "rootFolderPath": root, "monitored": True,
            "minimumAvailability": "released", "addOptions": {"searchForMovie": True}}
    try:
        added = r._req("/movie", "POST", body)
    except ArrError as e:
        fail(1, f"Radarr refused the add: {e.detail}")
    out({"added": True, "kind": "movie", "radarrId": added["id"], "title": added["title"],
         "year": added.get("year"), "profile": pname, "root": root, "searchStarted": True},
        f"Added {added['title']} ({added.get('year')}) — profile {pname}, searching now.")


# ----------------------------------------------------------------------------- series


def series_lookup(term: str, limit: int):
    s = Arr("sonarr")
    res = s._req(f"/series/lookup?term={urllib.parse.quote(term)}")
    cands = []
    for x in res[:limit]:
        seasons = [se["seasonNumber"] for se in x.get("seasons", []) if se["seasonNumber"] > 0]
        cands.append({
            "tvdbId": x.get("tvdbId"), "title": x.get("title"), "year": x.get("year"),
            "status": x.get("status"), "seriesType": x.get("seriesType"),
            "seasons": len(seasons), "network": x.get("network"),
            "overview": (x.get("overview") or "")[:200],
            "inLibrary": bool(x.get("id")), "sonarrId": x.get("id") or None,
        })
    text = "\n".join(
        f"{i+1}. {c['title']} ({c['year']}) tvdb:{c['tvdbId']} — {c['seasons']} seasons, {c['status']}"
        + ("  [in library]" if c["inLibrary"] else "")
        for i, c in enumerate(cands)
    ) or "no matches"
    out({"kind": "series", "term": term, "candidates": cands}, text)


def _parse_seasons(spec: str, available: list[int]) -> list[int]:
    spec = (spec or "").strip().lower()
    if spec == "all":
        return available
    if spec in ("latest", "last"):
        return [max(available)] if available else []
    wanted: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            wanted.update(range(int(a), int(b) + 1))
        else:
            wanted.add(int(part))
    missing = sorted(wanted - set(available))
    if missing:
        fail(1, f"season(s) {missing} do not exist; available: {available}")
    return sorted(wanted)


def series_status(s: Arr, series_id: int):
    x = s._req(f"/series/{series_id}")
    stats = x.get("statistics") or {}
    seasons = []
    for se in x.get("seasons", []):
        if se["seasonNumber"] == 0:
            continue
        st = se.get("statistics") or {}
        seasons.append({"season": se["seasonNumber"], "monitored": se.get("monitored"),
                        "files": st.get("episodeFileCount", 0), "episodes": st.get("episodeCount", 0)})
    res = {"sonarrId": x["id"], "title": x["title"], "year": x.get("year"), "monitored": x.get("monitored"),
           "seriesType": x.get("seriesType"), "path": x.get("path"),
           "files": stats.get("episodeFileCount", 0), "episodes": stats.get("episodeCount", 0),
           "seasons": seasons}
    q = [i for i in s.queue() if i.get("seriesId") == series_id]
    if q:
        res["downloading"] = q
    return res


def series_add(tvdb_id: int, seasons_spec: str, profile: str | None, root: str | None, anime: bool | None):
    s = Arr("sonarr")
    res = s._req(f"/series/lookup?term=tvdb:{tvdb_id}")
    if not res:
        fail(1, f"tvdb:{tvdb_id} not found")
    x = res[0]
    available = sorted(se["seasonNumber"] for se in x.get("seasons", []) if se["seasonNumber"] > 0)
    wanted = _parse_seasons(seasons_spec, available)
    if not wanted:
        fail(1, "no seasons selected — pass --seasons (e.g. 1 / 1-3 / latest / all)")

    if x.get("id"):
        # already in the library: monitor + search the requested seasons only
        full = s._req(f"/series/{x['id']}")
        changed = []
        for se in full["seasons"]:
            if se["seasonNumber"] in wanted and not se.get("monitored"):
                se["monitored"] = True
                changed.append(se["seasonNumber"])
        if changed or not full.get("monitored"):
            full["monitored"] = True
            s._req(f"/series/{full['id']}", "PUT", full)
        for n in wanted:
            s.command("SeasonSearch", seriesId=full["id"], seasonNumber=n)
        st = series_status(s, full["id"])
        st.update({"alreadyInLibrary": True, "seasonsRequested": wanted, "newlyMonitored": changed, "searchStarted": True})
        out(st, f"{st['title']} was already in the library — now searching season(s) {wanted}.")
        return

    is_anime = anime if anime is not None else (x.get("seriesType") == "anime")
    pid, pname = s.profile_id(profile)
    roots = s.root_folders()
    if not root:
        env_key = "SONARR_ROOT_ANIME" if is_anime else "SONARR_ROOT_TV"
        root = os.environ.get(env_key)
        if not root:
            pick = [r for r in roots if ("ANIME" in r.upper() and "ITA" not in r.upper())] if is_anime \
                else [r for r in roots if "ANIME" not in r.upper()]
            root = pick[0] if pick else (roots[0] if roots else None)
    if not root or root not in roots:
        fail(1, f"root folder '{root}' unknown; available: {roots}")

    for se in x.get("seasons", []):
        se["monitored"] = se["seasonNumber"] in wanted
    body = {**x, "qualityProfileId": pid, "rootFolderPath": root, "monitored": True, "seasonFolder": True,
            "seriesType": "anime" if is_anime else x.get("seriesType", "standard"),
            "addOptions": {"searchForMissingEpisodes": False, "monitor": "none"}}
    # monitor:"none" + explicit season flags = only the requested seasons end up monitored
    try:
        added = s._req("/series", "POST", body)
    except ArrError as e:
        fail(1, f"Sonarr refused the add: {e.detail}")
    # Sonarr applies addOptions.monitor after the POST; re-assert the season flags, then search
    full = s._req(f"/series/{added['id']}")
    for se in full["seasons"]:
        se["monitored"] = se["seasonNumber"] in wanted
    full["monitored"] = True
    s._req(f"/series/{full['id']}", "PUT", full)
    for n in wanted:
        s.command("SeasonSearch", seriesId=full["id"], seasonNumber=n)
    out({"added": True, "kind": "series", "sonarrId": full["id"], "title": full["title"], "year": full.get("year"),
         "seriesType": full.get("seriesType"), "profile": pname, "root": root,
         "seasonsMonitored": wanted, "searchStarted": True},
        f"Added {full['title']} ({full.get('year')}) to {root} — season(s) {wanted} monitored, searching now.")


# ----------------------------------------------------------------------------- status / queue / remove


def status(kind: str, ident: int | None, term: str | None):
    a = Arr(kind)
    if ident is None and term:
        path = "/movie/lookup" if kind == "radarr" else "/series/lookup"
        res = [x for x in a._req(f"{path}?term={urllib.parse.quote(term)}") if x.get("id")]
        if not res:
            fail(1, f"'{term}' is not in the {kind} library")
        ident = res[0]["id"]
    if ident is None:
        fail(1, "need --id or --term")
    st = movie_status(a, ident) if kind == "radarr" else series_status(a, ident)
    if kind == "radarr":
        txt = f"{st['title']} ({st['year']}): " + ("downloaded, " + str(st.get("quality")) if st["hasFile"] else "no file yet")
    else:
        txt = f"{st['title']}: {st['files']}/{st['episodes']} episodes on disk; seasons " + \
              ", ".join(f"S{x['season']}={x['files']}/{x['episodes']}" + ("" if x["monitored"] else " (unmonitored)") for x in st["seasons"])
    if st.get("downloading"):
        txt += "; downloading: " + "; ".join(f"{d['title']} {d.get('percent')}% ({d.get('timeleft')})" for d in st["downloading"])
    out(st, txt)


def queue_all():
    res = {}
    for kind in ("radarr", "sonarr"):
        try:
            res[kind] = Arr(kind).queue()
        except SystemExit:
            res[kind] = "unavailable"
    lines = []
    for kind, items in res.items():
        if isinstance(items, list):
            for i in items:
                what = i.get("movie") or f"{i.get('series')} {i.get('episode')}"
                lines.append(f"[{kind}] {what}: {i.get('status')} {i.get('percent')}% left {i.get('timeleft')}")
    out({"queue": res}, "\n".join(lines) or "queue empty")


def recent(kind: str, limit: int):
    a = Arr(kind)
    inc = "includeMovie=true" if kind == "radarr" else "includeSeries=true&includeEpisode=true"
    h = a._req(f"/history?page=1&pageSize={limit}&sortKey=date&sortDirection=descending&eventType=3&{inc}")
    items = []
    for rec in h.get("records", []):
        if kind == "radarr":
            what = f"{rec.get('movie', {}).get('title')} ({rec.get('movie', {}).get('year')})"
        else:
            ep = rec.get("episode") or {}
            what = f"{rec.get('series', {}).get('title')} S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
        items.append({"what": what, "date": rec.get("date"), "quality": (rec.get("quality") or {}).get("quality", {}).get("name")})
    out({"kind": kind, "imported": items}, "\n".join(f"{i['date'][:16]} {i['what']} [{i['quality']}]" for i in items) or "nothing imported recently")


def remove(kind: str, ident: int, delete_files: bool):
    a = Arr(kind)
    path = f"/movie/{ident}" if kind == "radarr" else f"/series/{ident}"
    x = a._req(path)
    a._req(f"{path}?deleteFiles={'true' if delete_files else 'false'}&addImportExclusion=false", "DELETE")
    out({"removed": True, "kind": kind, "id": ident, "title": x.get("title"), "filesDeleted": delete_files},
        f"Removed {x.get('title')} from {kind}" + (" and deleted its files." if delete_files else " (files kept)."))


# ----------------------------------------------------------------------------- cli


def main():
    global ARGS
    p = argparse.ArgumentParser(prog="media.py", description=__doc__.split("\n")[0])
    p.add_argument("--text", action="store_true", help="human summary instead of JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    lk = sub.add_parser("lookup", help="find candidates (no changes)")
    lk.add_argument("kind", choices=["movie", "series"])
    lk.add_argument("term")
    lk.add_argument("--limit", type=int, default=3)

    ad = sub.add_parser("add", help="add + search (confirm with the user first)")
    ad.add_argument("kind", choices=["movie", "series"])
    ad.add_argument("id", type=int, help="tmdbId for movie, tvdbId for series")
    ad.add_argument("--seasons", help="series only: 1 | 1-3 | 2,4 | latest | all")
    ad.add_argument("--profile", help="quality profile name")
    ad.add_argument("--root", help="root folder path")
    ad.add_argument("--anime", action="store_true", help="force anime type/root")
    ad.add_argument("--dub", help="movie only: dubbed language ISO code, e.g. it -> profile HD-1080p ITA + RADARR_ROOT_IT")

    st = sub.add_parser("status", help="library + download status of one item")
    st.add_argument("kind", choices=["movie", "series"])
    st.add_argument("--id", type=int)
    st.add_argument("--term")

    sub.add_parser("queue", help="everything currently downloading")

    rc = sub.add_parser("recent", help="recently imported")
    rc.add_argument("kind", choices=["movie", "series"])
    rc.add_argument("--limit", type=int, default=10)

    rm = sub.add_parser("remove", help="remove from the library (files kept unless --delete-files)")
    rm.add_argument("kind", choices=["movie", "series"])
    rm.add_argument("id", type=int, help="radarrId / sonarrId (from lookup/status), NOT tmdb/tvdb")
    rm.add_argument("--delete-files", action="store_true")

    # accept --text anywhere on the line (e.g. "queue --text"), not only before the subcommand
    _argv = [a for a in sys.argv[1:] if a != "--text"]
    ARGS = p.parse_args(_argv)
    ARGS.text = ARGS.text or "--text" in sys.argv
    k = {"movie": "radarr", "series": "sonarr"}
    try:
        if ARGS.cmd == "lookup":
            (movie_lookup if ARGS.kind == "movie" else series_lookup)(ARGS.term, ARGS.limit)
        elif ARGS.cmd == "add":
            if ARGS.kind == "movie":
                movie_add(ARGS.id, ARGS.profile, ARGS.root, ARGS.dub)
            else:
                series_add(ARGS.id, ARGS.seasons or "", ARGS.profile, ARGS.root, True if ARGS.anime else None)
        elif ARGS.cmd == "status":
            status(k[ARGS.kind], ARGS.id, ARGS.term)
        elif ARGS.cmd == "queue":
            queue_all()
        elif ARGS.cmd == "recent":
            recent(k[ARGS.kind], ARGS.limit)
        elif ARGS.cmd == "remove":
            remove(k[ARGS.kind], ARGS.id, ARGS.delete_files)
    except ArrError as e:
        fail(2, str(e))


ARGS = None
if __name__ == "__main__":
    main()
