from aoe2killcoach4.core import (
    build_prompt,
    build_tsv_row,
    format_seconds,
    sanitize_filename,
    snapshot_composition,
)


def test_format_seconds():
    assert format_seconds(None) is None
    assert format_seconds(0) == "0:00"
    assert format_seconds(125) == "2:05"


def test_sanitize_filename():
    assert sanitize_filename("Arabia vs. Arena") == "Arabia_vs_Arena"
    assert sanitize_filename("a/b:c") == "a_b_c"


def test_snapshot_composition_basic():
    events = [
        {"time": 10, "line": "villager"},
        {"time": 20, "line": "archer_line"},
        {"time": 200, "line": "archer_line"},
    ]
    duration = 300
    age_times = {
        "Feudal": {"click_time": 130},
        "Castle": {"click_time": None},
        "Imperial": {"click_time": None},
    }
    snapshots = snapshot_composition(events, duration, age_times, interval=300)
    mid = next(item for item in snapshots if item["time"] == 130)
    end = snapshots[-1]
    assert mid["totals_by_line"]["villager"] == 1
    assert mid["totals_by_line"]["archer_line"] == 1
    assert end["totals_by_line"]["archer_line"] == 2


def test_build_prompt_and_tsv_row():
    result = {
        "match": {"map": "Arabia", "duration": 900, "timestamp": 0},
        "players": {
            "you": {"name": "You", "civilization": "Franks", "winner": True},
            "opponent": {
                "name": "Opp",
                "civilization": "Britons",
                "winner": False,
            },
        },
        "coach_view": {
            "timings": {
                "you": {
                    "ages": {
                        "Feudal": {"click_time_str": "10:00"},
                        "Castle": {"click_time_str": "20:00"},
                        "Imperial": {"click_time_str": "30:00"},
                    }
                },
                "opponent": {
                    "ages": {
                        "Feudal": {"click_time_str": "10:30"},
                        "Castle": {"click_time_str": "21:00"},
                        "Imperial": {"click_time_str": "31:00"},
                    }
                },
            },
            "eco_health": {
                "you": {"tc_idle_time": {"total": 100}},
                "opponent": {"tc_idle_time": {"total": 200}},
            },
        },
    }
    prompt = build_prompt(result["match"], result["players"])
    assert "Arabia" in prompt
    columns, row = build_tsv_row(result)
    assert columns[0] == "timestamp"
    assert row[4] == "Franks"
