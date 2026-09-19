#!/usr/bin/env python3
"""retro.py -- the execution postmortem's deterministic half (R371).

WHY THIS EXISTS. `skills/generate-lineups/references/retro.md` asks a session,
after the hand-over, for the clock gap between gate-clean and delivery, every
degraded input, every number passed by hand, every tool that failed its
contract, and every brief key the skill names that this build's brief does not
carry. All five are facts already sitting in the artifacts. None of them is
extracted by anything: the only telemetry in the whole build is one `elapsed_s`
written at `build_slate.py:5456`. So every retro reconstructs them by reading
back through a session's own scrollback, which is the least reliable record in
the room and the first thing to go when the context compacts.

WHAT THIS IS NOT. It is not the retro. It files nothing, judges nothing, and
decides nothing. Whether a degraded input had a fallback somebody should have
reached for, whether twenty minutes on a dead end is a finding, and whether a
missing brief key is a docs defect or a correct conditional -- those are the
judgment half and they stay a skill step. Ben's call, 2026-09-18 (R362): the
retro is not a hook, and "the assistant stopped speaking" is not "a build
completed". This prints facts and stops.

WHAT IT READS. The R369 delivery record is the anchor, because it is tracked
and survives the container. The brief is read beside it out of `outputs/<date>/`
and is EPHEMERAL, which is exactly right for this tool: the retro runs in the
session that built the slate, minutes after the hand-over, while the brief is
still on disk. When it is gone the sections that need it say so by name rather
than coming back empty, because an empty section reads as "nothing was
degraded".
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SCHEMA_VERSION = 1

SKILL_MD = "skills/generate-lineups/SKILL.md"

#: Top-level brief keys, so a backticked dotted token in SKILL.md is only read
#: as a brief key when its ROOT is one the brief actually uses. Without this the
#: scan below picks up every module path and attribute in the document.
BRIEF_ROOTS = ("enrichment", "slate_clock", "pool", "exposure", "gates", "solve",
               "contests", "verification", "deadline", "leverage",
               "anti_correlation", "lineups_feed", "slate")

#: A dotted token ending in one of these is a filename, not a brief key
#: (`lineups_feed.json` is the sighting that made this necessary).
_FILE_SUFFIXES = ("json", "csv", "py", "md", "txt", "html", "log", "yml", "yaml")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------

def find_brief(root: Path, date: str, slate_tag: str) -> Optional[Path]:
    """The brief for this delivery, most specific first.

    `build_slate.py` writes `build_brief<suffix>.json` and a second
    slate-tagged copy `build_brief<suffix>_<tag>.json`, so evidence survives a
    same-date rebuild. The tagged copy is preferred for that reason: on a date
    with two draftgroups the bare name is whichever build ran last.
    """
    base = root / "outputs" / str(date)
    if not base.is_dir():
        return None
    tag = str(slate_tag or "").strip()
    if tag:
        tagged = sorted(base.glob(f"build_brief*_{tag}.json"))
        if tagged:
            return tagged[0]
    for name in ("build_brief.json",):
        if (base / name).is_file():
            return base / name
    any_brief = sorted(base.glob("build_brief*.json"))
    return any_brief[0] if any_brief else None


def _parse_utc(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _dig(payload: Any, dotted: str) -> Any:
    """``payload["a"]["b"]`` for ``"a.b"``; the sentinel below when absent."""
    node = payload
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return _MISSING
        node = node[part]
    return node


class _Missing:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<absent>"


_MISSING = _Missing()


# ---------------------------------------------------------------------------
# the five sections
# ---------------------------------------------------------------------------

def clock(record: Mapping[str, Any], brief: Optional[Mapping[str, Any]],
          handover_utc: str = "") -> Dict[str, Any]:
    """Gate-clean to hand-over, which is the one number retro.md asks for first.

    GATE-CLEAN is when the delivery row was written: `record_delivery` runs
    after the three gates, so its `recorded_utc` is the moment the file became
    the deliverable. HAND-OVER is when Ben got it, and NO artifact in this tree
    carries that stamp -- the session is the only thing that knows. So it is an
    argument, and without it this prints the gate-clean stamp and the command
    that reads the clock rather than inventing a gap. `elapsed_s` is the build's
    own wall time and is a different quantity: it ends where this one starts.
    """
    row = record.get("manifest_row") or {}
    gate_clean = _parse_utc(row.get("recorded_utc")) or _parse_utc(record.get("recorded_utc"))
    handed = _parse_utc(handover_utc)
    out: Dict[str, Any] = {
        "gate_clean_utc": gate_clean.isoformat() if gate_clean else None,
        "gate_clean_source": ("manifest_row.recorded_utc" if row.get("recorded_utc")
                              else "record.recorded_utc"),
        "handover_utc": handed.isoformat() if handed else None,
        "gap_minutes": None,
        "build_elapsed_s": (brief or {}).get("elapsed_s"),
        "minutes_to_deadline_at_build": _clean(_dig(brief or {}, "slate_clock.minutes_to_deadline")),
        "first_lock_utc": _clean(_dig(brief or {}, "slate_clock.first_lock_utc")),
    }
    if gate_clean and handed:
        out["gap_minutes"] = round((handed - gate_clean).total_seconds() / 60.0, 1)
    else:
        out["note"] = ("no artifact stamps the hand-over; pass --handover-utc "
                       "(read it with `TZ=UTC date -Is`) to get the gap")
    return out


def _clean(value: Any) -> Any:
    return None if isinstance(value, _Missing) else value


def degraded_inputs(record: Mapping[str, Any],
                    brief: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every input the build itself reported as degraded, absent, or unapplied.

    Read off the artifacts, never inferred. `enrichment.degraded` plus its
    reason is the build's own self-report; `requested_but_unapplied` is the
    stronger one, because it names something the operator ASKED for that did
    not land. A factor whose count is zero is reported too and labelled for
    what it is -- CLAUDE.md's own reading is that a zero is a fact about the
    slate rather than a gap in the build, so it is listed and not flagged.
    """
    out: List[Dict[str, Any]] = []
    egress = str(record.get("egress") or "").strip()
    if egress:
        out.append({"source": "record.egress", "what": egress})
    else:
        out.append({"source": "record.egress",
                    "what": "not recorded by this delivery; no caller of "
                            "record_delivery passes egress= today, so the "
                            "session-start line is the only measurement"})
    if brief is None:
        out.append({"source": "brief", "what": "the brief is not on disk; every "
                                               "degraded-input fact below it is unavailable"})
        return out
    enrich = brief.get("enrichment")
    if not isinstance(enrich, Mapping):
        out.append({"source": "brief.enrichment",
                    "what": "this brief carries no enrichment block at all"})
    else:
        if enrich.get("degraded"):
            out.append({"source": "brief.enrichment.degraded",
                        "what": str(enrich.get("degraded_reason") or "degraded, no reason recorded")})
        unapplied = enrich.get("requested_but_unapplied")
        if unapplied:
            out.append({"source": "brief.enrichment.requested_but_unapplied",
                        "what": json.dumps(unapplied, default=str)})
        if enrich.get("signal_applied") is False:
            out.append({"source": "brief.enrichment.signal_applied",
                        "what": "false: this build ranked on the proxy projection alone"})
        counts = enrich.get("counts")
        if isinstance(counts, Mapping):
            zeros = sorted(k for k, v in counts.items() if v == 0)
            if zeros:
                out.append({"source": "brief.enrichment.counts",
                            "what": "moved nothing on this slate: " + ", ".join(zeros)})
        unresolved = enrich.get("f5_retractable_unresolved")
        if unresolved:
            out.append({"source": "brief.enrichment.f5_retractable_unresolved",
                        "what": json.dumps(unresolved, default=str)})
    feed = brief.get("lineups_feed")
    if isinstance(feed, Mapping):
        for key in ("status", "warning", "staged_feed_unreadable", "note"):
            if feed.get(key):
                out.append({"source": f"brief.lineups_feed.{key}",
                            "what": json.dumps(feed[key], default=str)})
        if feed.get("age_minutes"):
            out.append({"source": "brief.lineups_feed.age_minutes",
                        "what": f"the feed was {feed['age_minutes']} minute(s) old"})
    inert = brief.get("factors_inert")
    if inert:
        out.append({"source": "brief.factors_inert", "what": json.dumps(inert, default=str)})
    return out


