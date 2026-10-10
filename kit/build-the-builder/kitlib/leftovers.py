"""Find content of the public Briefs A and B left in an agent built for another brief.

    python3 kitlib/leftovers.py out/<slot>/agent.py <brief file> [<brief file> ...]

The builder starts from agents/ref_ab.py, which was written from the public briefs in briefs/.
Any value (date, time, deadline, band) or sentence of those briefs that is in the built agent but
not in its own brief is probably a leftover: replace it with the new brief's rule, or delete it.
Building for Brief A or B itself finds nothing, by design. Exit code 1 when there are hits.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PATTERNS = [
    r"\d{4}-\d{2}-\d{2}",                         # dates
    r"\b\d{1,2}:\d{2}\b",                         # times
    r"\b\d+(?:st|nd|rd|th) business day",         # deadlines in words
    r"\b\d+\s*(?:to|-)\s*\d+\s*days",             # bands
]


def norm(s):
    return " ".join(s.lower().replace("’", "'").split())


def hits(agent_src, old_briefs, brief_text):
    """Values and sentences of the public briefs that are in the agent but not in its own brief."""
    b, a, old = norm(brief_text), norm(agent_src), norm(old_briefs)
    out = []
    for pat in PATTERNS:
        for m in sorted(set(re.findall(pat, agent_src))):
            if norm(m) in old and norm(m) not in b:
                out.append(m)
    # exact wording the public briefs require ("You will receive a text message ..."): a new brief
    # usually words its own, so the old one must not survive
    for q in sorted(set(re.findall(r'"([^"\n]{12,200})"', old_briefs))):
        core = norm(q).strip(".?!' ")
        if len(core.split()) >= 4 and core in a and core not in b:
            out.append(q)
    return out


def main():
    agent = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
    old = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "briefs").glob("*.md")))
    brief = "\n".join(pathlib.Path(p).read_text(encoding="utf-8") for p in sys.argv[2:])
    found = hits(agent, old, brief)
    for v in found:
        print("LEFTOVER?", v)
    print("%d possible leftovers" % len(found))
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
