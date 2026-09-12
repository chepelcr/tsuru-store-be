"""The Lambda image is python:3.9 — keep runtime-evaluated annotations 3.9-safe.

`Optional[str | int]` in `branch_sync_dto.py` took the whole service down in
dev on 2026-09-12. `from __future__ import annotations` defers annotations to
strings, and pydantic evaluates them at runtime, where PEP 604 unions do not
exist on 3.9:

    TypeError: Unable to evaluate type annotation 'Optional[str | int]'

Because `app/main.py` imports the SQS handler at module scope, the failure was
not limited to branch discovery — every invocation, including the HTTP API,
returned Runtime.Unknown. This test is cheap insurance against a `X | Y` slipping
back into a pydantic model.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "app"
DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"

# Files whose annotations pydantic (or SQLAlchemy) evaluates at runtime.
RUNTIME_EVALUATED = sorted(
    p for p in (APP / "dtos").rglob("*.py")
) + sorted(APP.glob("models/*.py"))


def test_dockerfile_still_pins_a_version_without_pep604() -> None:
    """If the image moves to 3.10+, this whole guard can go."""
    base = DOCKERFILE.read_text(encoding="utf-8").splitlines()[0]
    assert "python:3.9" in base, (
        f"Dockerfile base changed to {base!r}. PEP 604 unions are legal from "
        "3.10 — delete this module rather than working around it."
    )


@pytest.mark.parametrize("path", RUNTIME_EVALUATED, ids=lambda p: p.name)
def test_no_pep604_unions_in_runtime_evaluated_annotations(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            for sub in ast.walk(node.annotation):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    offenders.append(
                        f"{path.name}:{node.lineno} {ast.unparse(node.annotation)}"
                    )
    assert not offenders, (
        "PEP 604 union in a runtime-evaluated annotation; use typing.Optional / "
        "typing.Union on python 3.9:\n  " + "\n  ".join(offenders)
    )
