"""Wrapper for running ue_path_c_smoke.py in an already-open UE Editor.

The remote_execution bridge executes one script file and does not forward
additional argv. This wrapper supplies the argv needed for the GUI/editor
actor-spawn smoke path.
"""

from __future__ import annotations

import runpy
import sys


sys.argv = [
    "ue_path_c_smoke.py",
    "--spawn-actor=1",
    "--output-json=C:/temp/ue-remote/path_c_smoke_spawn_actor.json",
]

runpy.run_path("C:/temp/ue-remote/ue_path_c_smoke.py", run_name="__main__")
