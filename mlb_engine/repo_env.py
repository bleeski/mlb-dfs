"""repo_env.py -- one place that knows the environment this repo runs in.

Three authorities live here, each because the alternative was every caller
answering the same question differently: the secrets loader (R29(5a), below),
the ET calendar (R65), and the host profile (R349). Nothing here fetches, and
nothing here logs a secret.

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


# ---------------------------------------------------------------------------
# The one host authority (R349)
# ---------------------------------------------------------------------------
# Until 2026-09-16 this project knew two hosts and named exactly one budget:
# CLAUDE.md's "The Cowork inner bash budget is 130s. One number, this one."
# That number then became the argparse default of `solver_probe --budget` and
# `autobuild --call-budget-seconds`, so a host with a fifteen-minute ceiling was
# planning its calls against a two-minute one.
#
# The cost is not hypothetical. On the 2026-09-16 1910_7g slate the repo was at
# /home/user/mlb-dfs on a Claude Code container whose BASH_DEFAULT_TIMEOUT_MS is
# 900000, and the build ran a 420-second call without trouble -- while every
# default in the tree still described 130.
#
# So the budget stops being a constant and becomes a resolved fact, with the
# precedence `gate_call_ceiling()` in tools/audit.py already uses for its own
# ceiling: an explicit argument, then an environment variable, then a host
# profile, then a conservative default for a host that has told us nothing.
# PROBE, never guess: every signal below is something the host asserts about
# itself (a mount path, os.name, its own exported ceiling), never an inference
# from a session's flavour. A host that says nothing gets Cowork's 130, because
# under-spending a budget costs a slice and over-spending it costs the call.
#
# Two things this deliberately does NOT do. It never widens a budget a caller
# passed explicitly, and it is not a capability check: `has_rm` and `tmp_shared`
# describe what the sandbox allows, and a caller that can simply try the cheap
# thing and handle the failure should keep doing that rather than branch on a
# profile.

HOST_ENV = "MLB_DFS_HOST"
CALL_BUDGET_ENV = "MLB_DFS_CALL_BUDGET_S"
ROOT_ENV = "MLB_DFS_ROOT"

HOST_COWORK = "cowork"
HOST_CLAUDE_CODE = "claude_code"
HOST_WINDOWS = "windows"
HOST_UNKNOWN = "unknown"

# The floor for a host that has told us nothing. This is the number CLAUDE.md's
# ## Sandbox section has always named; what changed is that it is now one
# profile's value rather than every caller's default.
UNKNOWN_HOST_BUDGET_S = 130.0

# What fraction of a host's OWN declared ceiling is safe to plan inside. The
# remainder pays for container start, the ~15s engine import off a cold
# __pycache__, and the certify-and-write tail. 0.7 of 900s is 630s, which is
# comfortably past the 420s call that 1910_7g actually needed.
CALL_BUDGET_SAFE_FRACTION = 0.7

# Claude Code states its own bash ceiling in the environment (.claude/settings.json
# sets BASH_DEFAULT_TIMEOUT_MS / BASH_MAX_TIMEOUT_MS, and the client exports
# them), which is why this is a probe and not a guess about the session.
DECLARED_CEILING_ENV = "BASH_DEFAULT_TIMEOUT_MS"
DECLARED_MAX_CEILING_ENV = "BASH_MAX_TIMEOUT_MS"

HOST_PROFILES: Dict[str, Dict[str, object]] = {
    # No `rm` (mv into _to_delete/), /tmp is not shared between calls, and the
    # host-backed mount stalls intermittently. docs/cowork_sandbox.md owns the
    # rest of the procedure.
    HOST_COWORK: {"call_budget_s": 130.0, "has_rm": False, "tmp_shared": False},
    # Measured 2026-09-16: /tmp persisted across four calls, rm works, and a
    # 420s build fit one call. The budget is derived from the host's own
    # declared ceiling when it states one, so this value is only the fallback.
    HOST_CLAUDE_CODE: {"call_budget_s": 600.0, "has_rm": True, "tmp_shared": True},
    # Ben's machine. PowerShell, so `TZ=... date` and `nohup` are not available,
    # but there is no inner call ceiling and the full gate runs in one call.
    HOST_WINDOWS: {"call_budget_s": 540.0, "has_rm": True, "tmp_shared": True},
    HOST_UNKNOWN: {"call_budget_s": UNKNOWN_HOST_BUDGET_S,
                   "has_rm": False, "tmp_shared": False},
}


def repo_root(stated: Optional[str] = None) -> Path:
    """This repo's root. ``MLB_DFS_ROOT`` wins when it names a real checkout.

    The override is validated rather than trusted: a path that does not carry
    both ``mlb_engine/`` and ``CLAUDE.md`` is not this repo, and silently
    honouring it would point a build at a directory with no engine in it.
    """
    raw = stated if stated is not None else os.environ.get(ROOT_ENV, "")
    raw = (raw or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if (candidate / "mlb_engine").is_dir() and (candidate / "CLAUDE.md").is_file():
            return candidate.resolve()
    return REPO_ROOT


def detect_host(root: Optional[Path] = None,
                env: Optional[Dict[str, str]] = None) -> str:
    """Which host this process is running on, by probing what it asserts.

    Order: an explicit ``MLB_DFS_HOST``; the repo living under a
    ``/sessions/*/mnt/`` mount, which is Cowork's one reliable signature;
    ``os.name == "nt"`` for Ben's machine; a host that exported its own bash
    ceiling, which is Claude Code; otherwise unknown.

    Returns a key of ``HOST_PROFILES``, never ``None``, so no caller needs a
    fallback branch of its own.
    """
    environ = os.environ if env is None else env
    stated = (environ.get(HOST_ENV) or "").strip().lower()
    if stated in HOST_PROFILES and stated != HOST_UNKNOWN:
        return stated
    where = Path(root) if root is not None else repo_root()
    try:
        parts = where.resolve().parts
    except OSError:
        parts = where.parts
    if "sessions" in parts and "mnt" in parts:
        return HOST_COWORK
    if os.name == "nt":
        return HOST_WINDOWS
    for key in (DECLARED_CEILING_ENV, DECLARED_MAX_CEILING_ENV):
        if (environ.get(key) or "").strip():
            return HOST_CLAUDE_CODE
    return HOST_UNKNOWN


def declared_ceiling_s(env: Optional[Dict[str, str]] = None) -> Optional[float]:
    """The host's own bash ceiling in seconds, when it states one.

    ``None`` when nothing is declared or the value does not parse, so a caller
    can tell "this host says nothing" from "this host says zero".
    """
    environ = os.environ if env is None else env
    raw = (environ.get(DECLARED_CEILING_ENV) or "").strip()
    if not raw:
        return None
    try:
        seconds = float(raw) / 1000.0
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def call_budget_s(explicit: Optional[float] = None,
                  host: Optional[str] = None,
                  env: Optional[Dict[str, str]] = None) -> float:
    """Seconds of real work it is safe to plan inside ONE call on this host.

    Precedence, matching ``tools/audit.py``'s ``gate_call_ceiling``: an explicit
    argument, then ``MLB_DFS_CALL_BUDGET_S``, then this host's own declared
    ceiling discounted by ``CALL_BUDGET_SAFE_FRACTION``, then the host profile,
    then 130.0.

    A host's declared ceiling is used as stated even when it is SMALLER than
    130: flooring it up would hand back a budget that overruns the call, which
    is the failure this function exists to prevent.

    The declared ceiling is read for ``claude_code`` ONLY. Cowork and Ben's
    machine take their profile number, because a stated host is a claim about
    which sandbox this is and an ambient ``BASH_DEFAULT_TIMEOUT_MS`` from
    whatever shell wrapped the call is not evidence against it. The first cut
    read the ceiling unconditionally and answered 630.0 for
    ``MLB_DFS_HOST=cowork``, which is the 130s budget quietly lost again by a
    different route.
    """
    environ = os.environ if env is None else env
    if explicit is not None:
        return float(explicit)
    raw = (environ.get(CALL_BUDGET_ENV) or "").strip()
    if raw:
        try:
            stated = float(raw)
            if stated > 0:
                return stated
        except ValueError:
            pass
    resolved_host = host or detect_host(env=environ)
    if resolved_host == HOST_CLAUDE_CODE:
        declared = declared_ceiling_s(env=environ)
        if declared is not None:
            return round(declared * CALL_BUDGET_SAFE_FRACTION, 1)
    return float(HOST_PROFILES[resolved_host]["call_budget_s"])


def host_profile(host: Optional[str] = None,
                 env: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """This host's profile, with ``host`` and the resolved budget folded in.

    One call answers every host question a caller has, so nothing has to pair a
    ``detect_host`` with a separate lookup and risk the two disagreeing.
    """
    environ = os.environ if env is None else env
    resolved = host or detect_host(env=environ)
    profile = dict(HOST_PROFILES[resolved])
    profile["host"] = resolved
    profile["call_budget_s"] = call_budget_s(host=resolved, env=environ)
    profile["declared_ceiling_s"] = declared_ceiling_s(env=environ)
    return profile


def call_budget_source(explicit: Optional[float] = None,
                       env: Optional[Dict[str, str]] = None) -> str:
    """Where the budget in force came from, for a verdict to quote.

    R290(c) established that a refusal an operator reads under a clock has to
    name the ceiling it was measured against. Now that the ceiling is resolved
    rather than constant, it has to name the SOURCE too, or a session cannot
    tell a real overrun from a host mismatch.
    """
    environ = os.environ if env is None else env
    if explicit is not None:
        return "supplied by the caller"
    if (environ.get(CALL_BUDGET_ENV) or "").strip():
        return f"CLAUDE.md Hosts: stated by {CALL_BUDGET_ENV}"
    resolved = detect_host(env=environ)
    if (resolved == HOST_CLAUDE_CODE
            and declared_ceiling_s(env=environ) is not None):
        return (f"CLAUDE.md Hosts: {resolved}, "
                f"{CALL_BUDGET_SAFE_FRACTION:g} of its own declared "
                f"{DECLARED_CEILING_ENV}")
    if resolved == HOST_UNKNOWN:
        return ("CLAUDE.md Sandbox: this host stated nothing, so the "
                "conservative Cowork budget applies")
    return f"CLAUDE.md Hosts: the {resolved} profile"
