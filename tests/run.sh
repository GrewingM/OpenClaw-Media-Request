#!/bin/bash
# Offline smoke test against tests/mock_arr.py
cd "$(dirname "$0")/.." || exit 1
python3 tests/mock_arr.py & MOCK=$!; sleep 1
export RADARR_URL=http://127.0.0.1:17878 SONARR_URL=http://127.0.0.1:18989
export RADARR_API_KEY=$(printf 'k%.0s' $(seq 32))
export SONARR_API_KEY=$RADARR_API_KEY
export RADARR_QUALITY_PROFILE=HD-1080p SONARR_QUALITY_PROFILE=HD-1080p
M="python3 scripts/media.py --text"
set -x
$M lookup movie dune
$M add movie 27205          # already in library -> status, rc 0
$M add movie 438631         # new -> added
$M add series 421378        # no seasons -> rc 1
$M add series 421378 --seasons 3
$M add series 421378 --seasons 4   # existing -> monitor + search S4 only
$M add series 81797 --seasons latest   # anime root
$M status series --term bear
$M queue
$M remove series 10
set +x
kill $MOCK
