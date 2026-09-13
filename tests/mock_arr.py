#!/usr/bin/env python3
"""Tiny in-memory Radarr+Sonarr look-alike for exercising media.py offline.
Run:  python3 tests/mock_arr.py  (serves radarr on 17878, sonarr on 18989)"""
import json, re, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

MOVIES = {  # library: tmdbId -> record
    27205: {"id": 1, "tmdbId": 27205, "title": "Inception", "year": 2010, "hasFile": True, "monitored": True,
            "path": "/shield/MOVIES/Inception (2010)", "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}}},
}
LOOKUP_MOVIES = [
    {"tmdbId": 438631, "title": "Dune", "year": 2021, "originalTitle": "Dune", "overview": "Paul Atreides..."},
    {"tmdbId": 841, "title": "Dune", "year": 1984, "originalTitle": "Dune", "overview": "Lynch..."},
    {"tmdbId": 27205, "title": "Inception", "year": 2010, "overview": "Cobb..."},
]
SERIES = {}  # tvdbId -> record
LOOKUP_SERIES = [
    {"tvdbId": 421378, "title": "The Bear", "year": 2022, "status": "continuing", "seriesType": "standard",
     "network": "FX", "overview": "Carmy...", "seasons": [{"seasonNumber": n, "monitored": False} for n in range(0, 5)]},
    {"tvdbId": 81797, "title": "One Piece", "year": 1999, "status": "continuing", "seriesType": "anime",
     "network": "Fuji TV", "overview": "Luffy...", "seasons": [{"seasonNumber": n, "monitored": False} for n in range(0, 23)]},
]
COMMANDS = []
NEXT = {"movie": 10, "series": 10}


class H(BaseHTTPRequestHandler):
    kind = "radarr"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.headers.get("X-Api-Key") != "k" * 32:
            return self._send(401, {"error": "Unauthorized"})
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path.replace("/api/v3", "")
        if p == "/qualityprofile":
            return self._send(200, [{"id": 1, "name": "Any"}, {"id": 4, "name": "HD-1080p"}])
        if p == "/rootfolder":
            return self._send(200, [{"path": "/shield/MOVIES"}] if self.kind == "radarr"
                              else [{"path": "/shield/TV-SHOWS"}, {"path": "/shield/ANIME"}, {"path": "/shield/ANIME_ITA"}])
        if p == "/queue":
            recs = [{"title": "Dune.2021.1080p", "status": "downloading", "trackedDownloadState": "downloading",
                     "size": 1000, "sizeleft": 400, "timeleft": "00:12:00", "downloadClient": "qBittorrent",
                     "movie": {"id": 10, "title": "Dune", "year": 2021}, "statusMessages": []}] if self.kind == "radarr" else []
            return self._send(200, {"records": recs})
        if p == "/history":
            return self._send(200, {"records": [{"date": "2026-09-12T20:00:00Z", "quality": {"quality": {"name": "WEBDL-1080p"}},
                                                 "movie": {"title": "Inception", "year": 2010},
                                                 "series": {"title": "The Bear"}, "episode": {"seasonNumber": 3, "episodeNumber": 1}}]})
        if p == "/movie/lookup":
            term = q.get("term", [""])[0]
            if term.startswith("tmdb:"):
                res = [m for m in LOOKUP_MOVIES if m["tmdbId"] == int(term[5:])]
            else:
                res = [m for m in LOOKUP_MOVIES if term.lower() in m["title"].lower()]
            return self._send(200, [{**m, **({"id": MOVIES[m["tmdbId"]]["id"], "hasFile": MOVIES[m["tmdbId"]]["hasFile"]}
                                             if m["tmdbId"] in MOVIES else {})} for m in res])
        if p == "/series/lookup":
            term = q.get("term", [""])[0]
            if term.startswith("tvdb:"):
                res = [s for s in LOOKUP_SERIES if s["tvdbId"] == int(term[5:])]
            else:
                res = [s for s in LOOKUP_SERIES if term.lower() in s["title"].lower()]
            return self._send(200, [{**s, **({"id": SERIES[s["tvdbId"]]["id"]} if s["tvdbId"] in SERIES else {})} for s in res])
        m = re.match(r"/movie/(\d+)$", p)
        if m:
            for r in MOVIES.values():
                if r["id"] == int(m.group(1)):
                    return self._send(200, r)
            return self._send(404, {"message": "NotFound"})
        m = re.match(r"/series/(\d+)$", p)
        if m:
            for r in SERIES.values():
                if r["id"] == int(m.group(1)):
                    return self._send(200, r)
            return self._send(404, {"message": "NotFound"})
        self._send(404, {"message": f"no route {p}"})

    def do_POST(self):
        u = urlparse(self.path); p = u.path.replace("/api/v3", ""); b = self._body()
        if p == "/command":
            COMMANDS.append(b); return self._send(201, {"id": len(COMMANDS), "name": b["name"], "status": "queued"})
        if p == "/movie":
            if b["tmdbId"] in MOVIES:
                return self._send(400, [{"propertyName": "TmdbId", "errorMessage": "This movie has already been added"}])
            rec = {**b, "id": NEXT["movie"], "hasFile": False, "path": f"{b['rootFolderPath']}/{b['title']} ({b['year']})"}
            NEXT["movie"] += 1; MOVIES[b["tmdbId"]] = rec; return self._send(201, rec)
        if p == "/series":
            if b["tvdbId"] in SERIES:
                return self._send(400, [{"errorMessage": "This series has already been added"}])
            rec = {**b, "id": NEXT["series"], "path": f"{b['rootFolderPath']}/{b['title']}"}
            # emulate Sonarr applying addOptions.monitor=none: all seasons unmonitored
            if b.get("addOptions", {}).get("monitor") == "none":
                for se in rec["seasons"]:
                    se["monitored"] = False
            for se in rec["seasons"]:
                se["statistics"] = {"episodeFileCount": 0, "episodeCount": 8}
            rec["statistics"] = {"episodeFileCount": 0, "episodeCount": 8 * (len(rec["seasons"]) - 1)}
            NEXT["series"] += 1; SERIES[b["tvdbId"]] = rec; return self._send(201, rec)
        self._send(404, {"message": f"no route {p}"})

    def do_PUT(self):
        u = urlparse(self.path); p = u.path.replace("/api/v3", ""); b = self._body()
        m = re.match(r"/series/(\d+)$", p)
        if m:
            for k, r in SERIES.items():
                if r["id"] == int(m.group(1)):
                    SERIES[k] = b; return self._send(202, b)
        self._send(404, {"message": "NotFound"})

    def do_DELETE(self):
        u = urlparse(self.path); p = u.path.replace("/api/v3", "")
        m = re.match(r"/(movie|series)/(\d+)$", p)
        if m:
            store = MOVIES if m.group(1) == "movie" else SERIES
            for k, r in list(store.items()):
                if r["id"] == int(m.group(2)):
                    del store[k]; return self._send(200, {})
        self._send(404, {"message": "NotFound"})


def serve(kind, port):
    cls = type(f"{kind}H", (H,), {"kind": kind})
    HTTPServer(("127.0.0.1", port), cls).serve_forever()


if __name__ == "__main__":
    threading.Thread(target=serve, args=("radarr", 17878), daemon=True).start()
    serve("sonarr", 18989)
