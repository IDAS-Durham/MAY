"""
Debug and diagnostic output utilities for June Zero simulation.

This module provides functions for exporting data to CSV files and printing
diagnostic information about the world state.
"""
import csv
import logging
import os
import numpy as np

logger = logging.getLogger("debug_output")


from may.serialization.export_properties import export_relationships


def export_venue_allocations(world, output_file="venue_allocations.csv"):
    """
    Export all venues (except households) with their allocation counts to CSV.

    Args:
        world: World object containing geography, population, and venues
        output_file: Path to output CSV file
    """
    logger.info(f"Exporting venue allocations to {output_file}...")

    venues = world.venues.get_all_venues().values()

    # Collect venue allocation data
    venue_data = []
    for venue in venues:
        # Skip households
        if venue.type == "household":
            continue

        # Count allocated people
        allocated_count = venue.size()

        # Get capacity information from venue properties
        # Different venue types may have different capacity column names
        capacity_config = world.venues.get_capacity_config(venue.type)

        if capacity_config and 'total_capacity_column' in capacity_config:
            # Use the configured capacity column (e.g., 'bed_count' for care_home)
            capacity_column = capacity_config['total_capacity_column']
            total_capacity = venue.properties.get(capacity_column, 0)
        else:
            # Fallback to standard 'capacity' column
            total_capacity = venue.properties.get('capacity', 0)

        # Calculate utilization percentage
        if total_capacity > 0:
            utilization_pct = (allocated_count / total_capacity) * 100
        else:
            utilization_pct = 0.0

        venue_data.append({
            'venue_id': venue.id,
            'venue_name': venue.name,
            'venue_type': venue.type,
            'geographical_unit': venue.geographical_unit.name,
            'geographical_level': venue.geographical_unit.level,
            'capacity': int(total_capacity) if total_capacity else 0,
            'people_allocated': allocated_count,
            'utilization_pct': f"{utilization_pct:.1f}",
            'latitude': venue.coordinates[0] if venue.coordinates else None,
            'longitude': venue.coordinates[1] if venue.coordinates else None,
        })

    # Sort by venue type and then by allocated count
    venue_data.sort(key=lambda x: (x['venue_type'], -x['people_allocated']))

    # Write to CSV
    if venue_data:
        with open(output_file, 'w', newline='') as f:
            fieldnames = ['venue_id', 'venue_name', 'venue_type', 'geographical_unit',
                         'geographical_level', 'capacity', 'people_allocated', 'utilization_pct',
                         'latitude', 'longitude']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(venue_data)

        logger.info(f"Exported {len(venue_data)} venues to {output_file}")

        # Log summary statistics
        total_allocated = sum(v['people_allocated'] for v in venue_data)
        total_capacity = sum(v['capacity'] for v in venue_data)
        venue_types = {}
        for v in venue_data:
            vtype = v['venue_type']
            if vtype not in venue_types:
                venue_types[vtype] = {'count': 0, 'allocated': 0, 'capacity': 0}
            venue_types[vtype]['count'] += 1
            venue_types[vtype]['allocated'] += v['people_allocated']
            venue_types[vtype]['capacity'] += v['capacity']

        overall_utilization = (total_allocated / total_capacity * 100) if total_capacity > 0 else 0.0
        logger.info(f"Total capacity: {total_capacity:,}, Total allocated: {total_allocated:,} ({overall_utilization:.1f}% utilization)")
        logger.info("Breakdown by venue type:")
        for vtype, stats in sorted(venue_types.items()):
            util_pct = (stats['allocated'] / stats['capacity'] * 100) if stats['capacity'] > 0 else 0.0
            logger.info(f"  {vtype}: {stats['count']} venues, {stats['allocated']:,}/{stats['capacity']:,} people ({util_pct:.1f}%)")
    else:
        logger.info("No non-household venues to export")


def export_residence_venues(world, output_file="residence_venues.csv"):
    """
    Export all venues assigned as residences with their residents to CSV.

    Args:
        world: World object containing geography, population, and venues
        output_file: Path to output CSV file
    """
    logger.info(f"Exporting residence venues to {output_file}...")

    # Collect residence data
    residence_data = []
    all_venues = world.venues.get_all_venues_list()

    for venue in all_venues:
        # Check all subsets. Households use dynamic categories (Kids, Adults, etc).
        for subset in venue.subsets.values():
            members = subset.members
            
            if not members:
                continue
                
            hid = venue.properties.get('HID', 'N/A')
            s_hid = str(hid).strip()
            if s_hid.endswith('.0'):
                s_hid = s_hid[:-2]
            bt_code = venue.properties.get('BTCode', 'N/A')
            venue_type = venue.type
            
            for person in members:
                # Format age/sex as "30F"
                sex_char = person.sex[0].upper() if person.sex else 'U'
                age_sex = f"{int(person.age)}{sex_char}"
                
                residence_data.append({
                    'HID': s_hid,
                    'BTCode': bt_code,
                    'VenueType': venue_type,
                    'VenueID': venue.id,
                    'GeoUnit': venue.geographical_unit.name if venue.geographical_unit else '',
                    'PersonID': person.id,
                    'AgeSex': age_sex
                })

    if residence_data:
        # Sort primarily by VenueType (households first) and then by HID
        try:
            # We want 'household' to be first. Others following alphabetically is fine.
            residence_data.sort(key=lambda x: (
                0 if x['VenueType'] == 'household' else 1,
                str(x['HID']),
                x['PersonID']
            ))
        except Exception as e:
            logger.warning(f"Failed to sort residence data: {e}")

        # Write to CSV
        with open(output_file, 'w', newline='') as f:
            fieldnames = ['HID', 'BTCode', 'VenueType', 'VenueID', 'GeoUnit',
                          'PersonID', 'AgeSex']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(residence_data)
            
        logger.info(f"Exported {len(residence_data):,} residence records to {output_file}")
    else:
        logger.warning("No residence venues found to export")


