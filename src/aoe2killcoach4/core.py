"""Core parsing logic for AoE2 KillCoach v4."""
from __future__ import annotations
from aoe2killcoach4.time_utils import coerce_seconds

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from aoe2killcoach4.data_mappings import (
    BUILDING_KEYS,
    COUNTER_MAP,
    GOLD_LINES,
    PRODUCTION_BUILDINGS,
    TECH_CATEGORIES,
    TRASH_LINES,
    UNIT_LINE_MAP,
)


@dataclass
class ParsedReplay:
    """Container for parsed replay metadata and serialized data."""

    data: Dict[str, Any]


def parse_replay(path: str) -> ParsedReplay:
    """Parse a replay file into a serialized dict.

    Args:
        path: Path to the .aoe2record replay.

    Returns:
        ParsedReplay containing serialized match data.
    """
    from mgz import model

    with open(path, "rb") as handle:
        match = model.parse_match(handle)
    data = model.serialize(match)
    return ParsedReplay(data=data)


def format_seconds(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    minutes, sec = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{sec:02d}"


def sanitize_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return "_".join(filter(None, safe.split("_")))


def find_player(
    players: list[dict[str, Any]],
    you_name: str | None,
    you_player: int | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if you_name:
        for player in players:
            if player.get("name", "").lower() == you_name.lower():
                opponent = next(p for p in players if p != player)
                return player, opponent
    if you_player:
        idx = max(0, you_player - 1)
        if idx < len(players):
            player = players[idx]
            opponent = next(p for p in players if p != player)
            return player, opponent
    player = players[0]
    opponent = players[1] if len(players) > 1 else players[0]
    return player, opponent


def extract_match_info(data: dict[str, Any]) -> dict[str, Any]:
    match_info = {
        "map": data.get("map"),
        "duration": data.get("duration"),
        "timestamp": data.get("timestamp"),
        "version": data.get("version"),
        "build": data.get("build"),
    }
    return match_info


def _action_time(action: dict[str, Any]) -> Optional[int]:
    ts = action.get("timestamp")
    return int(ts) if ts is not None else None


def _player_actions(data: dict[str, Any], player_index: int) -> list[dict[str, Any]]:
    actions = data.get("actions", [])
    return [action for action in actions if action.get("player") == player_index]


def _unit_line(unit_name: str | None) -> str:
    if not unit_name:
        return "unknown"
    return UNIT_LINE_MAP.get(unit_name, "unknown")


def _collect_unit_events(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for action in actions:
        action_type = action.get("type")
        if action_type not in {"TRAIN", "DE_QUEUE", "CREATE"}:
            continue
        payload = action.get("payload", {})
        unit_name = payload.get("unit") or payload.get("name")
        timestamp = _action_time(action)
        if timestamp is None:
            continue
        events.append(
            {
                "time": timestamp,
                "unit": unit_name,
                "line": _unit_line(unit_name),
                "object_ids": action.get("object_ids") or [],
            }
        )
    return sorted(events, key=lambda item: item["time"])


def _collect_build_events(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    builds = []
    for action in actions:
        if action.get("type") != "BUILD":
            continue
        payload = action.get("payload", {})
        building = payload.get("building") or payload.get("name")
        timestamp = _action_time(action)
        if timestamp is None:
            continue
        builds.append(
            {
                "time": timestamp,
                "building": building,
                "object_ids": action.get("object_ids") or [],
            }
        )
    return sorted(builds, key=lambda item: item["time"])


def _extract_uptimes(data: dict[str, Any], player_index: int) -> dict[str, Any]:
    uptimes = data.get("uptimes") or []
    if player_index < len(uptimes):
        uptime = uptimes[player_index]
        return {
            "Feudal": uptime.get("feudal"),
            "Castle": uptime.get("castle"),
            "Imperial": uptime.get("imperial"),
        }
    return {}


def _timing_entry(start: Optional[int], duration: Optional[int]) -> dict[str, Any]:
    completion = start + duration if start is not None and duration is not None else None
    return {
        "click_time": start,
        "click_time_str": format_seconds(start),
        "completion_time": completion,
        "completion_time_str": format_seconds(completion),
    }


def _derive_age_clicks(actions: Iterable[dict[str, Any]]) -> dict[str, int]:
    tech_map = {
        "Feudal Age": "Feudal",
        "Castle Age": "Castle",
        "Imperial Age": "Imperial",
    }
    starts: dict[str, int] = {}
    for action in actions:
        if action.get("type") not in {"RESEARCH", "DE_RESEARCH"}:
            continue
        payload = action.get("payload", {})
        tech = payload.get("tech") or payload.get("name")
        if tech in tech_map:
            timestamp = _action_time(action)
            if timestamp is not None:
                starts[tech_map[tech]] = timestamp
    return starts


def extract_timings(data: dict[str, Any], player_index: int) -> dict[str, Any]:
    uptimes = _extract_uptimes(data, player_index)
    actions = _player_actions(data, player_index)
    clicks = _derive_age_clicks(actions)
    durations = {"Feudal": 130, "Castle": 160, "Imperial": 190}
    timings = {
        "ages": {
            age: _timing_entry(clicks.get(age) or uptimes.get(age), durations.get(age))
            for age in ("Feudal", "Castle", "Imperial")
        }
    }
    return timings


def extract_first_buildings(builds: list[dict[str, Any]]) -> dict[str, Any]:
    firsts: dict[str, Any] = {}
    for build in builds:
        building = build.get("building")
        key = BUILDING_KEYS.get(building)
        if not key:
            continue
        if key not in firsts:
            firsts[key] = build["time"]
    return {
        "times": firsts,
        "times_str": {key: format_seconds(val) for key, val in firsts.items()},
    }


def extract_first_units(unit_events: list[dict[str, Any]]) -> dict[str, Any]:
    firsts: dict[str, int] = {}
    for event in unit_events:
        line = event["line"]
        if line not in firsts and line != "unknown":
            firsts[line] = event["time"]
    return {
        "times": firsts,
        "times_str": {key: format_seconds(val) for key, val in firsts.items()},
    }


def aggregate_units(unit_events: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    by_type: dict[str, int] = {}
    by_line: dict[str, int] = {}
    for event in unit_events:
        unit = event["unit"] or "unknown"
        line = event["line"]
        by_type[unit] = by_type.get(unit, 0) + 1
        by_line[line] = by_line.get(line, 0) + 1
    return by_type, by_line


def snapshot_composition(
    unit_events: list[dict[str, Any]],
    duration: int,
    age_times: dict[str, Any],
    interval: int = 300,
) -> list[dict[str, Any]]:
    buckets = list(range(0, max(duration, 0) + interval, interval))
    for age in ("Feudal", "Castle", "Imperial"):
        time_val = age_times.get(age, {}).get("click_time")
        if time_val is not None and time_val not in buckets:
            buckets.append(time_val)
    buckets = sorted(set(buckets))
    snapshots = []
    events_sorted = sorted(unit_events, key=lambda item: item["time"])
    idx = 0
    totals: dict[str, int] = {}
    for bucket in buckets:
        while idx < len(events_sorted) and events_sorted[idx]["time"] <= bucket:
            line = events_sorted[idx]["line"]
            totals[line] = totals.get(line, 0) + 1
            idx += 1
        military_total = sum(
            count
            for line, count in totals.items()
            if line not in {"villager", "fishing_ship", "trade"}
        )
        gold_total = sum(
            count for line, count in totals.items() if line in GOLD_LINES
        )
        trash_total = sum(
            count for line, count in totals.items() if line in TRASH_LINES
        )
        snapshots.append(
            {
                "time": bucket,
                "time_str": format_seconds(bucket),
                "totals_by_line": dict(totals),
                "military_total": military_total,
                "villagers_total_proxy": totals.get("villager", 0),
                "gold_units_total": gold_total,
                "trash_units_total": trash_total,
                "gold_pct": (gold_total / military_total) if military_total else None,
                "trash_pct": (trash_total / military_total) if military_total else None,
            }
        )
    return snapshots


def _collect_market_actions(actions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    first_buy = None
    first_sell = None
    buy_count = 0
    sell_count = 0
    for action in actions:
        if action.get("type") in {"BUY", "DE_BUY"}:
            timestamp = _action_time(action)
            if timestamp is not None and first_buy is None:
                first_buy = timestamp
            buy_count += 1
        if action.get("type") in {"SELL", "DE_SELL"}:
            timestamp = _action_time(action)
            if timestamp is not None and first_sell is None:
                first_sell = timestamp
            sell_count += 1
    return {
        "first_buy": first_buy,
        "first_buy_str": format_seconds(first_buy),
        "first_sell": first_sell,
        "first_sell_str": format_seconds(first_sell),
        "buy_count": buy_count,
        "sell_count": sell_count,
    }


def _collect_farms(builds: list[dict[str, Any]]) -> dict[str, Any]:
    farm_times = [b["time"] for b in builds if b.get("building") == "Farm"]
    farm_times = sorted(farm_times)
    milestones = {1: None, 5: None, 10: None}
    for count in milestones:
        if len(farm_times) >= count:
            milestones[count] = farm_times[count - 1]
    return {
        "total": len(farm_times),
        "milestones": {
            "first": milestones[1],
            "five": milestones[5],
            "ten": milestones[10],
        },
        "milestones_str": {
            "first": format_seconds(milestones[1]),
            "five": format_seconds(milestones[5]),
            "ten": format_seconds(milestones[10]),
        },
    }


def _collect_tc_idle(
    unit_events: list[dict[str, Any]],
    builds: list[dict[str, Any]],
    duration: int,
    age_times: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    villager_events = [e for e in unit_events if e["line"] == "villager"]
    villager_events = sorted(villager_events, key=lambda item: item["time"])
    tc_builds = [b for b in builds if b.get("building") == "Town Center"]
    tc_ids = {obj_id for b in tc_builds for obj_id in b.get("object_ids", [])}
    had_ids = bool(tc_ids)
    idle_total = 0
    per_age = {"Dark": 0, "Feudal": 0, "Castle": 0, "Imperial": 0}

    def add_idle(start: int, end: int) -> None:
        nonlocal idle_total
        gap = max(0, end - start)
        idle_total += gap
        age_bounds = [
            ("Dark", 0, age_times["Feudal"]["click_time"]),
            ("Feudal", age_times["Feudal"]["click_time"], age_times["Castle"]["click_time"]),
            ("Castle", age_times["Castle"]["click_time"], age_times["Imperial"]["click_time"]),
            ("Imperial", age_times["Imperial"]["click_time"], duration),
        ]
        for label, start_age, end_age in age_bounds:
            if start_age is None:
                start_age = 0
            if end_age is None:
                end_age = duration
            overlap = max(0, min(end, end_age) - max(start, start_age))
            per_age[label] += overlap

    if had_ids:
        events_by_tc: dict[int, list[int]] = {tc_id: [] for tc_id in tc_ids}
        for event in villager_events:
            for obj_id in event.get("object_ids", []):
                if obj_id in events_by_tc:
                    events_by_tc[obj_id].append(event["time"])
        for times in events_by_tc.values():
            times = sorted(times)
            last_time = 0
            for time in times:
                gap = time - last_time - 25
                if gap > 5:
                    add_idle(last_time + 25, time)
                last_time = time
            if last_time and duration > last_time + 25:
                add_idle(last_time + 25, duration)
    else:
        last_time = 0
        for event in villager_events:
            time = event["time"]
            gap = time - last_time - 25
            if gap > 5:
                add_idle(last_time + 25, time)
            last_time = time
        if last_time and duration > last_time + 25:
            add_idle(last_time + 25, duration)

    return {
        "total": idle_total,
        "total_str": format_seconds(idle_total),
        "by_age": per_age,
    }, not had_ids


def _collect_production_idle_flags(
    unit_events: list[dict[str, Any]],
    builds: list[dict[str, Any]],
    duration: int,
    idle_threshold: int = 60,
) -> tuple[list[dict[str, Any]], bool]:
    events_by_id: dict[int, list[int]] = {}
    for event in unit_events:
        for obj_id in event.get("object_ids", []):
            events_by_id.setdefault(obj_id, []).append(event["time"])
    flags: list[dict[str, Any]] = []
    missing_ids = False
    for build in builds:
        building = build.get("building")
        if building not in PRODUCTION_BUILDINGS:
            continue
        if not build.get("object_ids"):
            missing_ids = True
            continue
        for obj_id in build.get("object_ids", []):
            times = sorted(events_by_id.get(obj_id, []))
            last_time = build["time"]
            for time in times:
                if time - last_time > idle_threshold:
                    flags.append(
                        {
                            "building": building,
                            "object_id": obj_id,
                            "start": last_time,
                            "duration": time - last_time,
                        }
                    )
                last_time = time
            if duration - last_time > idle_threshold:
                flags.append(
                    {
                        "building": building,
                        "object_id": obj_id,
                        "start": last_time,
                        "duration": duration - last_time,
                    }
                )
    for flag in flags:
        flag["start_str"] = format_seconds(flag["start"])
        flag["duration_str"] = format_seconds(flag["duration"])
    return flags, missing_ids


def _detect_switches(
    opponent_snapshots: list[dict[str, Any]],
    you_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    switch_events: list[dict[str, Any]] = []
    response_delays: list[dict[str, Any]] = []
    missed: list[dict[str, Any]] = []
    for prev, curr in zip(opponent_snapshots, opponent_snapshots[1:]):
        for line, count in curr["totals_by_line"].items():
            prev_count = prev["totals_by_line"].get(line, 0)
            if line in {"villager", "fishing_ship", "trade", "unknown"}:
                continue
            if count - prev_count >= 5 and prev_count <= 2:
                switch_events.append(
                    {
                        "time": curr["time"],
                        "time_str": curr["time_str"],
                        "opponent_line": line,
                        "delta": count - prev_count,
                        "confidence": "low",
                    }
                )
    for event in switch_events:
        opp_line = event["opponent_line"]
        counters = COUNTER_MAP.get(opp_line, [])
        response = None
        for snapshot in you_snapshots:
            if snapshot["time"] < event["time"]:
                continue
            for counter in counters:
                if snapshot["totals_by_line"].get(counter, 0) >= 3:
                    response = {
                        "opponent_line": opp_line,
                        "your_line": counter,
                        "response_time": snapshot["time"],
                        "response_time_str": snapshot["time_str"],
                        "delay": snapshot["time"] - event["time"],
                    }
                    break
            if response:
                break
        if response:
            response["delay_str"] = format_seconds(response["delay"])
            response["confidence"] = "low"
            response_delays.append(response)
        else:
            missed.append(
                {
                    "opponent_line": opp_line,
                    "suggested_counters": counters,
                    "confidence": "low",
                }
            )
    return {
        "switch_events": switch_events,
        "response_delay_vs_opponent": response_delays,
        "missed_counter_opportunities": missed,
    }


def _actions_per_minute(actions: list[dict[str, Any]], duration: int) -> list[dict[str, Any]]:
    bins = [0] * (max(duration, 0) // 60 + 1)
    for action in actions:
        ts = _action_time(action)
        if ts is None:
            continue
        index = min(ts // 60, len(bins) - 1)
        bins[index] += 1
    return [
        {"minute": idx, "actions": count}
        for idx, count in enumerate(bins)
    ]


def analyze_replay(
    data: dict[str, Any],
    you_name: str | None,
    you_player: int | None,
    export_level: str,
) -> dict[str, Any]:
    players = data.get("players", [])
    if len(players) < 1:
        raise ValueError("No players found in replay data.")
    you, opponent = find_player(players, you_name, you_player)
    you_index = players.index(you)
    opp_index = players.index(opponent)

    match_info = extract_match_info(data)
    duration = coerce_seconds(match_info.get("duration") or 0) or 0

    you_actions = _player_actions(data, you_index)
    opp_actions = _player_actions(data, opp_index)
    you_units = _collect_unit_events(you_actions)
    opp_units = _collect_unit_events(opp_actions)
    you_builds = _collect_build_events(you_actions)
    opp_builds = _collect_build_events(opp_actions)

    you_timings = extract_timings(data, you_index)
    opp_timings = extract_timings(data, opp_index)

    you_first_buildings = extract_first_buildings(you_builds)
    opp_first_buildings = extract_first_buildings(opp_builds)

    you_first_units = extract_first_units(you_units)
    opp_first_units = extract_first_units(opp_units)

    you_units_by_type, you_units_by_line = aggregate_units(you_units)
    opp_units_by_type, opp_units_by_line = aggregate_units(opp_units)

    you_snapshots = snapshot_composition(
        you_units, duration, you_timings["ages"]
    )
    opp_snapshots = snapshot_composition(
        opp_units, duration, opp_timings["ages"]
    )

    you_farms = _collect_farms(you_builds)
    opp_farms = _collect_farms(opp_builds)

    you_market = _collect_market_actions(you_actions)
    opp_market = _collect_market_actions(opp_actions)

    you_tc_idle, you_tc_missing = _collect_tc_idle(
        you_units, you_builds, duration, you_timings["ages"]
    )
    opp_tc_idle, opp_tc_missing = _collect_tc_idle(
        opp_units, opp_builds, duration, opp_timings["ages"]
    )

    you_idle_flags, you_prod_missing = _collect_production_idle_flags(
        you_units, you_builds, duration
    )
    opp_idle_flags, opp_prod_missing = _collect_production_idle_flags(
        opp_units, opp_builds, duration
    )

    counters = _detect_switches(opp_snapshots, you_snapshots)

    warnings = [
        "Cancellations and build destructions are not tracked.",
    ]
    if you_tc_missing or opp_tc_missing:
        warnings.append(
            "Missing object IDs for some queue events; idle times estimated overall."
        )
    if you_prod_missing or opp_prod_missing:
        warnings.append(
            "Missing object IDs for some production buildings; idle flags may be incomplete."
        )

    coach_view = {
        "timings": {
            "you": you_timings,
            "opponent": opp_timings,
        },
        "first_buildings": {
            "you": you_first_buildings,
            "opponent": opp_first_buildings,
        },
        "first_units": {
            "you": you_first_units,
            "opponent": opp_first_units,
        },
        "units": {
            "you": {
                "created_totals_by_type": you_units_by_type,
                "created_totals_by_line": you_units_by_line,
                "composition_snapshots": you_snapshots,
            },
            "opponent": {
                "created_totals_by_type": opp_units_by_type,
                "created_totals_by_line": opp_units_by_line,
                "composition_snapshots": opp_snapshots,
            },
        },
        "eco_health": {
            "you": {
                "tc_idle_time": you_tc_idle,
                "farms": you_farms,
                "market": you_market,
            },
            "opponent": {
                "tc_idle_time": opp_tc_idle,
                "farms": opp_farms,
                "market": opp_market,
            },
        },
        "production": {
            "you": {"idle_flags": you_idle_flags},
            "opponent": {"idle_flags": opp_idle_flags},
        },
        "counters": {
            "you": counters,
            "opponent": {"switch_events": [], "response_delay_vs_opponent": []},
        },
        "tech": {
            "you": {},
            "opponent": {},
            "categories": TECH_CATEGORIES,
        },
    }

    raw_section = {
        "actions_per_minute": {
            "you": _actions_per_minute(you_actions, duration),
            "opponent": _actions_per_minute(opp_actions, duration),
        }
    }

    result = {
        "schema_version": "0.4.0",
        "export_level": export_level,
        "match": match_info,
        "players": {
            "you": {
                "name": you.get("name"),
                "civilization": you.get("civilization"),
                "winner": you.get("winner"),
            },
            "opponent": {
                "name": opponent.get("name"),
                "civilization": opponent.get("civilization"),
                "winner": opponent.get("winner"),
            },
        },
        "coach_view": coach_view,
        "raw": raw_section,
        "warnings": warnings,
        "notes": [
            "Queued units represent commands, not surviving units.",
        ],
    }
    return result


def build_prompt(match: dict[str, Any], players: dict[str, Any]) -> str:
    you = players["you"]
    opp = players["opponent"]
    summary = (
        f"Map: {match.get('map')}. "
        f"You ({you.get('civilization')}) vs {opp.get('civilization')}. "
        f"Result: {'Win' if you.get('winner') else 'Loss'}."
    )
    return (
        "# AoE2 KillCoach v4 Prompt\n\n"
        f"{summary}\n\n"
        "## Coaching Instructions\n"
        "- Focus on high-impact coaching points based on timings, units, eco, and counters.\n"
        "- Reference coach_view sections for timings, eco health, unit composition, and counters.\n"
        "- Provide actionable, prioritized feedback with timestamps when possible.\n"
        "- Avoid repeating raw JSON; summarize insights concisely.\n"
    )


def build_tsv_row(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    match = result["match"]
    you = result["players"]["you"]
    opp = result["players"]["opponent"]
    timings_you = result["coach_view"]["timings"]["you"]["ages"]
    timings_opp = result["coach_view"]["timings"]["opponent"]["ages"]
    columns = [
        "timestamp",
        "map",
        "you_name",
        "opponent_name",
        "you_civ",
        "opponent_civ",
        "result",
        "duration",
        "you_feudal_click",
        "you_castle_click",
        "you_imp_click",
        "opp_feudal_click",
        "opp_castle_click",
        "opp_imp_click",
        "you_tc_idle_total",
        "opp_tc_idle_total",
    ]
    row = [
        str(match.get("timestamp") or ""),
        str(match.get("map") or ""),
        str(you.get("name") or ""),
        str(opp.get("name") or ""),
        str(you.get("civilization") or ""),
        str(opp.get("civilization") or ""),
        "Win" if you.get("winner") else "Loss",
        str(match.get("duration") or ""),
        str(timings_you["Feudal"]["click_time_str"] or ""),
        str(timings_you["Castle"]["click_time_str"] or ""),
        str(timings_you["Imperial"]["click_time_str"] or ""),
        str(timings_opp["Feudal"]["click_time_str"] or ""),
        str(timings_opp["Castle"]["click_time_str"] or ""),
        str(timings_opp["Imperial"]["click_time_str"] or ""),
        str(result["coach_view"]["eco_health"]["you"]["tc_idle_time"]["total"]),
        str(result["coach_view"]["eco_health"]["opponent"]["tc_idle_time"]["total"]),
    ]
    return columns, row


def write_outputs(
    result: dict[str, Any],
    out_dir: Path,
    tsv_mode: str,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    match = result["match"]
    players = result["players"]
    timestamp = match.get("timestamp")
    if isinstance(timestamp, (int, float)):
        ts_str = datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d_%H%M")
    else:
        ts_str = datetime.utcnow().strftime("%Y-%m-%d_%H%M")
    name = f"{match.get('map','map')}_{players['you'].get('civilization','you')}_vs_{players['opponent'].get('civilization','opp')}_{ts_str}"
    friendly = sanitize_filename(name)
    json_path = out_dir / f"{friendly}.llm.json"
    prompt_path = out_dir / f"{friendly}.prompt.md"
    tsv_path = out_dir / "aoe2killcoach_stats.tsv"

    json_path.write_text(
        __import__("json").dumps(result, indent=2, ensure_ascii=False)
    )
    prompt_path.write_text(build_prompt(match, players))

    columns, row = build_tsv_row(result)
    write_header = tsv_mode == "header-row" or not tsv_path.exists()
    with tsv_path.open("a", encoding="utf-8") as handle:
        if write_header:
            handle.write("\t".join(columns) + "\n")
        handle.write("\t".join(row) + "\n")

    return {
        "json": json_path,
        "prompt": prompt_path,
        "tsv": tsv_path,
    }
