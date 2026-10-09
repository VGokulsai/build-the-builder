"""A stand-in for a hung `claude`: starts a child that keeps our stdout open, then hangs.
Used by test_builder.py to check a timed-out call really returns on time on Windows."""
import subprocess
import sys
import time

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        time.sleep(60)
    else:
        subprocess.Popen([sys.executable, __file__, "child"])   # inherits our stdout, like a helper process
        time.sleep(60)
