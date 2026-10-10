"""Stand-ins for a hung `claude`, used by test_builder.py to check timeouts really hold on Windows.

    (no argument)  starts a child that keeps our stdout open, then hangs
    noread         hangs without ever reading stdin, so a large prompt fills the pipe
"""
import subprocess
import sys
import time

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "child":
        time.sleep(60)
    elif mode == "noread":
        time.sleep(60)
    else:
        subprocess.Popen([sys.executable, __file__, "child"])   # inherits our stdout, like a helper process
        time.sleep(60)
