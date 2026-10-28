"""Сборка сессий сна: когда уснул, когда проснулся, что разбудило."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PT_WAKE = 1
KP_SLEEP = 42
_NEAR = timedelta(seconds=8)

# Проверено на живом журнале: тип 1 → «Кнопка питания». Остальное — без выдумки.
_SOURCE = {
    1: "кнопка питания",
    2: "кнопка сна",
    6: "таймер",
    7: "крышка",
}

# Проверено: Reason 7 в Kernel-Power 42 → «System Idle».
_SLEEP_WHY = {
    7: "простои",
}


@dataclass
class Event:
    when: datetime
    id: int
    src: str
    props: tuple[str, ...]


@dataclass
class Session:
    sleep: datetime
    wake: datetime | None
    source: str
    device: str
    timer: str
    mode: str
    why: str


def clean_text(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf").strip()


def parse_when(text: str) -> datetime | None:
    raw = clean_text(text)
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _int(text: str) -> int | None:
    try:
        return int(clean_text(text), 0)
    except (TypeError, ValueError):
        return None


def _mode(target: int | None, effective: int | None) -> str:
    if target == 4 and effective == 5:
        return "гибридный сон"
    if effective == 5 or target == 5:
        return "гибернация"
    if effective == 4 or target == 4:
        return "сон"
    return ""


def _source(props: tuple[str, ...]) -> tuple[str, str, str]:
    kind = _int(props[12]) if len(props) > 12 else None
    device = clean_text(props[14]) if len(props) > 14 else ""
    timer = clean_text(props[18]) if len(props) > 18 else ""
    if device:
        return "устройство", device, timer
    if timer:
        return "таймер", device, timer
    if kind in _SOURCE:
        return _SOURCE[kind], device, timer
    return "журнал не записал", device, timer


def _why(props: tuple[str, ...]) -> str:
    code = _int(props[2]) if len(props) > 2 else None
    if code in _SLEEP_WHY:
        return _SLEEP_WHY[code]
    return ""


def build_sessions(events: list[Event]) -> list[Session]:
    wakes = [item for item in events if item.src == "pt" and item.id == PT_WAKE]
    sleeps = [item for item in events if item.src == "kp" and item.id == KP_SLEEP]
    sessions: list[Session] = []
    used: set[int] = set()
    for wake in wakes:
        start = parse_when(wake.props[0]) if wake.props else None
        end = parse_when(wake.props[1]) if len(wake.props) > 1 else None
        if start is None:
            start = wake.when
        if end is None:
            end = wake.when
        source, device, timer = _source(wake.props)
        target = _int(wake.props[10]) if len(wake.props) > 10 else None
        effective = _int(wake.props[11]) if len(wake.props) > 11 else None
        why = ""
        for index, sleep in enumerate(sleeps):
            if index in used:
                continue
            delta = abs((sleep.when.astimezone(timezone.utc) - start.astimezone(timezone.utc)).total_seconds())
            if delta <= _NEAR.total_seconds():
                used.add(index)
                why = _why(sleep.props)
                break
        sessions.append(
            Session(
                sleep=start,
                wake=end,
                source=source,
                device=device,
                timer=timer,
                mode=_mode(target, effective),
                why=why,
            )
        )
    sessions.sort(key=lambda item: _stamp(item.wake or item.sleep), reverse=True)
    return sessions


def _stamp(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def clip_sessions(sessions: list[Session], days: int, now: datetime) -> list[Session]:
    cutoff = now - timedelta(days=days)
    visible: list[Session] = []
    for session in sessions:
        stamp = session.wake or session.sleep
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=now.tzinfo)
        if stamp >= cutoff:
            visible.append(session)
    visible.sort(key=lambda item: _stamp(item.wake or item.sleep), reverse=True)
    return visible


def row_kind(session: Session) -> str:
    return session.source or "журнал не записал"


_MONTHS = "янв фев мар апр май июн июл авг сен окт ноя дек".split()


def format_when(moment: datetime) -> str:
    local = moment.astimezone() if moment.tzinfo else moment
    return f"{local.day} {_MONTHS[local.month - 1]}, {local:%H:%M}"


def format_span(start: datetime, end: datetime) -> str:
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        return "—"
    if seconds < 60:
        return "меньше минуты"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    days, hours = divmod(hours, 24)
    return f"{days} д {hours} ч" if hours else f"{days} д"
