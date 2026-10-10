"""Undo one fix at a time and confirm test_builder.py fails each time: py -3 mutate.py

A test that still passes with its fix removed is checking nothing (CLAUDE.md:
'A passing test proves nothing until you have watched it fail').
"""
import shutil
import subprocess
import sys

MUTANTS = [
    ("builder/llm.py", 'raise Blocked("claude error', 'raise ConnectionError("claude error', "blocked model retried"),
    ("builder/core.py", "    for key in TASK_KEYS:\n", "    for key in ():\n", "only 'description' understood"),
    ("builder/core.py", "    elif isinstance(t.get(\"function\"), dict):\n        t = t[\"function\"]\n",
     "    elif \"function\" in t:\n        t = t[\"function\"]\n", "odd tool shapes crash"),
    ("builder/llm.py", "    if len(system) > 4000:", "    if False:", "long prompt in argv"),
    ("builder/core.py", "            lines.append(\"  \" + t.strip())\n        elif s == \"agent\":",
     "            lines.append(\"  \" + t.strip())\n        elif False:", "backend sees no earlier calls"),
    ("builder/llm.py", "    try:\n        return json.loads(raw)\n    except ValueError:",
     "    try:\n        return json.loads(raw)\n    except KeyError:", "HTML body crashes"),
    ("builder/llm.py", "            if not body[i + end:].strip(\" \\n\\t.`\"):", "            if True:", "fragments of cut-off replies parsed"),
    ("builder/llm.py", [("            subprocess.run([\"taskkill\", \"/F\", \"/T\", \"/PID\", str(p.pid)], capture_output=True)",
                         "            p.kill()"),
                        ("            p.communicate(timeout=5)", "            p.communicate()")],
     None, "hung child process holds a timed-out call"),
    ("builder/core.py", "        if _refused(user):", "        if False:", "a refusing caller is scored"),
    ("builder/core.py", "    score = BREACH_CAP * share if critical_broken else share",
     "    score = 0.0 if critical_broken else share", "breaches give no learning signal"),
    ("run.py", '    task["id"] = str(task.get("id") or os.path.splitext(os.path.basename(a.task))[0])',
     '    task["id"] = str(task.get("id") or "task")', "id-less tasks overwrite each other"),
]


def main():
    survived = []
    for path, old, new, name in MUTANTS:
        pairs = old if isinstance(old, list) else [(old, new)]   # a mutant may change several lines
        src = open(path, encoding="utf-8").read()
        missing = [o for o, _ in pairs if o not in src]
        if missing:
            print("PATTERN MISSING for %r: fix the mutant, it proves nothing" % name)
            survived.append(name)
            continue
        mutated = src
        for o, n in pairs:
            mutated = mutated.replace(o, n, 1)
        shutil.copy(path, path + ".bak")
        try:
            open(path, "w", encoding="utf-8").write(mutated)
            r = subprocess.run([sys.executable, "test_builder.py"], capture_output=True, text=True)
            caught = r.returncode != 0
            print("%-8s %s" % ("caught" if caught else "SURVIVED", name))
            if not caught:
                survived.append(name)
        finally:
            shutil.move(path + ".bak", path)
    print("all mutants caught" if not survived else "survived: %s" % survived)
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
