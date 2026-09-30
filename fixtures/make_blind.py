"""Make label-stripped copies of the fixtures for accuracy runs.

The fixtures label their own defects (`# R1: ...`, `NOT-A-FINDING`), so an auditor
that reads them is being shown the answers. This writes copies with every comment
and every module docstring removed, line numbers unchanged, under neutral file
names, into a directory OUTSIDE the repo (so the auditor can't read EXPECTED.md).

Usage:
    python make_blind.py <output-dir>
"""

import ast
import io
import shutil
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent

# source file -> blind name (neutral: no "bad_" prefix)
FILES = {
    "py-sdk1/bad_server.py": "py-sdk1/server.py",
    "py-sdk1/requirements.txt": "py-sdk1/requirements.txt",
    "py-sdk2/bad_server.py": "py-sdk2/server.py",
    "py-sdk2/lowlevel_server.py": "py-sdk2/lowlevel_server.py",
    "py-sdk2/requirements.txt": "py-sdk2/requirements.txt",
}


def strip_labels(src: str) -> str:
    lines = src.splitlines(keepends=True)
    comment_col = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            comment_col[tok.start[0]] = tok.start[1]
    out = []
    for lineno, line in enumerate(lines, 1):
        if lineno in comment_col:
            kept = line[: comment_col[lineno]].rstrip()
            out.append(kept + "\n" if kept else "\n")
        else:
            out.append(line)
    src = "".join(out)

    tree = ast.parse(src)
    first = tree.body[0] if tree.body else None
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        lines = src.splitlines(keepends=True)
        span = first.end_lineno - first.lineno + 1
        lines[first.lineno - 1 : first.end_lineno] = ['"""MCP server."""\n'] + ["\n"] * (span - 1)
        src = "".join(lines)
    return src


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    out_root = Path(sys.argv[1]).resolve()
    if HERE.parent in out_root.parents or out_root == HERE.parent:
        print("refusing: output must be outside the repo, or the auditor can read EXPECTED.md")
        return 2
    for src_rel, dst_rel in FILES.items():
        src, dst = HERE / src_rel, out_root / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".py":
            text = strip_labels(src.read_text(encoding="utf-8"))
            # server names like "fixture-bad-sdk1" would hint that defects are planted
            text = text.replace("fixture-bad-", "notes-").replace("fixture-lowlevel-", "inventory-")
            ast.parse(text)  # still valid Python
            dst.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(src, dst)
        print(f"{src_rel} -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
