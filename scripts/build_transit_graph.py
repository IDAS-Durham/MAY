#!/usr/bin/env python3
"""Build the line-network graph + detect interchanges (commute plan task 18, D9).

Consumes the line definitions (data/transport/lines.csv + line_stops.csv) and emits
a routing graph that scripts/build_routing_table.py (task 19) runs shortest-path on.

Graph design — a per-MGU **hub** formulation (not pairwise transfers). A major rail
MGU has ~570 lines through it; pairwise transfer edges there would be ~570² ≈ 325k.
Routing every line-stop through one hub node per MGU keeps transfers O(lines), so the
whole graph stays ~linear in the number of stops.

Node kinds:
  stop : one per (line_id, position) — a boarding/alighting event on a line
  hub  : one per MGU — the interchange point shared by all lines serving that MGU

Edges (weight = minutes):
  ride   : stop_i -> stop_{i+1} on the same line, weight = Δt_offset_min
  alight : stop -> hub(its MGU), weight 0           (step off onto the concourse)
  board  : hub(MGU) -> stop at that MGU, weight = interchange penalty
           (the FIRST board from the journey origin skips the hub — see task 19 —
            so only transfers pay the penalty)

Graphs are built per mode_class (train, tube) and never mixed: a commuter's mode is
assigned once from census TS061, so journeys stay within one mode (plan D1/D2).

An **interchange** is any MGU served by ≥2 distinct lines (within a mode class).

Outputs (data/transport/, gitignored):
  transit_nodes.csv  node_idx, mode_class, kind, line_id, mgu, position, t_offset_min
  transit_edges.csv  mode_class, src_idx, dst_idx, weight_min, type
  interchanges.csv   mode_class, mgu, n_lines, n_stops, lines (sample)

Usage:  python3 scripts/build_transit_graph.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSPORT = REPO_ROOT / "data" / "transport"

# Interchange (transfer) penalty in minutes, by mode class. Rough peak values
# (walk between platforms + wait); calibrate later.
PENALTY_MIN = {"train": 5.0, "tube": 4.0}


def main() -> int:
    lines = pd.read_csv(TRANSPORT / "lines.csv")
    stops = pd.read_csv(TRANSPORT / "line_stops.csv")
    stops = stops.merge(lines[["line_id", "mode"]], on="line_id", how="left")

    node_rows, edge_rows, interchange_rows = [], [], []
    next_idx = 0

    for mode_class in sorted(stops["mode"].unique()):
        sub = stops[stops["mode"] == mode_class].sort_values(["line_id", "position"])
        penalty = PENALTY_MIN.get(mode_class, 5.0)

        # 1) hub node per MGU
        hub_idx: dict[str, int] = {}
        for mgu in sub["node_mgu"].unique():
            hub_idx[mgu] = next_idx
            node_rows.append({"node_idx": next_idx, "mode_class": mode_class,
                              "kind": "hub", "line_id": "", "mgu": mgu,
                              "position": "", "t_offset_min": ""})
            next_idx += 1

        # 2) stop nodes + ride/alight/board edges, walking each line in order
        n_ride = n_alight = n_board = 0
        for line_id, g in sub.groupby("line_id", sort=False):
            g = g.sort_values("position")
            prev_idx = prev_off = None
            for r in g.itertuples(index=False):
                sidx = next_idx
                node_rows.append({"node_idx": sidx, "mode_class": mode_class,
                                  "kind": "stop", "line_id": line_id,
                                  "mgu": r.node_mgu, "position": r.position,
                                  "t_offset_min": r.t_offset_min})
                next_idx += 1
                hub = hub_idx[r.node_mgu]
                # ride edge from previous stop on this line
                if prev_idx is not None:
                    w = max(0.0, float(r.t_offset_min) - float(prev_off))
                    edge_rows.append({"mode_class": mode_class, "src_idx": prev_idx,
                                      "dst_idx": sidx, "weight_min": w, "type": "ride"})
                    n_ride += 1
                # alight onto the MGU hub, and allow (re)boarding from it
                edge_rows.append({"mode_class": mode_class, "src_idx": sidx,
                                  "dst_idx": hub, "weight_min": 0.0, "type": "alight"})
                edge_rows.append({"mode_class": mode_class, "src_idx": hub,
                                  "dst_idx": sidx, "weight_min": penalty, "type": "board"})
                n_alight += 1
                n_board += 1
                prev_idx, prev_off = sidx, r.t_offset_min

        # 3) interchanges: MGUs served by >=2 distinct lines
        per_mgu = sub.groupby("node_mgu").agg(
            n_lines=("line_id", "nunique"), n_stops=("line_id", "size"),
            lines=("line_id", lambda s: "|".join(sorted(set(s))[:8])))
        inter = per_mgu[per_mgu["n_lines"] >= 2].reset_index()
        for r in inter.itertuples(index=False):
            interchange_rows.append({"mode_class": mode_class, "mgu": r.node_mgu,
                                     "n_lines": r.n_lines, "n_stops": r.n_stops,
                                     "lines": r.lines})

        print(f"  {mode_class:5s}: {len(hub_idx)} hubs, "
              f"{sum(1 for n in node_rows if n['mode_class']==mode_class and n['kind']=='stop')} stop-nodes, "
              f"edges ride={n_ride} alight={n_alight} board={n_board}, "
              f"interchanges={len(inter)} (penalty {penalty:.0f}m)")

    pd.DataFrame(node_rows).to_csv(TRANSPORT / "transit_nodes.csv", index=False)
    pd.DataFrame(edge_rows).to_csv(TRANSPORT / "transit_edges.csv", index=False)
    pd.DataFrame(interchange_rows).to_csv(TRANSPORT / "interchanges.csv", index=False)

    print(f"\nDone. {len(node_rows)} nodes, {len(edge_rows)} edges, "
          f"{len(interchange_rows)} interchanges.")
    print(f"  -> {TRANSPORT/'transit_nodes.csv'}")
    print(f"  -> {TRANSPORT/'transit_edges.csv'}")
    print(f"  -> {TRANSPORT/'interchanges.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
