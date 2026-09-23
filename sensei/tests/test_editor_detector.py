import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import editor_detector as ed


def _undo(ts, file=None):
    return {"type": "undo", "ts": ts, "file": file}


def _edit(ts, file=None):
    return {"type": "edit", "ts": ts, "file": file}


def test_empty_events_finds_nothing():
    assert ed.find_undo_storms([]) == []


def test_below_min_undos_not_flagged():
    events = [_undo(0), _undo(1), _undo(2)]  # only 3, default min is 4
    assert ed.find_undo_storms(events) == []


def test_finds_a_simple_storm():
    events = [_undo(0), _undo(1), _undo(2), _undo(3)]
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert len(storms) == 1
    assert storms[0]["count"] == 4
    assert storms[0]["start_ts"] == 0
    assert storms[0]["end_ts"] == 3


def test_non_undo_event_breaks_the_run():
    events = [_undo(0), _undo(1), _edit(2), _undo(3), _undo(4)]
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert storms == []  # two runs of 2, neither reaches min_undos


def test_storm_spanning_too_long_is_not_flagged():
    events = [_undo(0), _undo(10), _undo(20), _undo(60)]  # 60s span
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert storms == []


def test_storm_within_window_is_flagged():
    events = [_undo(0), _undo(10), _undo(20), _undo(29)]  # 29s span
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert len(storms) == 1


def test_different_files_do_not_merge_into_one_storm():
    events = [_undo(0, "a.py"), _undo(1, "a.py"), _undo(2, "b.py"), _undo(3, "b.py")]
    storms = ed.find_undo_storms(events, min_undos=2, window_seconds=30)
    assert len(storms) == 2
    files = {s["file"] for s in storms}
    assert files == {"a.py", "b.py"}


def test_trailing_run_at_end_of_events_is_still_flushed():
    events = [_edit(0), _undo(1), _undo(2), _undo(3), _undo(4)]
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert len(storms) == 1
    assert storms[0]["start_ts"] == 1


def test_two_separate_storms_both_found():
    events = (
        [_undo(0), _undo(1), _undo(2), _undo(3)]
        + [_edit(10)]
        + [_undo(20), _undo(21), _undo(22), _undo(23)]
    )
    storms = ed.find_undo_storms(events, min_undos=4, window_seconds=30)
    assert len(storms) == 2
    assert storms[0]["start_ts"] == 0
    assert storms[1]["start_ts"] == 20


def test_storm_key_stable_and_distinguishes_storms():
    s1 = {"file": "a.py", "start_ts": 100.0, "count": 4}
    s2 = {"file": "a.py", "start_ts": 100.0, "count": 4}
    s3 = {"file": "a.py", "start_ts": 200.0, "count": 4}
    assert ed.storm_key(s1) == ed.storm_key(s2)
    assert ed.storm_key(s1) != ed.storm_key(s3)


def test_format_storm_message_includes_count_and_file():
    storm = {"count": 5, "file": "app.py", "start_ts": 0, "end_ts": 1}
    message = ed.format_storm_message(storm)
    assert "5 undos" in message
    assert "app.py" in message


def test_format_storm_message_handles_missing_file():
    storm = {"count": 5, "file": None, "start_ts": 0, "end_ts": 1}
    message = ed.format_storm_message(storm)
    assert "5 undos" in message
    assert " on " not in message
