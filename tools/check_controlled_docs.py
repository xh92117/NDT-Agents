"""Run deterministic repository checks for the four controlled ASCII documents."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLED = ["AGENTS.md", "development-spec.md", "plan.md", "test.md"]
VERSION_PATTERN = re.compile(
    r"\*\*(?:Specification version|Plan version|Version):\*\*\s+([0-9]+\.[0-9]+)"
)
LINK_PATTERN = re.compile(r"\[[^]]+\]\(([^)]+)\)")
GATE_PATTERN = re.compile(r"^\| `?(TG-[0-9]{2})`? \|", re.MULTILINE)


def check_file(path: Path) -> tuple[str, set[str]]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path.name}: UTF-8 BOM is forbidden")
    if any(byte > 127 for byte in raw):
        raise ValueError(f"{path.name}: controlled documents must be ASCII-only")
    text = raw.decode("ascii")
    if len(re.findall(r"^```", text, re.MULTILINE)) % 2:
        raise ValueError(f"{path.name}: unbalanced fenced code block")
    version_match = VERSION_PATTERN.search(text)
    if not version_match:
        raise ValueError(f"{path.name}: version header not found")
    for target in LINK_PATTERN.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        relative = target.split("#", maxsplit=1)[0]
        if relative and not (path.parent / relative).resolve().exists():
            raise ValueError(f"{path.name}: broken local link {target}")
    return version_match.group(1), set(GATE_PATTERN.findall(text))


def main() -> None:
    results = {name: check_file(ROOT / name) for name in CONTROLLED}
    versions = {result[0] for result in results.values()}
    if len(versions) != 1:
        raise ValueError(f"controlled document versions differ: {sorted(versions)}")
    plan_gates = results["plan.md"][1]
    test_gates = results["test.md"][1]
    expected = {f"TG-{index:02d}" for index in range(7)}
    if plan_gates != expected or test_gates != expected:
        raise ValueError(
            f"gate mapping mismatch: plan={sorted(plan_gates)}, test={sorted(test_gates)}"
        )
    print(
        "DOC=PASS "
        f"version={versions.pop()} files={len(CONTROLLED)} gates={len(expected)} ascii=true"
    )


if __name__ == "__main__":
    main()
