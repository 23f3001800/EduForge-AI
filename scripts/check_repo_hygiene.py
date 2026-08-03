"""Fail the build if generated files or secrets get committed.

Both have happened. The Next.js migration swept `frontend/.next/` into a commit —
about 150MB of webpack packs, plus a `server-reference-manifest.json` carrying a
rotating `encryptionKey` that produced a one-line diff on every single build.
Neither belongs in history, and neither was caught by review because a 158-file
commit is not read line by line.

So this is a gate rather than a lesson. `make check` runs it, and a commit that
reintroduces either fails before it reaches a remote.

Secret detection is deliberately narrow: real provider key prefixes with enough
following entropy to not be a placeholder. A scanner that flags every string
containing "key" gets muted within a week, and a muted scanner is worse than
none.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Directories whose contents are produced by a build, never authored.
GENERATED = (
    "frontend/.next/",
    "frontend/dist/",
    "frontend/out/",
    "node_modules/",
    ".venv/",
    "__pycache__/",
)

#: Real key shapes. Each needs enough trailing entropy that an obvious
#: placeholder ("sk-ant-looks-real", "sk-or-...") does not match.
SECRET_PATTERNS = {
    "OpenRouter": re.compile(r"sk-or-v1-[A-Za-z0-9]{32,}"),
    "OpenAI": re.compile(r"sk-proj-[A-Za-z0-9_-]{32,}"),
    "Anthropic": re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_-]{32,}"),
    # Kept even though the Groq provider itself was removed: this scans committed
    # *files*, not the configured provider list, and a leaked `gsk_...` key is a
    # leaked key regardless of whether this codebase still calls Groq. An operator
    # env can still hold one (e.g. from before the provider was dropped), and a
    # secret scanner's job is to catch shapes that leak, not the ones we endorse.
    "Groq": re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    "Google": re.compile(r"AIza[A-Za-z0-9_-]{35}"),
    "AWS": re.compile(r"AKIA[A-Z0-9]{16}"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}

#: Binary and large-asset suffixes worth skipping — scanning a PDF for key
#: shapes is slow and only ever produces false positives.
SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".ttf", ".otf", ".woff", ".woff2", ".ico", ".docx", ".pptx"}


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [line for line in result.stdout.splitlines() if line]


def main() -> int:
    files = tracked_files()
    problems: list[str] = []

    generated = [f for f in files if any(f.startswith(prefix) or f"/{prefix}" in f for prefix in GENERATED)]
    for path in generated:
        problems.append(f"generated file is tracked: {path}")

    for path in files:
        if Path(path).suffix.lower() in SKIP_SUFFIXES:
            continue
        full = ROOT / path
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(text)
            if match:
                # Never print the secret itself — a CI log is another place it
                # would then live.
                problems.append(
                    f"{label} key shape in {path} (line "
                    f"{text[: match.start()].count(chr(10)) + 1})"
                )

    if problems:
        print("Repository hygiene check failed:", file=sys.stderr)
        for problem in sorted(set(problems))[:40]:
            print(f"  {problem}", file=sys.stderr)
        if len(set(problems)) > 40:
            print(f"  ... and {len(set(problems)) - 40} more", file=sys.stderr)
        return 1

    print(f"repo hygiene clean — {len(files)} tracked files, no generated output, no secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
