"""Start one interactive Codex session using the repository's MNQ role."""
import argparse
import os
import shutil
from pathlib import Path


def command(role, question, root):
    instructions = (root / ".github" / "agents" / f"mnq-{role}.agent.md").read_text()
    sandbox = "read-only" if role == "reviewer" else "workspace-write"
    return ["codex", "--cd", str(root), "--sandbox", sandbox,
            instructions + "\n\nOperator request\n" + question]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["researcher", "reviewer"])
    parser.add_argument("question")
    args = parser.parse_args()
    if not shutil.which("codex"):
        parser.error("Install and authenticate Codex CLI, or use the GitHub agent profiles.")
    os.execvp("codex", command(args.role, args.question, Path(__file__).resolve().parent))
