"""The prompt mix in the report: what tokunseba made of the opening prompts.

This is the only place a user sees why a routing rule is or is not firing, so the
interesting cases are the honest ones: an unsure judge, and an empty window.
"""
from __future__ import annotations

import time

from rich.console import Console

from tokunseba.cli import _mix_note
from tokunseba.ledger import DIFFICULTY_NAMES, Ledger
from tokunseba.ui.terminal import mix_table


def _render(renderable) -> str:
    out = Console(width=90, no_color=True, record=True)
    out.print(renderable)
    return out.export_text()


def _led(tmp_path) -> Ledger:
    return Ledger(tmp_path / "l.db")


def test_a_discarded_answer_is_counted_as_unsure(tmp_path):
    """A signal below the gate is absent from the payload, not zero. It still happened."""
    led = _led(tmp_path)
    led.record_event("route_signal", {"domain": "code", "domain_confidence": 0.9}, "s", "r")
    led.record_event("route_signal", {"domain_confidence": 0.4}, "s", "r")
    b = led.signal_breakdown(time.time() - 60)
    assert b["judged"] == 2
    assert b["domains"] == {"code": 1, "unsure": 1}
    assert b["levels"] == {"unsure": 2}


def test_difficulty_scores_become_names(tmp_path):
    led = _led(tmp_path)
    for score in (0.0, 1.0, 2.0, 3.0, 3.0):
        led.record_event("route_signal", {"difficulty": score}, "s", "r")
    b = led.signal_breakdown(time.time() - 60)
    assert b["levels"] == {"trivial": 1, "easy": 1, "moderate": 1, "hard": 2}
    assert b["confident"] == 5


def test_an_out_of_range_score_does_not_crash(tmp_path):
    """The judge promises a 0 to 3 scale. A backend that broke it must not break a report."""
    led = _led(tmp_path)
    led.record_event("route_signal", {"difficulty": 9.0}, "s", "r")
    assert led.signal_breakdown(time.time() - 60)["levels"] == {"hard": 1}


def test_corrupt_payloads_are_skipped_not_fatal(tmp_path):
    """One unreadable row must cost that row, not the section."""
    led = _led(tmp_path)
    led.record_event("route_signal", {"domain": "writing", "domain_confidence": 0.9}, "s", "r")
    led.record_event("route_signal", {"domain": "code", "domain_confidence": 0.9}, "s", "r")
    led._conn.execute("UPDATE events SET payload='{oops' WHERE payload LIKE '%writing%'")
    b = led.signal_breakdown(time.time() - 60)
    assert b["domains"] == {"code": 1}
    assert b["judged"] == 2


def test_the_window_is_respected(tmp_path):
    led = _led(tmp_path)
    led.record_event("route_signal", {"domain": "code", "domain_confidence": 0.9}, "s", "r")
    led._conn.execute("UPDATE events SET ts=ts-100000")
    assert led.signal_breakdown(time.time() - 60)["judged"] == 0


def test_scores_only_count_when_the_judge_said_yes(tmp_path):
    led = _led(tmp_path)
    led.record_event("route_signal", {"needs_tools": 1.0, "is_sensitive": 0.0}, "s", "r")
    led.record_event("route_signal", {"needs_tools": 0.0, "is_sensitive": 1.0}, "s", "r")
    b = led.signal_breakdown(time.time() - 60)
    assert b["needs_tools"] == 1
    assert b["sensitive"] == 1


def test_difficulty_rows_keep_their_natural_order():
    """Sorting difficulties by size would put hard above easy and read as nonsense."""
    text = _render(mix_table({"hard": 1, "trivial": 9, "moderate": 3}, "difficulty",
                             order=list(DIFFICULTY_NAMES)))
    assert text.index("trivial") < text.index("moderate") < text.index("hard")


def test_domain_rows_lead_with_the_biggest_and_end_with_unsure():
    text = _render(mix_table({"unsure": 40, "code": 5, "writing": 9}, "domain"))
    assert text.index("writing") < text.index("code") < text.index("unsure")


def test_an_empty_window_says_so_rather_than_rendering_nothing():
    assert "no prompts judged yet" in _render(mix_table({}, "domain"))
    assert "Nothing judged" in _mix_note({"judged": 0})


def test_the_note_names_the_command_when_there_is_easy_work():
    note = _mix_note({"judged": 10, "levels": {"trivial": 2, "easy": 1, "hard": 7}})
    assert "3 opened trivially or easily" in note
    assert "tokunseba route add" in note


def test_the_note_proposes_nothing_when_there_is_no_easy_work():
    note = _mix_note({"judged": 4, "levels": {"hard": 4}})
    assert "route add" not in note
    assert "4 conversations judged" in note


def test_the_report_renders_the_mix_on_an_empty_ledger(tmp_path):
    """Every report section has to survive a ledger with nothing in it."""
    from tokunseba.cli import _report_data, _report_group
    text = _render(_report_group(_report_data(_led(tmp_path), "7d")))
    assert "what you asked about" in text
    assert "how hard those prompts were" in text
