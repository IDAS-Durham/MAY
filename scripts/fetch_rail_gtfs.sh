#!/usr/bin/env bash
#
# Fetch GB national rail timetable data in GTFS format for commute-line modelling.
#
# Source: thomasforth/ATOCCIF2GTFS — a pre-built GTFS conversion of the publicly
#   available ATOC CIF timetable (Rail Delivery Group / National Rail). Committed
#   into that repo, so no ATOC account / Rail Data Portal registration is needed
#   (the National Rail Data Portal is being retired in early 2026).
# Vintage: ttis062, valid from 2024-04-06. Network topology (which stations a
#   route serves, in order, with travel times) is stable across 2021–2024, which
#   is what we consume for line definitions — see COMMUTE_PLAN.md D4.
# License: ATOC CIF open data terms (free reuse). See the source repo's LICENSE.
#
# Output: data/transport/rail_gtfs/  (gitignored — /data is not tracked)
#   agency.txt routes.txt trips.txt stops.txt stop_times.txt calendar.txt
#
# stops.txt      -> station coordinates, for snap_stations_to_lgu.py (task 5)
# stop_times.txt -> ordered stop sequences + arrival/departure times -> t_offset_min
# Consumed by:   scripts/build_transport_lines.py (task 6)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_ROOT/data/transport/rail_gtfs"
ZIP_NAME="gb_rail_gtfs_ttis062_20240406.zip"
URL="https://raw.githubusercontent.com/thomasforth/ATOCCIF2GTFS/master/ttis062_validfrom20240406_gtfs.zip"

mkdir -p "$DEST"
cd "$DEST"

echo "Downloading GB rail GTFS (~30 MB) -> $DEST/$ZIP_NAME"
curl -fSL --retry 3 -o "$ZIP_NAME" "$URL"

echo "Extracting..."
unzip -oq "$ZIP_NAME"

echo "Done. Contents:"
ls -1 *.txt

# Sanity check: the files the line-builder depends on must be present and non-empty.
for f in stops.txt stop_times.txt trips.txt routes.txt; do
  if [ ! -s "$f" ]; then
    echo "ERROR: expected $f to exist and be non-empty" >&2
    exit 1
  fi
done
echo "Verified: $(($(wc -l < stops.txt) - 1)) stations in stops.txt"
