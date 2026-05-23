#!/usr/bin/env python3
"""Fetch non-London UK metro/light-rail networks from OpenStreetMap (Overpass API).

Covers the systems not served by the TfL API (fetch_tfl_lines.py) or the National
Rail GTFS (fetch_rail_gtfs.sh):
  - Glasgow Subway        (route=subway,     operator "Glasgow Subway")
  - Tyne and Wear Metro   (route=light_rail, network  "Tyne and Wear Metro")
  - Manchester Metrolink  (route=tram,       network  "Manchester Metrolink")

OSM maps each line direction/branch as a route relation whose ordered members give
the station sequence; member stop nodes carry name + lat/lon. Overpass is keyless
and reproducible. We query each network separately by an exact OSM tag selector
(pinned to avoid false matches such as St. Louis "MetroLink") and label its output
rows with the canonical system name.

Because OSM often maps multiple stop_position/platform nodes per physical station
(and different routes reference different ones), we canonicalize a station by
(network, name): the first node seen for a name fixes its id + coordinates, and all
sequence rows reference that canonical id. This yields accurate per-network station
counts and clean station<->sequence joins.

Outputs (under data/transport/metros/, gitignored), mirroring the TfL output shape:
  raw/overpass_{label}.json    raw Overpass result per network (full fidelity)
  stations.csv                 station_id (OSM node), name, lat, lon, network
  sequences.csv                network, route_id, route_ref, route_name, position, station_id

Source: OpenStreetMap contributors, via https://overpass-api.de/  (ODbL).

Usage:  python3 scripts/fetch_uk_metros.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "transport" / "metros"
RAW_DIR = OUT_DIR / "raw"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Canonical system name -> exact Overpass relation selector. Pinned tightly so we
# don't pick up similarly-named systems elsewhere in the world.
NETWORKS = {
    "Glasgow Subway":       'relation["route"="subway"]["operator"="Glasgow Subway"]',
    "Tyne and Wear Metro":  'relation["route"="light_rail"]["network"="Tyne and Wear Metro"]',
    "Manchester Metrolink": 'relation["route"="tram"]["network"="Manchester Metrolink"]',
}


def query_for(selector: str) -> str:
    # 1) emit the route relations with their ordered member lists (out body),
    # 2) recurse to all member nodes and emit their tags+coords (>; out body).
    return f"""[out:json][timeout:180];
({selector};)->.routes;
.routes out body;
.routes >;
out body;
"""


def run_overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS, data=data, headers={"User-Agent": "MAY-commute-builder/1.0"},
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.load(resp)


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    stations: dict[tuple[str, str], dict] = {}   # (network, name) -> attrs (canonical)
    sequence_rows: list[dict] = []
    summary: dict[str, dict] = {}

    for label, selector in NETWORKS.items():
        result = run_overpass(query_for(selector))
        slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        (RAW_DIR / f"overpass_{slug}.json").write_text(json.dumps(result, indent=2))

        elements = result["elements"]
        nodes = {e["id"]: e for e in elements if e["type"] == "node"}
        relations = [e for e in elements if e["type"] == "relation"]
        n_routes = 0

        for rel in relations:
            tags = rel.get("tags", {})
            route_ref = tags.get("ref", "")
            route_name = tags.get("name", "")
            members = rel.get("members", [])

            # Ordered stop members: prefer role starting "stop"; fall back to
            # platform node members if a relation maps no stop_position nodes.
            stops = [m for m in members
                     if m["type"] == "node" and m.get("role", "").startswith("stop")]
            if not stops:
                stops = [m for m in members
                         if m["type"] == "node" and m.get("role", "").startswith("platform")]

            pos = 0
            last_name = None
            for m in stops:
                node = nodes.get(m["ref"])
                if node is None:
                    continue
                name = (node.get("tags", {}).get("name") or "").strip()
                if not name or name == last_name:
                    continue  # skip unnamed helpers; collapse consecutive dupes
                last_name = name
                key = (label, name)
                if key not in stations:
                    stations[key] = {
                        "station_id": node["id"],   # first node seen = canonical
                        "name": name,
                        "lat": node.get("lat"),
                        "lon": node.get("lon"),
                        "network": label,
                    }
                sequence_rows.append({
                    "network": label,
                    "route_id": rel["id"],
                    "route_ref": route_ref,
                    "route_name": route_name,
                    "position": pos,
                    "station_id": stations[key]["station_id"],
                })
                pos += 1
            n_routes += 1
            print(f"  {label:24s} rel {rel['id']:>10}  ref={route_ref or '-':14s} "
                  f"{pos:3d} stops  ({route_name})")

        n_st = sum(1 for k in stations if k[0] == label)
        summary[label] = {"routes": n_routes, "stations": n_st}

    with (OUT_DIR / "stations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["station_id", "name", "lat", "lon", "network"])
        w.writeheader()
        for key in sorted(stations, key=lambda k: (k[0], k[1])):
            w.writerow(stations[key])

    with (OUT_DIR / "sequences.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["network", "route_id", "route_ref",
                                          "route_name", "position", "station_id"])
        w.writeheader()
        w.writerows(sequence_rows)

    print(f"\nDone. {len(stations)} unique stations, {len(sequence_rows)} ordered "
          f"membership rows.")
    failed = []
    for label in NETWORKS:
        s = summary.get(label, {"routes": 0, "stations": 0})
        print(f"  {label:24s} {s['routes']:2d} routes, {s['stations']:3d} unique stations")
        if s["stations"] == 0:
            failed.append(label)
    print(f"  -> {OUT_DIR/'stations.csv'}")
    print(f"  -> {OUT_DIR/'sequences.csv'}")

    if failed:
        print(f"ERROR: no stations fetched for: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
