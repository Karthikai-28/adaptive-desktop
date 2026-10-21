"""Mission verdicts: a mission succeeds only when its report proves every acceptance criterion.

The mission brief numbers the criteria C1..Cn and asks for one line per criterion in the final report,
`C2: PASS - <evidence>` or `C2: FAIL - <reason>`. Markdown decoration (bullets, bold, table pipes,
checkboxes) is tolerated. A later report overrides an earlier one, so a retried or follow-up task can
settle a criterion. A PASS without evidence does not count.
"""
import re

LINE = re.compile(r"^\s*(?:[-+*•]\s*)?(?:\[[ xX]\]\s*)?C(\d{1,2})\b\s*[:.)\]=-]*\s*(PASS|FAIL)\b\s*[:.,;=\-–—]*\s*(.*)$",
                  re.I)
MIN_EVIDENCE = 3


def parse(text):
    """{criterion number: (verdict, evidence)} from one report; the last line for a number wins."""
    out = {}
    for raw in (text or "").splitlines():
        line = re.sub(r"[*_`|]", " ", raw)
        m = LINE.match(line)
        if m:
            out[int(m.group(1))] = (m.group(2).upper(), " ".join(m.group(3).split())[:500])
    return out


def judge(criteria, reports):
    found = {}
    for text in reports:
        found.update(parse(text))
    rows = []
    for i, criterion in enumerate(criteria, 1):
        verdict, evidence = found.get(i, ("MISSING", ""))
        if verdict == "PASS" and len(evidence) < MIN_EVIDENCE:
            verdict = "MISSING"
        rows.append({"id": f"C{i}", "criterion": criterion, "verdict": verdict, "evidence": evidence})
    return rows


def outcome(rows):
    """(mission status, error) for finished work judged by judge()."""
    failed = [r["id"] for r in rows if r["verdict"] == "FAIL"]
    missing = [r["id"] for r in rows if r["verdict"] == "MISSING"]
    if failed:
        return "failed", "criteria failed: " + ", ".join(failed) + \
            (f"; no PASS/FAIL evidence for {', '.join(missing)}" if missing else "")
    if missing:
        return "unverified", "the report gives no PASS/FAIL evidence for " + ", ".join(missing)
    return "succeeded", ""