def export_commute_mode_debug(world, output_file="commute_mode_debug.csv"):
    """
    Export per-person commute-mode evidence and log a summary.

    Proves the commute_mode_assignment gating: who got a commute_mode, broken
    down against work_mode and the actually-assigned primary_activity workplace
    venue (office/classroom/hospital/care_home, worker subset). Workplace venue
    types that should commute vs. those that should not are cross-tabbed so the
    gate can be eyeballed.

    Args:
        world: World object containing the population.
        output_file: Path to output CSV file. A "<stem>_summary.txt" sibling is
            also written with the aggregate tables.
    """
    from collections import Counter

    logger.info(f"Exporting commute-mode debug to {output_file}...")

    WORKPLACE_VENUES = {"office", "classroom", "hospital", "care_home"}
    SHARED_TRANSPORT_MODES = {"train", "tube", "bus"}
    # Per-mode leg venue types written by route_commute_{train,tube,bus}.yaml.
    LEG_VENUE_TYPES = ("train_line", "tube_line", "bus_line")

    rows = []
    people = world.population.get_all_people()

    # Bookkeeping for the task 8/9 cross-checks (per §12).
    leg_count_by_mode = Counter()
    leg_count_distribution = Counter()    # n_legs -> count of people
    walk_with_venue = 0
    bad_timing = 0                         # legs where t_board >= t_alight
    sample_bad_timing = []

    for person in people:
        primary = person.activity_map.get("primary_activity", {})
        # Venue types under primary_activity and whether person sits in a
        # 'worker' subset of a workplace venue.
        pa_venue_types = sorted(primary.keys())
        is_workplace_worker = False
        for vt, subsets in primary.items():
            if vt in WORKPLACE_VENUES and any(
                getattr(s, "subset_name", None) == "worker" for s in subsets
            ):
                is_workplace_worker = True
                break

        commute_mode = person.properties.get("commute_mode")

        # Inspect commute legs (post-RouteDistributor). The activity_map shape
        # for shared-transport riders is: person.activity_map["commute"][
        # "<mode>_line"] = [Subset, Subset, ...] — one subset per leg. Each
        # route_commute_<mode>.yaml writes its own venue type, so we union
        # across train_line / tube_line / bus_line.
        commute = person.activity_map.get("commute", {})
        leg_subsets = []
        if isinstance(commute, dict):
            for vt in LEG_VENUE_TYPES:
                leg_subsets.extend(commute.get(vt, []))
        n_legs = len(leg_subsets)

        # Collect (t_board, t_alight) for inspection / sanity checks.
        leg_timings = []
        for s in leg_subsets:
            md = getattr(s, "member_metadata", {}).get(person.id, {})
            leg_timings.append((md.get("t_board_min"), md.get("t_alight_min")))
            tb, ta = md.get("t_board_min"), md.get("t_alight_min")
            if tb is None or ta is None or not (tb < ta):
                bad_timing += 1
                if len(sample_bad_timing) < 5:
                    sample_bad_timing.append((person.id, s.venue.name, tb, ta))

        if commute_mode in SHARED_TRANSPORT_MODES:
            leg_count_by_mode[commute_mode] += n_legs
        leg_count_distribution[n_legs] += 1
        if commute_mode == "walk" and n_legs > 0:
            walk_with_venue += 1

        # Only keep people who are interesting for this proof: anyone who has a
        # work_mode (i.e. went through the workplace pipeline) or got a venue or
        # a commute_mode. Keeps the CSV small for the County Durham test world.
        work_mode = person.properties.get("work_mode")
        if not (work_mode or pa_venue_types or commute_mode):
            continue

        rows.append({
            "PersonID": person.id,
            "Age": int(person.age),
            "Sex": person.sex,
            "work_mode": work_mode,
            "work_sector": person.properties.get("work_sector"),
            "primary_activity_venues": "|".join(pa_venue_types),
            "is_workplace_worker": is_workplace_worker,
            "commute_mode": commute_mode,
            "n_commute_legs": n_legs,
            "commute_legs": ";".join(
                f"{s.venue.name}({tb}-{ta})"
                for s, (tb, ta) in zip(leg_subsets, leg_timings)
            ),
        })

    # ---- Aggregate tables (the actual proof) -------------------------------
    n_total = len(people)
    n_with_commute = sum(1 for r in rows if r["commute_mode"])
    mode_counts = Counter(r["commute_mode"] for r in rows if r["commute_mode"])

    # Cross-tab 1: commute_mode assigned vs work_mode (should be Normal/Hybrid only)
    wm_with_commute = Counter(
        r["work_mode"] for r in rows if r["commute_mode"]
    )
    # Cross-tab 2: did workplace workers get a commute_mode? Did non-workers?
    worker_with_commute = sum(
        1 for r in rows if r["is_workplace_worker"] and r["commute_mode"]
    )
    worker_without_commute = sum(
        1 for r in rows if r["is_workplace_worker"] and not r["commute_mode"]
    )
    nonworker_with_commute = sum(
        1 for r in rows if not r["is_workplace_worker"] and r["commute_mode"]
    )
    # Cross-tab 3: commute_mode by the workplace venue type they were placed in
    venue_mode = Counter(
        r["primary_activity_venues"] for r in rows if r["commute_mode"]
    )

    summary_lines = []
    def emit(line=""):
        summary_lines.append(line)
        logger.info(line)

    emit("=" * 60)
    emit("COMMUTE MODE ASSIGNMENT — VERIFICATION")
    emit("=" * 60)
    emit(f"Total people in world           : {n_total:,}")
    emit(f"Rows in debug CSV (work-related): {len(rows):,}")
    emit(f"People with commute_mode        : {n_with_commute:,}")
    emit("")
    emit("commute_mode distribution:")
    for mode, c in mode_counts.most_common():
        emit(f"  {mode:<14}: {c:,}")
    emit("")
    emit("work_mode of people WITH a commute_mode (expect Normal/Hybrid only):")
    for wm, c in wm_with_commute.most_common():
        emit(f"  {str(wm):<14}: {c:,}")
    emit("")
    emit("Gate cross-checks (these prove the activity_venue filter):")
    emit(f"  workplace workers WITH commute_mode    : {worker_with_commute:,}")
    emit(f"  workplace workers WITHOUT commute_mode : {worker_without_commute:,}  "
         f"(expected: From_Home workers + any not sampled)")
    emit(f"  NON-workers WITH commute_mode          : {nonworker_with_commute:,}  "
         f"(expected: 0)")
    emit("")
    emit("commute_mode count by assigned primary_activity venue(s):")
    for vt, c in venue_mode.most_common():
        emit(f"  {vt:<22}: {c:,}")
    emit("")
    # ---- Route distributor (task 8/9) cross-checks ------------------------
    emit("ROUTE DISTRIBUTOR — VERIFICATION (tasks 8/9, per §12)")
    venues_by_type = {
        vt: world.venues.get_venues_by_type(vt) for vt in LEG_VENUE_TYPES
    }
    total_line_venues = sum(len(v) for v in venues_by_type.values())
    n_routed = sum(c for n, c in leg_count_distribution.items() if n > 0)
    n_multi = sum(c for n, c in leg_count_distribution.items() if n > 1)
    emit(f"  Line venues materialised (total)   : {total_line_venues:,}")
    for vt in LEG_VENUE_TYPES:
        emit(f"    {vt:<12}: {len(venues_by_type[vt]):,}")
    emit(f"  People with >=1 commute leg        : {n_routed:,}")
    emit(f"  People with >=2 commute legs       : {n_multi:,}")
    emit("  Leg-count distribution (n_legs -> n_people):")
    for n in sorted(leg_count_distribution.keys()):
        emit(f"    {n} -> {leg_count_distribution[n]:,}")
    emit("  Total legs written by mode:")
    for mode in sorted(leg_count_by_mode.keys()):
        emit(f"    {mode:<6}: {leg_count_by_mode[mode]:,}")
    # Assertions (D12): a person whose final commute_mode is walk must end
    # with an empty commute venue.
    if walk_with_venue:
        emit(f"  ⚠ walk-mode people with a commute venue: {walk_with_venue}  (expected: 0)")
    else:
        emit("  ✓ walk-mode people with a commute venue: 0 (D12 fallback consistent)")
    if bad_timing:
        emit(f"  ⚠ legs with bad timing (t_board >= t_alight or missing): {bad_timing}")
        for pid, name, tb, ta in sample_bad_timing:
            emit(f"      person={pid} line={name} t_board={tb} t_alight={ta}")
    else:
        emit("  ✓ all legs satisfy t_board < t_alight")
    emit("=" * 60)

    # ---- Write CSV ----------------------------------------------------------
    if rows:
        rows.sort(key=lambda r: (not r["is_workplace_worker"], r["PersonID"]))
        with open(output_file, "w", newline="") as f:
            fieldnames = [
                "PersonID", "Age", "Sex", "work_mode", "work_sector",
                "primary_activity_venues", "is_workplace_worker", "commute_mode",
                "n_commute_legs", "commute_legs",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Exported {len(rows):,} commute-debug records to {output_file}")
    else:
        logger.warning("No work-related people found to export for commute debug")

    # ---- Write summary sibling ---------------------------------------------
    summary_path = os.path.splitext(output_file)[0] + "_summary.txt"
    try:
        with open(summary_path, "w") as f:
            f.write("\n".join(summary_lines) + "\n")
        logger.info(f"Wrote commute-mode summary to {summary_path}")
    except Exception as e:
        logger.warning(f"Failed to write commute summary: {e}")

    return {
        "n_total": n_total,
        "n_with_commute": n_with_commute,
        "nonworker_with_commute": nonworker_with_commute,
        "mode_counts": dict(mode_counts),
    }


def export_work_assignment_debug(
    world,
    output_file="work_assignment_debug.csv",
    industry_sex_margin_file=None,
):
    """
    Export per-worker work-assignment evidence and a summary of proof metrics.

    Measures whether the workplace pipeline seats people in real jobs and
    whether the location/sector draws are geographically self-consistent. Runs
    unchanged on both the residence-basis pipeline (workplace_sgu) and the
    workplace-basis pipeline (workplace_mgu): it resolves whichever workplace
    property is present to its MGU, so a baseline run and a fixed run are
    directly comparable.

    Four metrics (written to a "<stem>_summary.txt" sibling):
      (1) Company placement rate  -- company-eligible workers seated in a
          company office / all company-eligible workers.
      (2) Sector-location consistency -- share of company-eligible workers
          whose INTENDED workplace MGU actually contains >=1 company of their
          drawn sector (capacity ignored). Isolates "wrong place" from "right
          place but full".
      (3) Spatial basis -- Pearson correlation of assigned-workers-per-MGU with
          company capacity per MGU (job supply) vs with resident-worker count
          per MGU (residence density).
      (4) Sex realism -- assigned %female by sector vs the census (TS060)
          LAD x sex margin, restricted to the world's LGUs. Skipped with a
          warning if the margin file is absent.

    Args:
        world: built World object.
        output_file: per-worker CSV path. A "<stem>_summary.txt" sibling holds
            the aggregate proof tables.
        industry_sex_margin_file: resolved path to EW_industry_sex_lad.csv (or
            the nation's equivalent) for metric (4). None -> skip metric (4).
    """
    from collections import Counter, defaultdict

    logger.info(f"Exporting work-assignment debug to {output_file}...")

    levels = world.geography.levels
    MGU_LEVEL = levels[1] if len(levels) > 1 else None
    LGU_LEVEL = levels[2] if len(levels) > 2 else None

    WORKPLACE_VENUES = {"office", "hospital", "care_home", "classroom"}
    SPECIFIC_VENUES = {"hospital", "care_home", "classroom"}

    # Canonical sector order + census column names (matches
    # work_sector_assignment.yaml value_columns).
    SECTOR_COLS = [
        ("A", "Agriculture; Forestry; Fishing"),
        ("B", "Mining and Quarrying"),
        ("C", "Manufacturing"),
        ("D", "Electricity, Gas, Steam and Air Conditioning Supply"),
        ("E", "Water Supply; Sewage; Waste Management and Remediation activities"),
        ("F", "Construction"),
        ("G", "Wholesale and Retail trade; Repair of Motor Vehicles and Motorcycles"),
        ("H", "Transport and Storage"),
        ("I", "Accommodation and Food Service Activities"),
        ("J", "Information and Communication"),
        ("K", "Financial and Insurance Activities"),
        ("L", "Real Estate Activities"),
        ("M", "Professional Scientific and Technical Activities"),
        ("N", "Administrative and Support Service Activities"),
        ("O", "Public Administration and Defence; Compulsory Social Security"),
        ("P", "Education"),
        ("Q", "Human Health and Social Work Activities"),
        ("Other", "Other"),
    ]

    def to_mgu_name(unit):
        """Return the MGU-level name for a geographical unit, or None."""
        if unit is None or MGU_LEVEL is None:
            return None
        if unit.level == MGU_LEVEL:
            return unit.name
        mgu = unit.get_ancestor_by_level(MGU_LEVEL)
        return mgu.name if mgu else None

    # ---- Company supply: presence + capacity by MGU x sector ---------------
    sectors_by_mgu = defaultdict(set)        # mgu_name -> {sector, ...}
    cap_by_mgu_sector = defaultdict(int)     # (mgu_name, sector) -> capacity
    cap_by_mgu = defaultdict(int)            # mgu_name -> total capacity
    company_venues = world.venues.get_venues_by_type("company")
    for v in company_venues:
        mgu_name = to_mgu_name(v.geographical_unit)
        if mgu_name is None:
            continue
        sector = v.properties.get("industry_code")
        cap = int(v.properties.get("employee_count", 0) or 0)
        sectors_by_mgu[mgu_name].add(sector)
        cap_by_mgu_sector[(mgu_name, sector)] += cap
        cap_by_mgu[mgu_name] += cap

    # ---- Walk workers ------------------------------------------------------
    rows = []
    assigned_by_mgu = Counter()      # intended workplace MGU -> company-eligible workers
    home_by_mgu = Counter()          # home MGU -> company-eligible workers (residence proxy)
    sector_sex_assigned = defaultdict(lambda: {"male": 0, "female": 0})

    n_workers = 0                    # have work_sector
    n_company_eligible = 0
    n_placed_company = 0
    n_placed_specific = 0
    n_remote = 0                     # From_Home: employer but no physical desk
    n_consistent = 0                 # intended MGU has >=1 company of the sector
    n_intended_missing = 0
    wm_eligible = Counter()          # work_mode among company-eligible
    wm_unplaced = Counter()          # work_mode among company-eligible unplaced

    for person in world.population.get_all_people():
        sector = person.properties.get("work_sector")
        if not sector:
            continue
        n_workers += 1
        sex = (person.sex or "").lower()
        work_mode = person.properties.get("work_mode")
        if sex in ("male", "female"):
            sector_sex_assigned[sector][sex] += 1

        home_mgu = to_mgu_name(person.geographical_unit)

        # Where did they actually land (worker subset in a workplace venue)?
        placed_type = None
        placed_mgu = None
        primary = person.activity_map.get("primary_activity", {})
        for vt, subsets in primary.items():
            if vt in WORKPLACE_VENUES and any(
                getattr(s, "subset_name", None) == "worker" for s in subsets
            ):
                placed_type = vt
                placed_mgu = to_mgu_name(subsets[0].venue.geographical_unit)
                break

        is_specific = placed_type in SPECIFIC_VENUES
        is_company = placed_type == "office"
        # From_Home and 'Other' (no fixed workplace: farmers, construction,
        # travelling) workers have an employer but occupy no physical company
        # desk, so they are excluded from the company-placement denominator.
        is_remote = (work_mode in ("From_Home", "Other")) and not is_specific
        company_eligible = (not is_specific) and not is_remote
        if is_specific:
            n_placed_specific += 1
        elif is_remote:
            n_remote += 1

        # Intended workplace MGU: placed venue if any, else the drawn attribute.
        if placed_mgu is not None:
            intended_mgu = placed_mgu
        else:
            wmgu = person.properties.get("workplace_mgu")
            wsgu = person.properties.get("workplace_sgu")
            if wmgu:
                unit = world.geography.get_unit(wmgu)
                intended_mgu = to_mgu_name(unit) if unit else wmgu
            elif wsgu:
                unit = world.geography.get_unit(wsgu)
                intended_mgu = to_mgu_name(unit) if unit else None
            else:
                intended_mgu = None

        consistent = None
        if company_eligible:
            n_company_eligible += 1
            wm_eligible[work_mode] += 1
            if is_company:
                n_placed_company += 1
            else:
                wm_unplaced[work_mode] += 1
            if intended_mgu:
                assigned_by_mgu[intended_mgu] += 1
            if home_mgu:
                home_by_mgu[home_mgu] += 1
            # Consistency: does the intended MGU host this sector at all?
            if intended_mgu is None:
                n_intended_missing += 1
                consistent = False
            else:
                consistent = sector in sectors_by_mgu.get(intended_mgu, ())
                if consistent:
                    n_consistent += 1

        rows.append({
            "PersonID": person.id,
            "Sex": person.sex,
            "work_mode": work_mode,
            "work_sector": sector,
            "home_mgu": home_mgu,
            "intended_workplace_mgu": intended_mgu,
            "placed_venue_type": placed_type or "",
            "company_eligible": company_eligible,
            "placed_in_company": is_company,
            "mgu_hosts_sector": consistent,
        })

    # ---- Metric (3): correlations over MGUs --------------------------------
    all_mgus = sorted(set(cap_by_mgu) | set(assigned_by_mgu) | set(home_by_mgu))
    r_capacity = r_residence = None
    if len(all_mgus) >= 3:
        assigned_vec = np.array([assigned_by_mgu.get(m, 0) for m in all_mgus], float)
        cap_vec = np.array([cap_by_mgu.get(m, 0) for m in all_mgus], float)
        home_vec = np.array([home_by_mgu.get(m, 0) for m in all_mgus], float)
        if assigned_vec.std() > 0 and cap_vec.std() > 0:
            r_capacity = float(np.corrcoef(assigned_vec, cap_vec)[0, 1])
        if assigned_vec.std() > 0 and home_vec.std() > 0:
            r_residence = float(np.corrcoef(assigned_vec, home_vec)[0, 1])

    # ---- Metric (4): sex realism vs census margin --------------------------
    sex_realism_rows = []   # (sector, assigned_pctF, census_pctF, n_assigned)
    if industry_sex_margin_file and os.path.exists(industry_sex_margin_file):
        try:
            import pandas as pd
            margin = pd.read_csv(industry_sex_margin_file)
            world_lgus = set(world.geography.get_units_by_level(LGU_LEVEL).keys()) \
                if LGU_LEVEL else set()
            if world_lgus:
                margin = margin[margin["LGU_name"].isin(world_lgus)]
            census_pctF = {}
            for code, col in SECTOR_COLS:
                if col not in margin.columns:
                    continue
                f = margin.loc[margin["Sex"].str.lower() == "female", col].sum()
                m = margin.loc[margin["Sex"].str.lower() == "male", col].sum()
                tot = f + m
                census_pctF[code] = (100.0 * f / tot) if tot > 0 else None
            for code, _ in SECTOR_COLS:
                a = sector_sex_assigned.get(code, {"male": 0, "female": 0})
                n = a["male"] + a["female"]
                assigned_pctF = (100.0 * a["female"] / n) if n > 0 else None
                sex_realism_rows.append((code, assigned_pctF, census_pctF.get(code), n))
        except Exception as e:
            logger.warning(f"Sex-realism metric failed: {e}")
    else:
        logger.warning(
            "Sex-realism metric skipped: no industry_sex_margin_file "
            f"({industry_sex_margin_file})"
        )

    # ---- Emit summary ------------------------------------------------------
    summary_lines = []
    def emit(line=""):
        summary_lines.append(line)
        logger.info(line)

    pr = lambda num, den: (100.0 * num / den) if den else 0.0
    emit("=" * 64)
    emit("WORK-ASSIGNMENT PIPELINE — EVIDENCE")
    emit("=" * 64)
    emit(f"Workers (have work_sector)      : {n_workers:,}")
    emit(f"  placed in specific venue      : {n_placed_specific:,} "
         f"(hospital/care_home/classroom)")
    emit(f"  no fixed desk (WFH/Other)     : {n_remote:,}")
    emit(f"  company-eligible (on-site)    : {n_company_eligible:,}")
    emit("")
    emit("(1) COMPANY PLACEMENT RATE")
    emit(f"  placed in a company           : {n_placed_company:,}/{n_company_eligible:,} "
         f"({pr(n_placed_company, n_company_eligible):.1f}%)")
    emit(f"  unplaced (skipped)            : {n_company_eligible - n_placed_company:,} "
         f"({pr(n_company_eligible - n_placed_company, n_company_eligible):.1f}%)")
    emit("  work_mode of company-eligible (unplaced / eligible):")
    for wm in sorted(wm_eligible, key=lambda k: str(k)):
        emit(f"    {str(wm):<12}: {wm_unplaced.get(wm, 0):,} / {wm_eligible[wm]:,}")
    emit("")
    emit("(2) SECTOR-LOCATION CONSISTENCY  (intended MGU hosts the drawn sector)")
    emit(f"  consistent                    : {n_consistent:,}/{n_company_eligible:,} "
         f"({pr(n_consistent, n_company_eligible):.1f}%)")
    emit(f"  intended MGU lacks sector     : {n_company_eligible - n_consistent - n_intended_missing:,}")
    emit(f"  no intended MGU resolved      : {n_intended_missing:,}")
    emit("")
    emit("(3) SPATIAL BASIS  (assigned workers per MGU, Pearson r)")
    emit(f"  vs company capacity (jobs)    : "
         f"{'n/a' if r_capacity is None else f'{r_capacity:+.3f}'}")
    emit(f"  vs resident workers (homes)   : "
         f"{'n/a' if r_residence is None else f'{r_residence:+.3f}'}")
    emit(f"  ({len(all_mgus):,} MGUs)")
    emit("")
    emit("(4) SEX REALISM  (assigned %F vs census %F, by sector)")
    if sex_realism_rows:
        emit(f"  {'sec':<6}{'assigned%F':>12}{'census%F':>12}{'diff':>10}{'n':>10}")
        for code, aF, cF, n in sex_realism_rows:
            a_str = "n/a" if aF is None else f"{aF:.1f}"
            c_str = "n/a" if cF is None else f"{cF:.1f}"
            d_str = "n/a" if (aF is None or cF is None) else f"{aF - cF:+.1f}"
            emit(f"  {code:<6}{a_str:>12}{c_str:>12}{d_str:>10}{n:>10,}")
    else:
        emit("  (skipped — no census margin file)")
    emit("=" * 64)

    # ---- Write CSV ---------------------------------------------------------
    if rows:
        rows.sort(key=lambda r: (not r["company_eligible"], not r["placed_in_company"],
                                 str(r["work_sector"]), r["PersonID"]))
        with open(output_file, "w", newline="") as f:
            fieldnames = [
                "PersonID", "Sex", "work_mode", "work_sector", "home_mgu",
                "intended_workplace_mgu", "placed_venue_type", "company_eligible",
                "placed_in_company", "mgu_hosts_sector",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"Exported {len(rows):,} work-assignment records to {output_file}")
    else:
        logger.warning("No workers found to export for work-assignment debug")

    summary_path = os.path.splitext(output_file)[0] + "_summary.txt"
    try:
        with open(summary_path, "w") as f:
            f.write("\n".join(summary_lines) + "\n")
        logger.info(f"Wrote work-assignment summary to {summary_path}")
    except Exception as e:
        logger.warning(f"Failed to write work-assignment summary: {e}")

    return {
        "n_workers": n_workers,
        "n_company_eligible": n_company_eligible,
        "placement_rate": pr(n_placed_company, n_company_eligible),
        "consistency_rate": pr(n_consistent, n_company_eligible),
        "r_capacity": r_capacity,
        "r_residence": r_residence,
    }


def export_people(world, output_file="people.csv"):
    """
    Export all people with their attributes, properties, and activity assignments to CSV.

    Args:
        world: World object containing geography, population, and venues
        output_file: Path to output CSV file
    """
    logger.info(f"Exporting people to {output_file}...")

    people = world.population.get_all_people()

    # Collect person data
    person_data = []
    for person in people:
        # Basic attributes
        row = {
            'person_id': person.id,
            'age': person.age,
            'sex': person.sex,
            'geographical_unit': person.geographical_unit.name if person.geographical_unit else None,
        }

        # Get the large-unit (levels[2]) name, if the hierarchy has a third level
        levels = world.geography.levels
        lgu_level = levels[2] if len(levels) > 2 else None
        lgu_name = None
        if lgu_level and person.geographical_unit:
            current_unit = person.geographical_unit
            while current_unit:
                if current_unit.level == lgu_level:
                    lgu_name = current_unit.name
                    break
                current_unit = current_unit.parent
        row['lgu'] = lgu_name

        # Add all properties as columns
        for key, value in person.properties.items():
            # Convert to string for CSV compatibility
            row[f'prop_{key}'] = str(value) if value is not None else None

        # Get residence information
        # Use person.residence property (works for all residence types)
        residence_venue = person.residence
        residence_type = person.residence_type

        row['residence_type'] = residence_type
        row['residence_name'] = residence_venue.name if residence_venue else None

        # Get all activities
        row['activities'] = ','.join(person.activities) if person.activities else None

        # Get activity assignments (company, school, university, etc.)
        # Iterate through activity_map to find non-residence activities
        for activity_name, subsets in person.activity_map.items():
            # Skip residence activity (all residence types use the 'residence' activity name)
            if activity_name == 'residence':
                continue

            row[f'{activity_name}'] = str(subsets)
            # Check if this is a multi-venue activity (dict) or single-venue (list)
            # if isinstance(subsets, dict):
            #     # Multi-venue activity (e.g., leisure with multiple types)
            #     # Store count of venues per type
            #     for venue_type, venue_subsets in subsets.items():
            #         if venue_subsets and len(venue_subsets) > 0:
            #             # Store count of venues for this type
            #             row[f'{activity_name}_{venue_type}_count'] = len(venue_subsets)
            #             # Optionally store first venue name
            #             row[f'{activity_name}_{venue_type}_first'] = venue_subsets
            # elif subsets and len(subsets) > 0:
            #     # Single-venue activity (traditional)
            #     subset_list = subsets.values()
            #     venue = subsets_list[0].venue
            #     row[f'{activity_name}_venue_name'] = venue.name
            #     row[f'{activity_name}_venue_type'] = venue.type
            #     row[f'{activity_name}_venue_geo_unit'] = venue.geographical_unit.name if venue.geographical_unit else None

            #     # Add parent venue information if it exists
            #     if venue.parent:
            #         parent = venue.parent
            #         row[f'{activity_name}_parent_venue_name'] = parent.name
            #         row[f'{activity_name}_parent_venue_type'] = parent.type
            #         row[f'{activity_name}_parent_venue_geo_unit'] = parent.geographical_unit.name if parent.geographical_unit else None

        person_data.append(row)

    # Get all unique column names from all rows
    all_columns = set()
    for row in person_data:
        all_columns.update(row.keys())

    # Define column order (basic attributes first, then properties, then activities)
    basic_columns = ['person_id', 'age', 'sex', 'geographical_unit', 'lgu']
    residence_columns = ['residence_type', 'residence_name']
    activity_columns = ['activities']

    # Get property columns (sorted)
    prop_columns = sorted([col for col in all_columns if col.startswith('prop_')])

    # Get activity venue columns (sorted)
    activity_venue_columns = sorted([col for col in all_columns
                                     if col.endswith('_venue_name') or
                                        col.endswith('_venue_type') or
                                        col.endswith('_venue_geo_unit') or
                                        col.endswith('_parent_venue_name') or
                                        col.endswith('_parent_venue_type') or
                                        col.endswith('_parent_venue_geo_unit')])

    # Combine all columns in order
    fieldnames = basic_columns + residence_columns + activity_columns + prop_columns + activity_venue_columns

    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(person_data)

    logger.info(f"Exported {len(person_data)} people to {output_file}")

    # Log summary
    with_residence = sum(1 for p in person_data if p.get('residence_type'))
    logger.info(f"  People with residence: {with_residence}/{len(person_data)} ({with_residence/len(person_data)*100:.1f}%)")

    # Count activity assignments
    activity_counts = {}
    for row in person_data:
        for col in activity_venue_columns:
            if col.endswith('_venue_name') and row.get(col):
                activity_type = col.replace('_venue_name', '')
                activity_counts[activity_type] = activity_counts.get(activity_type, 0) + 1

    if activity_counts:
        logger.info("  Activity assignments:")
        for activity, count in sorted(activity_counts.items()):
            logger.info(f"    {activity}: {count} people")


def print_world_examples(world):
    """
    Print examples of the created world to help users understand the data.

    Args:
        world: World object containing geography, population, and venues
    """
    geo = world.geography
    venues = world.venues
    population = world.population
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXAMPLES")
    logger.info("=" * 60)

    # Example 1: Show geographical hierarchy
    logger.info("")
    logger.info("1. Geographical Hierarchy:")
    all_units = geo.get_all_units_list()
    if all_units:
        # Get an example SGU
        sgu_units = [u for u in all_units if u.level == geo.levels[0]]
        if sgu_units:
            example_sgu = sgu_units[0]
            logger.info(f"   SGU Example: {example_sgu}")
            logger.info(f"   - Coordinates: {example_sgu.coordinates}")
            if example_sgu.parent:
                logger.info(f"   - Parent MGU: {example_sgu.parent.name}")
                if example_sgu.parent.parent:
                    logger.info(f"   - Parent LGU: {example_sgu.parent.parent.name}")

        # Get an example MGU with venues
        mgu_with_venues = [u for u in all_units if u.level == geo.levels[1] and len(u.venues) > 0]
        if mgu_with_venues:
            example_mgu = mgu_with_venues[0]
            logger.info("")
            logger.info(f"   MGU Example: {example_mgu}")
            logger.info(f"   - Has {len(example_mgu.children)} SGU children")
            logger.info(f"   - Has {len(example_mgu.venues)} venues")

    # Example 2: Show venues
    logger.info("")
    logger.info("2. Venue Examples:")
    venue_types = venues.get_venue_types()
    for vtype in sorted(venue_types)[:10]:  # Show first 10 types
        venues_of_type = venues.get_venues_by_type(vtype)
        if venues_of_type:
            example_venue = venues_of_type[0]
            logger.info(f"   {vtype.capitalize()}: {example_venue.name}")
            logger.info(f"   - Located in: {example_venue.geographical_unit.name} ({example_venue.geographical_unit.level})")
            if example_venue.coordinates:
                logger.info(f"   - Coordinates: {example_venue.coordinates}")
            if example_venue.properties:
                # Show first 2 properties
                props = list(example_venue.properties.items())
                for key, value in props:
                    logger.info(f"   - {key}: {value}")

    # Example 3: Show how to query
    logger.info("")
    logger.info("3. Population Examples:")
    stats = population.get_statistics()
    if stats:
        logger.info(f"   Total population: {stats['total_population']:,}")
        logger.info(f"   Mean age: {stats['mean_age']:.1f} years")
        logger.info(f"   Median age: {stats['median_age']:.1f} years")
        logger.info(f"   Sex distribution:")
        for sex, count in stats['sex_distribution'].items():
            pct = 100 * count / stats['total_population']
            logger.info(f"     - {sex}: {count:,} ({pct:.1f}%)")
        logger.info(f"   Activity distribution:")
        for activity, count in sorted(stats['activity_counts'].items()):
            logger.info(f"     - {activity}: {count:,}")

        # Show example people
        logger.info("")
        logger.info("   Example people:")
        for person in np.random.choice(population.get_all_people(), size=min(5, len(population.get_all_people())), replace=False):
            logger.info(f"   {person}")
            logger.info(f"     - Activities: {', '.join(person.activities)}")

    logger.info("")
    logger.info("4. Household Examples:")
    households = world.get_households()
    if households and world.household_distributor:
        total_pop = len(population.get_all_people())
        allocation_rate = (len(world.household_distributor.allocated_people) / total_pop * 100) if total_pop > 0 else 0
        logger.info(f"   Total households: {len(households)}")
        logger.info(f"   People allocated: {len(world.household_distributor.allocated_people):,} / {total_pop:,} ({allocation_rate:.1f}%)")
        logger.info("")
        logger.info("   Example households:")
        for household in np.random.choice(households, size=min(5, len(households)), replace=False):
            age_categories = household.properties.get('_age_categories', [])
            composition = household.get_composition(age_categories)
            logger.info(f"   Household {household.id} in {household.geographical_unit.name}")
            logger.info(f"     - Size: {household.size()} people")
            logger.info(f"     - Composition: {composition}")
            if household.properties.get('original_pattern'):
                logger.info(f"     - Pattern: {household.properties['original_pattern']}")

    logger.info("")
    logger.info("5. Query Examples:")
    logger.info("   # Get all hospitals")
    all_hospitals = venues.get_venues_by_type("hospital")
    logger.info(f"   venues.get_venues_by_type('hospital') -> {len(all_hospitals)} hospitals")

    logger.info("")
    logger.info("   # Get venues in a specific area")
    mgu_with_venues = [u for u in all_units if u.level == geo.levels[1] and len(u.venues) > 0]
    if mgu_with_venues:
        unit_venues = mgu_with_venues[0].venues
        logger.info(f"   geo.get_unit('{mgu_with_venues[0].name}').venues -> {len(unit_venues)} venues")
        if unit_venues:
            logger.info(f"      e.g., {unit_venues[0].name} ({unit_venues[0].type})")

    logger.info("")
    logger.info("   # Get people by activity")
    workers = population.get_people_by_activity("work")
    logger.info(f"   population.get_people_by_activity('work') -> {len(workers)} people")

    logger.info("")
    logger.info("   # Get person's residence")
    if world.household_distributor and world.household_distributor.allocated_people:
        example_person_id = next(iter(world.household_distributor.allocated_people))
        example_person = next((p for p in population.get_all_people() if p.id == example_person_id), None)
        if example_person and "residence" in example_person.activity_map:
            residence_subsets = example_person.activity_map["residence"]
            if residence_subsets:
                residence_venue = residence_subsets[0].venue
                age_categories = residence_venue.properties.get('_age_categories', [])
                logger.info(f"   person.activity_map['residence'] -> {residence_venue.type.capitalize()} {residence_venue.id}")
                logger.info(f"      Size: {residence_venue.size()}, Composition: {residence_venue.get_composition(age_categories)}")

    logger.info("")
    logger.info("=" * 60)


def export_resident_linked_connections(world, output_file="outputs/resident_linked_connections.csv"):
    """
    Debug only: Export resident-linked connections (e.g., care home visits) to CSV.
    This helps verify that people are correctly linked to venues based on residents.

    Args:
        world: World object
        output_file: Path to output CSV file
    """
    import os
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    logger.info(f"DEBUG: Exporting resident-linked connections to {output_file}...")
    
    data = []
    people = world.population.get_all_people()
    
    # We look for 'leisure' activity with 'care_home' venue type by default
    activity_key = "leisure"
    target_venue_type = "care_home"
    
    # Pre-build person lookup for efficiency if needed, but get_person is usually fast
    
    for person in people:
        if activity_key not in person.activity_map:
            continue
            
        links = person.activity_map[activity_key].get(target_venue_type, [])
        for subset_link in links:
            venue = subset_link.venue
            subset_name = subset_link.subset_name
            
            # Extract resident_id from subset_name (e.g., "visitor_for_123")
            resident_id = 'unknown'
            resident_age = 'unknown'
            resident_sex = 'unknown'
            
            if "_for_" in subset_name:
                try:
                    res_id_str = subset_name.split("_for_")[-1]
                    resident_id = int(res_id_str)
                    resident = world.population.get_person(resident_id)
                    if resident:
                        resident_age = resident.age
                        resident_sex = resident.sex
                except (ValueError, IndexError):
                    pass
            
            # Get person details
            residence = person.residence
            household_id = residence.id if residence and residence.type == 'household' else 'none'
            
            data.append({
                'person_id': person.id,
                'age': person.age,
                'sex': person.sex,
                'household_id': household_id,
                'geo_unit': person.geographical_unit.name if person.geographical_unit else 'none',
                'linked_venue_id': venue.id,
                'linked_venue_name': venue.name,
                'visitor_to_resident_id': resident_id,
                'resident_age': resident_age,
                'resident_sex': resident_sex,
                'linked_venue_geo': venue.geographical_unit.name if venue.geographical_unit else 'none'
            })
            
    if not data:
        logger.warning(f"DEBUG: No {target_venue_type} links found in {activity_key} map.")
        return

    # Write to CSV
    with open(output_file, 'w', newline='') as f:
        fieldnames = ['person_id', 'age', 'sex', 'household_id', 'geo_unit', 
                     'linked_venue_id', 'linked_venue_name', 'visitor_to_resident_id', 
                     'resident_age', 'resident_sex', 'linked_venue_geo']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
        
    logger.info(f"DEBUG: Successfully exported {len(data)} links to {output_file}.")
