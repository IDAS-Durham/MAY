#!/usr/bin/env python3
"""Precompute the (origin, destination) routing table (commute plan task 19, D9).

Runs shortest-path on the transit graph (scripts/build_transit_graph.py) to produce,
for every transit-connected MGU pair within a mode class, the ordered list of legs a
commuter rides. The commute distributor (task 8) is then a pure lookup into this
table — no per-person routing at world-build time, so it scales to 60M agents.

Method (per mode class, train and tube kept separate):
  * Build a sparse CSR adjacency from the persisted nodes/edges.
  * For each origin MGU, run one multi-source Dijkstra from that MGU's stop-nodes
    (min_only=True merges them into a single shortest-path forest; starting at
    stop-nodes makes the FIRST board free — only transfers pay the hub penalty).
  * Each destination MGU is reached at its hub node; walk the predecessor tree back
    to the origin and split the node path into legs at hub crossings (a leg = a
    maximal run of stop-nodes on one line). A multi-line journey yields >1 leg —
    exactly the interchange itinerary D9 needs; JUNE sums per-leg exposure.

Caps keep the table to realistic commute journeys (and bound reconstruction cost):
  MAX_JOURNEY_MIN  drop O→D pairs slower than this
  MAX_LEGS         drop itineraries needing more transfers than this

Outputs (data/transport/, gitignored), normalised + joinable on (origin/dest/mode):
  routes.csv      origin_mgu, dest_mgu, mode_class, n_legs, total_time_min
  route_legs.csv  origin_mgu, dest_mgu, mode_class, leg_idx, line_id,
                  board_mgu, alight_mgu, t_board_min, t_alight_min

Usage:  python3 scripts/build_routing_table.py [--mode train|tube]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSPORT = REPO_ROOT / "data" / "transport"

MAX_JOURNEY_MIN = 120.0
MAX_LEGS = 4


def route_mode(mode_class: str, nodes: pd.DataFrame, edges: pd.DataFrame):
    """Return (route_rows, leg_rows) for one mode class."""
    n = nodes[nodes["mode_class"] == mode_class].reset_index(drop=True)
    e = edges[edges["mode_class"] == mode_class]
    remap = {old: i for i, old in enumerate(n["node_idx"])}
    k = len(n)

    src = e["src_idx"].map(remap).to_numpy()
    dst = e["dst_idx"].map(remap).to_numpy()
    M = csr_matrix((e["weight_min"].to_numpy(float), (src, dst)), shape=(k, k))

    # Per-node arrays for fast reconstruction.
    is_stop = (n["kind"] == "stop").to_numpy()
    line_of = n["line_id"].fillna("").to_numpy()
    mgu_of = n["mgu"].to_numpy()
    toff_of = pd.to_numeric(n["t_offset_min"], errors="coerce").to_numpy()

    # Index helpers.
    hub_idx = {m: i for i, m, st in zip(range(k), mgu_of, is_stop) if not st}
    stops_by_mgu: dict[str, list[int]] = {}
    for i in np.where(is_stop)[0]:
        stops_by_mgu.setdefault(mgu_of[i], []).append(int(i))

    origins = sorted(stops_by_mgu)             # every MGU that hosts a stop
    hub_local = np.array([hub_idx[m] for m in origins])
    route_rows, leg_rows = [], []
    t0 = time.time()

    for oi, omgu in enumerate(origins):
        dist, pred, _ = dijkstra(M, directed=True, indices=stops_by_mgu[omgu],
                                 min_only=True, return_predecessors=True)
        dhub = dist[hub_local]                 # journey time to each dest MGU's hub
        reach = np.where((dhub > 0) & (dhub <= MAX_JOURNEY_MIN))[0]
        for di in reach:
            dmgu = origins[di]
            if dmgu == omgu:
                continue
            # Walk predecessors from dest hub back to an origin stop-node.
            path, cur = [], hub_local[di]
            while cur != -9999 and cur >= 0:
                path.append(cur)
                cur = pred[cur]
            path.reverse()                     # origin-stop ... dest-hub
            # Split stop-nodes into legs by contiguous line_id.
            legs = []
            for node in path:
                if not is_stop[node]:
                    continue
                ln = line_of[node]
                if legs and legs[-1]["line"] == ln:
                    legs[-1]["end"] = node
                else:
                    legs.append({"line": ln, "start": node, "end": node})
            if not legs or len(legs) > MAX_LEGS:
                continue
            route_rows.append({"origin_mgu": omgu, "dest_mgu": dmgu,
                               "mode_class": mode_class, "n_legs": len(legs),
                               "total_time_min": round(float(dhub[di]), 1)})
            for li, leg in enumerate(legs):
                s, en = leg["start"], leg["end"]
                leg_rows.append({
                    "origin_mgu": omgu, "dest_mgu": dmgu, "mode_class": mode_class,
                    "leg_idx": li, "line_id": leg["line"],
                    "board_mgu": mgu_of[s], "alight_mgu": mgu_of[en],
                    "t_board_min": int(round(toff_of[s])),
                    "t_alight_min": int(round(toff_of[en])),
                })
        if (oi + 1) % 250 == 0 or oi + 1 == len(origins):
            print(f"    {mode_class}: {oi+1}/{len(origins)} origins, "
                  f"{len(route_rows)} routes, {time.time()-t0:.0f}s")
    return route_rows, leg_rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["train", "tube"], help="limit to one mode class")
    args = ap.parse_args()

    nodes = pd.read_csv(TRANSPORT / "transit_nodes.csv")
    edges = pd.read_csv(TRANSPORT / "transit_edges.csv")
    modes = [args.mode] if args.mode else sorted(nodes["mode_class"].unique())

    all_routes, all_legs = [], []
    for mc in modes:
        print(f"  routing mode_class={mc} ...")
        r, l = route_mode(mc, nodes, edges)
        all_routes += r
        all_legs += l

    routes = pd.DataFrame(all_routes)
    legs = pd.DataFrame(all_legs)
    suffix = f"_{args.mode}" if args.mode else ""
    routes.to_csv(TRANSPORT / f"routes{suffix}.csv", index=False)
    legs.to_csv(TRANSPORT / f"route_legs{suffix}.csv", index=False)

    print(f"\nDone. {len(routes)} routes, {len(legs)} legs.")
    if len(routes):
        print(f"  legs per route: {routes['n_legs'].value_counts().sort_index().to_dict()}")
        print(f"  journey time (min): median {routes['total_time_min'].median():.0f}, "
              f"p90 {routes['total_time_min'].quantile(0.9):.0f}")
    print(f"  -> {TRANSPORT/('routes'+suffix+'.csv')}")
    print(f"  -> {TRANSPORT/('route_legs'+suffix+'.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
