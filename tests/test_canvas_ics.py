from datetime import datetime

from aggregator.fetchers.canvas_ics import TZ, parse_ics

SAMPLE_ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//test//canvas sample//EN",
        # Timed assignment: 03:59 UTC on Oct 6 == 11:59 PM EDT on Oct 5
        "BEGIN:VEVENT",
        "UID:event-assignment-111",
        "DTSTART:20261006T035900Z",
        "SUMMARY:Homework 1 [PROB4203_001_2026_3]",
        "URL:https://courseworks2.columbia.edu/courses/1/assignments/111",
        "END:VEVENT",
        # All-day event
        "BEGIN:VEVENT",
        "UID:event-assignment-222",
        "DTSTART;VALUE=DATE:20261012",
        "SUMMARY:Midterm Project [ECON1105_001_2026_3]",
        "END:VEVENT",
        # No course suffix in the title
        "BEGIN:VEVENT",
        "UID:event-calendar-event-333",
        "DTSTART:20261020T150000Z",
        "SUMMARY:Office hours",
        "END:VEVENT",
        # Malformed: no UID, should be skipped
        "BEGIN:VEVENT",
        "DTSTART:20261021T150000Z",
        "SUMMARY:Broken event",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)


def test_parses_valid_events_and_skips_malformed():
    items = parse_ics(SAMPLE_ICS)
    assert len(items) == 3


def test_sorted_by_due_date():
    items = parse_ics(SAMPLE_ICS)
    assert [a.title for a in items] == ["Homework 1", "Midterm Project", "Office hours"]


def test_timed_event_converted_to_new_york():
    hw = parse_ics(SAMPLE_ICS)[0]
    assert hw.due_at == datetime(2026, 10, 5, 23, 59, tzinfo=TZ)
    assert hw.due_at.tzinfo is not None


def test_all_day_event_due_end_of_day():
    proj = parse_ics(SAMPLE_ICS)[1]
    assert proj.due_at == datetime(2026, 10, 12, 23, 59, tzinfo=TZ)


def test_course_and_title_split():
    hw = parse_ics(SAMPLE_ICS)[0]
    assert hw.course == "PROB4203_001_2026_3"
    assert hw.title == "Homework 1"
    assert hw.url.endswith("/assignments/111")


def test_missing_course_suffix_falls_back():
    office = parse_ics(SAMPLE_ICS)[2]
    assert office.course == "unknown"
    assert office.title == "Office hours"


def test_uid_is_namespaced_and_stable():
    first = [a.uid for a in parse_ics(SAMPLE_ICS)]
    second = [a.uid for a in parse_ics(SAMPLE_ICS)]
    assert first == second
    assert first[0] == "canvas:event-assignment-111"
