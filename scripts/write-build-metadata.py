#!/usr/bin/env python3
"""Freeze the deployed Git identity for display by the running application."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".build-metadata.json"


def git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


commit = os.environ.get("RENDER_GIT_COMMIT", "").strip()
if not commit:
    commit = git_output("rev-parse", "HEAD")

message = os.environ.get("DEPLOYMENT_GIT_MESSAGE", "").strip()
if not message and commit:
    message = git_output("show", "-s", "--format=%s", commit)
if not message:
    message = git_output("log", "-1", "--format=%s")

OUTPUT.write_text(
    json.dumps({"commit": commit, "message": message}, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
