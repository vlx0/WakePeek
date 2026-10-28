"""Сборка сессий сна, без настоящего settings.json."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wakepeek.log import parse_payload
from wakepeek.sessions import Event, build_sessions, clip_sessions, format_span, parse_when, row_kind
from wakepeek.settings import load_days, save_days

TZ = timezone(timedelta(hours=5))


def at(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=TZ)


def pt(sleep: datetime, wake: datetime, source: str = "1", *rest: str) -> Event:
    sleep_utc = sleep.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    wake_utc = wake.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    props = [sleep_utc, wake_utc] + [""] * 8 + ["4", "5", source, "0", "", "0", "0", "0", "", ""]
    if rest:
        props = list(props)
        for index, value in enumerate(rest):
            props[14 + index] = value
    return Event(wake, 1, "pt", tuple(props))


def kp(when: datetime, reason: str = "7") -> Event:
    return Event(when, 42, "kp", ("4", "5", reason, "0", "1"))


class ParseTests(unittest.TestCase):
    def test_utc_sleep_and_marks(self) -> None:
        parsed = parse_when("\u200e2026-10-26T15:56:52.7251735Z")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 10)
        self.assertEqual(parsed.day, 26)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_payload_error_and_array(self) -> None:
        with self.assertRaises(Exception):
            parse_payload("ERR отказано в доступе")
        rows = parse_payload('[{"t":"2026-10-26T21:15:33+05:00","id":1,"src":"pt","p":[]}]')
        self.assertEqual(rows[0]["src"], "pt")


class SessionTests(unittest.TestCase):
    def test_power_button_and_idle(self) -> None:
        sleep = at(26, 20, 56, 53)
        wake = at(26, 21, 15, 33)
        events = [pt(sleep, wake, "1"), kp(sleep, "7")]
        sessions = build_sessions(events)
        self.assertEqual(len(sessions), 1)
        item = sessions[0]
        self.assertEqual(row_kind(item), "кнопка питания")
        self.assertEqual(item.mode, "гибридный сон")
        self.assertEqual(item.why, "простои")
        self.assertEqual(item.wake.astimezone(TZ), wake)

    def test_unknown_source_stays_unknown(self) -> None:
        sleep = at(25, 21, 23, 1)
        wake = at(26, 16, 9, 46)
        sessions = build_sessions([pt(sleep, wake, "0")])
        self.assertEqual(sessions[0].source, "журнал не записал")
        self.assertEqual(sessions[0].why, "")

    def test_device_text(self) -> None:
        sleep = at(26, 19, 6, 12)
        wake = at(26, 19, 34, 57)
        item = build_sessions([pt(sleep, wake, "4", "HID-compliant mouse")])[0]
        self.assertEqual(item.source, "устройство")
        self.assertEqual(item.device, "HID-compliant mouse")

    def test_newer_first(self) -> None:
        older = pt(at(26, 19, 6, 12), at(26, 19, 34, 57), "1")
        newer = pt(at(27, 14, 17, 27), at(27, 15, 50, 18), "1")
        sessions = build_sessions([older, newer])
        self.assertGreater(
            sessions[0].wake or sessions[0].sleep,
            sessions[1].wake or sessions[1].sleep,
        )

    def test_clip_and_span(self) -> None:
        now = at(27, 18, 0)
        old = pt(at(1, 10, 0), at(1, 11, 0), "1")
        fresh = pt(at(26, 20, 0), at(26, 20, 20), "1")
        shown = clip_sessions(build_sessions([old, fresh]), 14, now)
        self.assertEqual(len(shown), 1)
        self.assertEqual(format_span(at(26, 20, 0, 0), at(26, 20, 0, 20)), "меньше минуты")


class SettingsTests(unittest.TestCase):
    def test_roundtrip_in_temp(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            save_days(30, root)
            self.assertEqual(load_days(root), 30)
            save_days(3, root)
            self.assertEqual(load_days(root), 14)


if __name__ == "__main__":
    unittest.main()