def hand_passed_numbers(record: Mapping[str, Any],
                        brief: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Numbers this build ran on that came from an argument rather than a default.

    Only the artifacts that DISTINGUISH the two are read. `anti_correlation`
    carries `requested: null` when the flag was not passed (R288), and
    `controls_override_applied` is the override string itself, so both say
    outright whether a human chose the value. A control whose artifact does not
    separate "passed" from "defaulted" is not guessed at here; it is listed as
    in-force with its source named as the artifact.
    """
    out: List[Dict[str, Any]] = []
    controls = record.get("controls") or {}
    if controls:
        for key in sorted(controls):
            out.append({"control": key, "value": controls[key], "source": "record.controls"})
    else:
        out.append({"control": "(none)", "value": None,
                    "source": "record.controls is empty; no caller of "
                              "record_delivery passes controls= today, so the "
                              "brief below is the only record of them"})
    strategy = (record.get("manifest_row") or {}).get("strategy_state") or {}
    if strategy:
        out.append({"control": "strategy_state", "value": json.dumps(strategy, default=str),
                    "source": "record.manifest_row.strategy_state (the counted relaxations)"})
    if brief is None:
        return out
    override = brief.get("controls_override_applied")
    if override:
        out.append({"control": "--controls-override", "value": override,
                    "source": "brief.controls_override_applied (passed by hand)"})
    anti = brief.get("anti_correlation")
    if isinstance(anti, Mapping):
        requested = anti.get("requested")
        out.append({
            "control": "--max-opposing-hitters-per-sp",
            "value": anti.get("applied"),
            "source": ("brief.anti_correlation.requested (passed by hand)"
                       if requested is not None
                       else "brief.anti_correlation.applied (engine default; the "
                            "flag was not passed)"),
        })
    deadline = brief.get("deadline")
    if isinstance(deadline, Mapping) and deadline.get("walked"):
        out.append({"control": "deadline ladder", "value": json.dumps(deadline.get("walked"), default=str),
                    "source": "brief.deadline (a rung opened controls this build "
                              "would otherwise have refused under)"})
    exposure = brief.get("exposure")
    if isinstance(exposure, Mapping):
        for key in sorted(exposure):
            value = exposure[key]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out.append({"control": f"exposure.{key}", "value": value,
                            "source": "brief.exposure (in force; the artifact does "
                                      "not separate passed from defaulted)"})
    return out


def documented_exit_codes() -> "tuple[Dict[int, str], str]":
    """``build_slate.REFUSAL_EXIT_NOTES``, read out of the SOURCE.

    Two reasons this is an `ast` read rather than an import. It is CODE, so it
    is read from this file's own repo and never from `--root`, which is the
    artifact tree a test or an isolated run points elsewhere -- the same split
    `delivery_record` draws between `_artifact_root` and `_code_root`. And
    importing `build_slate` pulls the whole engine in to read one dict, in a
    tool whose entire job is to print facts quickly after a hand-over.

    Returns ``(table, note)``. A table that cannot be read is an empty one plus
    a sentence saying so, because "this exit is undocumented" and "the list of
    documented exits could not be found" are different claims and only one of
    them is about the build.
    """
    source = (REPO / "skills" / "generate-lineups" / "scripts" / "build_slate.py")
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return {}, (f"the documented exit codes could not be read from "
                    f"{source.name} ({type(exc).__name__}); this says nothing "
                    f"about the exit above")
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "REFUSAL_EXIT_NOTES" not in names:
            continue
        try:
            table = ast.literal_eval(node.value)
        except ValueError:
            break
        if isinstance(table, Mapping):
            return {int(k): str(v) for k, v in table.items()}, ""
    return {}, (f"REFUSAL_EXIT_NOTES is not a literal dict in {source.name} any "
                f"more; this says nothing about the exit above")


def contract_failures(record: Mapping[str, Any], brief: Optional[Mapping[str, Any]],
                      root: Path) -> List[Dict[str, Any]]:
    """Tools that did not fail the way their contract says they should.

    Two sources. A REFUSAL record (R369) carries an exit code, and an exit code
    with no documented meaning is a contract failure by definition -- R364 is
    exactly that sighting, `solver_probe` exiting 1 with a traceback where the
    R296 contract says 4. And the brief's own verification block lists the
    checks that did not pass, which is the build reporting on itself.
    """
    out: List[Dict[str, Any]] = []
    documented, table_note = documented_exit_codes()
    try:
        from mlb_engine.entries.delivery_record import read_records
        for other in read_records(root=root, date=str(record.get("date") or "")):
            if other.get("kind") != "refusal":
                continue
            code = other.get("exit_code")
            note = documented.get(int(code)) if isinstance(code, int) else None
            out.append({
                "source": str(other.get("_path") or "refusal record"),
                "what": f"exit {code}",
                "contract": note or (table_note or
                                     "this exit code is in no documented set; "
                                     "a tool that exits it is failing its contract"),
                "undocumented": note is None,
            })
    except Exception as exc:  # noqa: BLE001
        out.append({"source": "delivery records", "what": f"not read ({type(exc).__name__}: {exc})",
                    "contract": "", "undocumented": False})
    if brief is None:
        return out
    checks = brief.get("verification")
    if isinstance(checks, Mapping):
        for key, value in sorted(checks.items()):
            if value is False:
                out.append({"source": f"brief.verification.{key}", "what": "did not pass",
                            "contract": "", "undocumented": False})
    elif isinstance(checks, (list, tuple)):
        for item in checks:
            if isinstance(item, Mapping) and item.get("passed") is False:
                out.append({"source": f"brief.verification.{item.get('name') or item.get('check') or '?'}",
                            "what": str(item.get("detail") or "did not pass"),
                            "contract": "", "undocumented": False})
    gates = brief.get("gates")
    if isinstance(gates, Mapping):
        for key, value in sorted(gates.items()):
            if value is False:
                out.append({"source": f"brief.gates.{key}", "what": "false",
                            "contract": "", "undocumented": False})
    return out


def skill_brief_keys(skill_text: str) -> List[str]:
    """Every brief key `SKILL.md` names, read out of the document.

    Two constructions, because the document uses two. The general one is a
    backticked dotted path whose root is a real brief key; the filename filter
    is there because `lineups_feed.json` matches that shape and is a file.

    The second is the enrichment self-report sentence, which lists its keys as
    bare backticked names after a colon. That sentence is the R363 sighting
    itself -- it states `signal_applied`, `requested_but_unapplied`, `degraded`,
    `degraded_reason`, `f1_league_mean_implied_total` and `f1_odds` with no
    contest-type condition, and a Showdown brief has no enrichment block to
    carry any of them -- so a scan that missed it would miss the one case this
    detector was built for.
    """
    keys: set = set()
    for token in re.findall(r"`([a-z_]+(?:\.[a-z0-9_]+)+)`", skill_text):
        root = token.split(".")[0]
        if root not in BRIEF_ROOTS:
            continue
        if token.rsplit(".", 1)[-1] in _FILE_SUFFIXES:
            continue
        keys.add(token)
    for match in re.finditer(r"([a-z_]+) self-report:((?:[^.]|\.\S)*)", skill_text):
        root = match.group(1)
        if root not in BRIEF_ROOTS:
            continue
        for name in re.findall(r"`([a-z0-9_]+)`", match.group(2)):
            keys.add(f"{root}.{name}")
    return sorted(keys)


def absent_brief_keys(brief: Optional[Mapping[str, Any]], skill_text: str,
                      contest_type: str) -> Dict[str, Any]:
    """The R363 detector: keys SKILL.md names that THIS brief does not carry.

    Absence is all this reports. Whether a given absence is a docs defect or a
    correct conditional is the judgment half and it is not decided here -- the
    sighting R363 records is a Showdown brief with no `enrichment` block while
    SKILL.md states that self-report flatly, and telling that apart from a key
    the document conditions on Classic needs a reader.
    """
    if brief is None:
        return {"contest_type": contest_type, "checked": 0, "absent": [],
                "note": "the brief is not on disk, so no key could be checked"}
    named = skill_brief_keys(skill_text)
    absent = [key for key in named if isinstance(_dig(brief, key), _Missing)]
    return {"contest_type": contest_type, "checked": len(named), "absent": absent,
            "note": ("SKILL.md names these keys and this brief does not carry them; "
                     "whether each is a docs defect or a correct conditional is a "
                     "judgment the skill step makes, not this tool")}


AGENT_RUNS = "data/agent_runs"


def agent_runs(root: Path, date: str) -> Dict[str, Any]:
    """What the repo agents cost and found on this date (R372).

    `.claude/hooks/subagent_record.py` appends one line per `dfs-qa` or
    `dfs-premise` run to `data/agent_runs/<date>/<session_id>.jsonl`. Before it,
    the only record a run left was scrollback, and R344's first agentic pass had
    its cost reconstructed by hand afterwards.

    COST HERE IS WALL TIME AND FINDINGS, NEVER TOKENS. The SubagentStop payload
    carries no token count, so there is no honest token figure to print and this
    prints none. `findings: null` means the agent omitted the `FINDINGS: <n>`
    line its definition requires; it is never read as zero, because "found
    nothing" and "did not say" are different facts and only one of them is good
    news.

    The directory is keyed by the UTC date the AGENT ran, which is not always the
    slate date -- a late slate crosses UTC midnight. A date with no directory is
    reported as such rather than as an empty list.
    """
    base = root / AGENT_RUNS / str(date)
    if not base.is_dir():
        return {"runs": [], "note": (f"no {AGENT_RUNS}/{date}/ -- either no repo "
                                     f"agent ran on this UTC date, or the run "
                                     f"crossed UTC midnight and sits under the "
                                     f"adjacent date")}
    runs: List[Dict[str, Any]] = []
    for path in sorted(base.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                runs.append(row)
    runs.sort(key=lambda r: str(r.get("recorded_utc") or ""))
    return {"runs": runs, "note": ""}


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------

def retro(record: Mapping[str, Any], root: Path, brief_path: Optional[Path] = None,
          handover_utc: str = "") -> Dict[str, Any]:
    row = record.get("manifest_row") or {}
    date = str(record.get("date") or "")
    tag = str(row.get("slate_tag") or "")
    path = brief_path if brief_path is not None else find_brief(root, date, tag)
    brief: Optional[Dict[str, Any]] = None
    brief_note = ""
    if path is not None and Path(path).is_file():
        try:
            brief = json.loads(Path(path).read_text(encoding="utf-8"))
            brief_note = str(Path(path))
        except (OSError, ValueError) as exc:
            brief_note = f"{path} is unreadable ({exc})"
    else:
        brief_note = (f"no build_brief under outputs/{date}/; `outputs/` is "
                      f"gitignored and a cloud container is reclaimed at session "
                      f"end, so run this in the session that built the slate, or "
                      f"pass --brief")
    try:
        skill_text = (root / SKILL_MD).read_text(encoding="utf-8")
    except OSError:
        skill_text = ""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "retro_facts",
        "date": date,
        "slate_tag": tag,
        "contest_type": str(row.get("contest_type") or ""),
        "record_path": str(record.get("_path") or ""),
        "delivered_sha256": row.get("sha256"),
        "brief": brief_note,
        "clock": clock(record, brief, handover_utc),
        "degraded_inputs": degraded_inputs(record, brief),
        "hand_passed_numbers": hand_passed_numbers(record, brief),
        "contract_failures": contract_failures(record, brief, root),
        "absent_brief_keys": absent_brief_keys(brief, skill_text,
                                               str(row.get("contest_type") or "")),
        "agent_runs": agent_runs(root, date),
        "labels": ("facts extracted from this build's artifacts; the judgment "
                   "and the filing stay a skill step (references/retro.md)"),
    }


def render(facts: Mapping[str, Any]) -> str:
    out: List[str] = []
    out.append(f"# Retro facts -- {facts.get('date')} "
               f"{facts.get('slate_tag') or 'untagged'} "
               f"({facts.get('contest_type') or 'classic'})")
    out.append(f"record: {facts.get('record_path') or 'unknown'}")
    out.append(f"brief:  {facts.get('brief')}")
    out.append("")

    block = facts.get("clock") or {}
    out.append("## The clock")
    out.append(f"  gate-clean: {block.get('gate_clean_utc') or 'unrecorded'} "
               f"({block.get('gate_clean_source')})")
    out.append(f"  hand-over:  {block.get('handover_utc') or 'not stamped by any artifact'}")
    gap = block.get("gap_minutes")
    out.append(f"  gap:        {gap if gap is not None else 'not computable'}"
               f"{' minute(s)' if gap is not None else ''}")
    if block.get("note"):
        out.append(f"  {block['note']}")
    out.append(f"  build wall time: {block.get('build_elapsed_s')} s; "
               f"minutes to first lock at build: "
               f"{block.get('minutes_to_deadline_at_build')}")
    out.append("")

    out.append("## Degraded inputs")
    rows = facts.get("degraded_inputs") or []
    if not rows:
        out.append("  none reported by the artifacts")
    for item in rows:
        out.append(f"  {item['source']}: {item['what']}")
    out.append("")

    out.append("## Numbers this build ran on")
    rows = facts.get("hand_passed_numbers") or []
    if not rows:
        out.append("  none recorded")
    for item in rows:
        out.append(f"  {item['control']} = {item['value']}")
        out.append(f"    {item['source']}")
    out.append("")

    out.append("## Tools against their contracts")
    rows = facts.get("contract_failures") or []
    if not rows:
        out.append("  no refusal record for this date and no failed check in the brief")
    for item in rows:
        mark = "UNDOCUMENTED EXIT" if item.get("undocumented") else "recorded"
        out.append(f"  [{mark}] {item['source']}: {item['what']}")
        if item.get("contract"):
            out.append(f"    contract: {item['contract']}")
    out.append("")

    block = facts.get("absent_brief_keys") or {}
    out.append("## Brief keys SKILL.md names that this brief does not carry (R363)")
    out.append(f"  contest type {block.get('contest_type') or 'unknown'}; "
               f"{block.get('checked')} key(s) checked")
    if not block.get("absent"):
        out.append("  none absent")
    for key in block.get("absent") or []:
        out.append(f"  absent: {key}")
    out.append(f"  {block.get('note')}")
    out.append("")

    block = facts.get("agent_runs") or {}
    out.append("## Repo agent runs (R372)")
    rows = block.get("runs") or []
    if not rows:
        out.append(f"  {block.get('note') or 'none recorded'}")
    for item in rows:
        found = item.get("findings")
        found = "not stated (the agent omitted its FINDINGS line)" if found is None else found
        secs = item.get("duration_s")
        out.append(f"  {item.get('agent_type') or 'unknown agent'}: "
                   f"{secs if secs is not None else '?'} s, findings {found}")
        out.append(f"    model {item.get('model') or 'unrecorded'}; "
                   f"stop {item.get('stop_reason') or '?'}; "
                   f"duration from {item.get('duration_source') or '?'}")
    if rows:
        out.append("  cost here is wall time and findings per run; the hook "
                   "payload carries no token count")
    out.append("")
    out.append(facts.get("labels") or "")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", nargs="*", help="delivery record JSON path(s)")
    ap.add_argument("--date", help="every delivery record for this slate date")
    ap.add_argument("--root", default=str(REPO), help="repo root")
    ap.add_argument("--brief", help="brief JSON to read instead of resolving one")
    ap.add_argument("--handover-utc", default="",
                    help="when Ben got the file, ISO-8601 UTC; the one fact no "
                         "artifact carries (read it with `TZ=UTC date -Is`)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    root = Path(args.root).resolve()
    if not args.record and not args.date:
        ap.error("pass a record path or --date")

    records: List[Dict[str, Any]] = []
    try:
        if args.record:
            for raw in args.record:
                path = Path(raw)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["_path"] = (str(path.relative_to(root))
                                    if path.is_relative_to(root) else str(path))
                records.append(payload)
        else:
            from mlb_engine.entries.delivery_record import read_records
            records = [r for r in read_records(root=root, date=args.date)
                       if r.get("kind") == "delivery"]
    except (OSError, ValueError) as exc:
        print(f"ERROR  could not read the delivery record(s): {exc}", file=sys.stderr)
        return 3
    if not records:
        print(f"no delivery record for {args.date or 'the given path(s)'}; a build "
              f"records itself (R369), and a refusal records itself too.")
        return 0
    for record in records:
        facts = retro(record, root,
                      Path(args.brief) if args.brief else None,
                      args.handover_utc)
        print(json.dumps(facts, indent=1, sort_keys=True, default=str)
              if args.json else render(facts))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
