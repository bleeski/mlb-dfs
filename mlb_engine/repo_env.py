"""repo_env.py -- one place that knows where this repo keeps its secrets.

R29(5a). The repo's ``.env`` holds THE_ODDS_API_KEY, and it is loaded for every
session that runs ``tools/fetch_slate_bundle.py``, because that script carries a
small ``.env`` loader of its own. Nothing else did. ``build_slate.py``'s odds
auto-fetch read ``os.environ`` directly, which is empty in a Cowork bash call
unless something exported it first, so the build reported

    no --odds file and THE_ODDS_API_KEY unset

and then

    no moneyline matched this game's teams; entries split evenly between the
    two sides

with the key sitting three files away. The build allocated a 50/50 thesis split
against a market that had the game priced the whole time. On the 2026-07-29
TEX@TB Showdown that happened to round to the same lineup counts at n=20, so
nothing shipped wrong by luck rather than by design.

The loader lives here rather than in either caller so there is one answer to
"where does the key come from". An explicit environment variable always wins
over the file, so ``export`` still overrides and a scheduled task's injected
secret is never clobbered by a stale checkout.

Nothing here logs, echoes, prints or returns file contents beyond the single
requested value, per the repo's hard guardrail on API keys.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = REPO_ROOT / ".env"
ODDS_KEY_ENV = "THE_ODDS_API_KEY"


def parse_dotenv(path: Path) -> Dict[str, str]:
    """``KEY=VALUE`` lines from a ``.env`` file. Blank and ``#`` lines skipped.

    Returns an empty dict for a missing or unreadable file: a secrets file that
    is absent is a normal state (a fresh clone), not an error to raise through a
    build.
    """
    values: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def load_repo_dotenv(path: Optional[Path] = None) -> list[str]:
    """Populate ``os.environ`` from the repo ``.env``. Returns the names set.

    Never overrides a variable already present in the real environment, so an
    explicit ``export`` always wins over the file. Returns names only, never
    values, so a caller may log what it loaded without leaking anything.
    """
    loaded: list[str] = []
    for key, value in parse_dotenv(path or DOTENV_PATH).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def resolve_secret(name: str, path: Optional[Path] = None) -> Optional[str]:
    """A secret from the environment, falling back to the repo ``.env``.

    Resolution order is environment first, file second. The environment is where
    a deliberate override lives; the file is the default that is guaranteed to
    exist for every session on this project regardless of the mount layout.
    """
    from_env = os.environ.get(name)
    if from_env and from_env.strip():
        return from_env.strip()
    value = parse_dotenv(path or DOTENV_PATH).get(name)
    return value.strip() if value and value.strip() else None


def resolve_odds_api_key(path: Optional[Path] = None) -> Optional[str]:
    """THE_ODDS_API_KEY, from the environment or the repo ``.env``."""
    return resolve_secret(ODDS_KEY_ENV, path)


# ---------------------------------------------------------------------------
# The one ET calendar authority (R65)
# ---------------------------------------------------------------------------
# Baseball's day is an Eastern-time day. This container runs on UTC, so
# ``date.today()`` rolls over at 8pm ET (7pm in EST months) and every caller
# that used it was answering a different question than the one it asked:
#
#   - build_slate's RotoWire gate compared args.date to the LOCAL today, so a
#     build started after 8pm ET for tonight's slate fell out of RotoWire's
#     today/tomorrow window entirely and skipped the merge in silence, leaving
#     the platoon staleness clock uncleared; and a build for TOMORROW's ET slate
#     resolved to "today", fetching the wrong ET day's page and stamping it with
#     args.date -- wrong-day batting orders wearing a fresh collected_date,
#     which defeats the staleness rule from the inside.
#   - fetch_rotowire_lineups defaulted collected_date the same way.
#   - fetch_slate_bundle approximated ET as a hardcoded UTC-4, which is an hour
#     wrong in EST months and flips the DATE for any instant between 04:00 and
#     05:00 UTC.
#
# ZoneInfo is stdlib from 3.9, so this file stays dependency-free and remains
# importable by the tools that carry their own loaders.

ET_ZONE_NAME = "America/New_York"


def now_et(now=None):
    """Current time as an aware datetime in America/New_York.

    ``now`` accepts any aware datetime and is converted; it exists so callers
    and tests can inject an instant instead of monkeypatching a clock. A naive
    datetime is rejected rather than assumed to be in any particular zone,
    because guessing is how this class of bug started.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo
    eastern = ZoneInfo(ET_ZONE_NAME)
    if now is None:
        return datetime.now(eastern)
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError("now must be timezone-aware; a naive datetime has no ET")
    return now.astimezone(eastern)


def today_et(now=None) -> str:
    """Today's ET calendar date as YYYY-MM-DD.

    Use this anywhere a slate date, a collected_date, or a today/tomorrow
    comparison is being computed. Never ``date.today()``: that is the
    container's calendar, and it is not the one the schedule runs on.
    """
    return now_et(now).date().isoformat()


def et_day_offsets(days: int = 1, now=None):
    """``(today_et, today_et + days)`` from ONE clock reading.

    Two separate ``date.today()`` calls can straddle midnight and return dates
    that are not one day apart, which is how the RotoWire gate could compute a
    today/tomorrow pair spanning two days. One reading cannot.
    """
    from datetime import timedelta
    base = now_et(now).date()
    return base.isoformat(), (base + timedelta(days=days)).isoformat()
