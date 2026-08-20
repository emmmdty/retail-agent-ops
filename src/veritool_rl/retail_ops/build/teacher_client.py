"""Backward-compat re-export. The real module lives in ``core.build.teacher_client``.

2026-08-20 lifted to core so a second domain (flight_ops) can reuse the teacher
transport without depending on retail_ops. This shim preserves all existing
retail_ops imports — no caller needs to change.
"""

from veritool_rl.core.build.teacher_client import *  # noqa: F403
