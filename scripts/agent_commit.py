#!/usr/bin/env python3

import os
import subprocess
import sys


def git_config(key: str) -> str:
    result = subprocess.run(
        ["git", "config", "--get", key],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


def main() -> int:
    agent_name = os.environ.get("AGENT_GIT_NAME", "").strip()
    agent_email = os.environ.get("AGENT_GIT_EMAIL", "").strip()

    if not agent_name:
        print("Missing AGENT_GIT_NAME.", file=sys.stderr)
        return 1

    if not agent_email:
        print("Missing AGENT_GIT_EMAIL.", file=sys.stderr)
        return 1

    reviewer_name = git_config("user.name")
    reviewer_email = git_config("user.email")

    if not reviewer_name:
        print("Missing git config user.name.", file=sys.stderr)
        return 1

    if not reviewer_email:
        print("Missing git config user.email.", file=sys.stderr)
        return 1

    env = os.environ.copy()

    # Override identity for this Git invocation only.
    env["GIT_AUTHOR_NAME"] = agent_name
    env["GIT_AUTHOR_EMAIL"] = agent_email
    env["GIT_COMMITTER_NAME"] = agent_name
    env["GIT_COMMITTER_EMAIL"] = agent_email

    reviewer = f"{reviewer_name} <{reviewer_email}>"

    command = [
        "git",
        "commit",
        "--trailer",
        f"Human-Reviewer: {reviewer}",
        *sys.argv[1:],
    ]

    try:
        result = subprocess.run(command, env=env)
    except FileNotFoundError:
        print(
            "Unable to find Git. Ensure 'git' is available on PATH.",
            file=sys.stderr,
        )
        return 1

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())