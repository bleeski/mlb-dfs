#!/usr/bin/env python
"""SubagentStop hook: record what a repo agent run cost and found (R372).

WHY. `.claude/agents/dfs-qa.md` and `dfs-premise.md` are invoked by hand, and
the only evidence a run ever happened is scrollback -- the least reliable record
in the room and the first thing to go when the context compacts. R344's first
agentic pass cost ~109k tokens, 4m00s wall and 10 tool calls for one acted-on
finding of five, and every one of those numbers was reconstructed by hand
afterwards. This writes them down instead.

WHAT THE PAYLOAD ACTUALLY CARRIES, which is less than R372 assumed. The
SubagentStop event delivers `agent_id`, `agent_type`, `last_assistant_message`,
`stop_reason`, `session_id` and `transcript_path`. It carries NO model, NO
duration and NO token count. So:

  * agent name      -> `agent_type`, straight from the payload.
  * model           -> read from the subagent's own transcript, which stamps
                       `message.model` on every assistant entry. This is the
                       model that SERVED the run, not the one the agent file
                       declares, and the two can differ on a fallback.
  * duration        -> the span of that transcript's first and last `timestamp`.
                       A floor, not a stopwatch: it measures the transcript, and
                       a run that died before writing an entry has none.
  * findings        -> parsed from the `FINDINGS: <n>` line both agent
                       definitions are required to end with. Absent line ->
                       `null`, never a guess. R372 asked for a token count and
                       the payload has none, so cost here is wall time and
                       findings per run and never a token figure.

WHERE IT WRITES, and why not into the delivery record. R372 names the R369
delivery record as the target. It cannot be: `dfs-qa` runs BEFORE the hand-over,
a DEV session running `dfs-premise` has no delivery at all, and
`data/deliveries/` is not in DEV's write set (`tools/claim.py`). So each session
appends to its OWN file at `data/agent_runs/<date>/<session_id>.jsonl`. One file
per session means two sessions never touch the same file, which is the same
no-conflict shape as the fragment directories -- and `data/agent_runs/` is
registered in `claim.py`'s `FRAGMENT_PREFIXES` for exactly that reason.
`tools/retro.py` reads it.

NEVER RAISES, NEVER BLOCKS. Bookkeeping beside an agent run, on the same
contract `delivery_record` keeps: a line that cannot be written is never the
reason anything fails.

Test by hand:
  echo '{"hook_event_name":"SubagentStop","agent_type":"dfs-qa",
         "last_assistant_message":"FINDINGS: 3","stop_reason":"end_turn"}' \
    | python .claude/hooks/subagent_record.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
AGENT_RUNS = "data/agent_runs"

#: The contract both agent definitions carry. Anchored to a line so a mention of
#: the word inside a report body is not mistaken for the count.
FINDINGS = re.compile(r"^\s*FINDINGS:\s*(\d+)\s*$", re.MULTILINE)


def repo_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    return Path(__file__).resolve().parents[2]


def findings_count(message: str) -> int | None:
    """The LAST `FINDINGS: n` line, or None.

    Last rather than first: the brief and this file both quote the line while
    explaining it, so an agent that echoes its instructions would otherwise
    report the example's number instead of its own.
    """
    hits = FINDINGS.findall(str(message or ""))
    return int(hits[-1]) if hits else None


def transcript_facts(path: str, agent_type: str = "") -> dict:
    """Model and duration, read from the subagent's transcript.

    Both are absent from the payload and present here, so this is the only way
    to get them. Every failure degrades to None with a stated reason rather than
    to a plausible number.
    """
    out: dict = {"model": None, "duration_s": None, "duration_source": None}
    if not path:
        out["duration_source"] = "no transcript_path in payload"
        return out
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        out["duration_source"] = f"transcript unreadable ({type(exc).__name__})"
        return out
    stamps: list[str] = []
    side: list[str] = []
    model = None
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        stamp = entry.get("timestamp")
        if isinstance(stamp, str):
            stamps.append(stamp)
            if entry.get("isSidechain") is True:
                side.append(stamp)
        if model is None and entry.get("type") == "assistant":
            got = (entry.get("message") or {}).get("model")
            if isinstance(got, str):
                model = got
    out["model"] = model
    # Which entries belong to the AGENT, which is not the same question as which
    # entries are in the file. Measured live on 2026-09-19, the first time this
    # hook fired for real: the event arrived with an empty `agent_type` and a
    # `transcript_path` pointing at the PARENT session's transcript, and the
    # naive full-file span recorded 18221.4 s -- five hours of main session,
    # written into the record as though it were an agent's wall time. A wrong
    # number that looks right is worse than no number, which is the whole
    # premise of this file, so:
    #   * sidechain entries present -> measure over those, they are the agent's;
    #   * otherwise trust the full span only when the payload NAMED an agent,
    #     which means the file is that agent's own transcript;
    #   * otherwise refuse and say why.
    if side:
        stamps = side
        out["duration_source"] = "sidechain entries in transcript"
    elif not agent_type:
        out["duration_source"] = ("no agent_type in payload and no sidechain "
                                  "entries in transcript; a full-file span here "
                                  "would measure the PARENT session, not an agent")
        return out
    if len(stamps) >= 2:
        try:
            first = datetime.fromisoformat(stamps[0].replace("Z", "+00:00"))
            last = datetime.fromisoformat(stamps[-1].replace("Z", "+00:00"))
            out["duration_s"] = round((last - first).total_seconds(), 1)
            out["duration_source"] = (out["duration_source"]
                                      or "transcript first-to-last timestamp span")
        except ValueError:
            out["duration_source"] = "transcript timestamps unparseable"
    else:
        out["duration_source"] = "fewer than two timestamped transcript entries"
    return out


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    try:
        now = datetime.now(timezone.utc)
        agent_type = str(payload.get("agent_type") or "")
        facts = transcript_facts(str(payload.get("transcript_path") or ""),
                                 agent_type)
        session = str(payload.get("session_id") or "nosession")
        session = "".join(c if (c.isalnum() or c in "-_") else "_" for c in session)
        record = {
            "schema_version": SCHEMA_VERSION,
            "recorded_utc": now.isoformat(),
            "agent_type": payload.get("agent_type"),
            "agent_id": payload.get("agent_id"),
            "session_id": payload.get("session_id"),
            "stop_reason": payload.get("stop_reason"),
            "findings": findings_count(payload.get("last_assistant_message")),
            "model": facts["model"],
            "duration_s": facts["duration_s"],
            "duration_source": facts["duration_source"],
            "labels": ("wall time and findings per run; the payload carries no "
                       "token count, so no cost figure here is a token figure"),
        }
        base = repo_root() / AGENT_RUNS / now.strftime("%Y-%m-%d")
        base.mkdir(parents=True, exist_ok=True)
        with (base / f"{session}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    except Exception:  # noqa: BLE001 - bookkeeping never fails an agent run
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
