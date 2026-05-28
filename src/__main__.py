import os
import cProfile
import pstats
from . import main as package_main

with open("/opt/genpod/server_debug.log", "w") as f:
    f.write("YES: __main__.py ran!\n")

profiler = cProfile.Profile()

# DEBUG: show we're in __main__.py
print("🚀 Server __main__.py launched")
print("📂 Current working dir:", os.getcwd())

profiler.enable()
try:
    package_main()
except Exception as e:
    print(f"💥 Exception during server execution: {e}")
    raise
finally:
    profiler.disable()
    out_file = os.path.abspath("server.prof")
    profiler.dump_stats(out_file)
    print(f"✅ server.prof saved at: {out_file}")
