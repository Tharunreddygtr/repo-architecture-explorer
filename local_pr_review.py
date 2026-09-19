from __future__ import annotations

import argparse
import io
import subprocess
import tempfile
import tarfile
from pathlib import Path

from architecture_explorer import analyze_project, build_pr_review_artifacts
from pr_impact import analyze_pr_impact, render_pr_impact_summary


ROOT = Path(__file__).resolve().parent


def _git_files(commit: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_value(args: list[str]) -> str:
    result = subprocess.run(args, cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _git_diff_status(base: str, head: str) -> list[tuple[str, str]]:
    output = _git_value(["git", "diff", "--name-status", base, head])
    changes = []
    for line in output.splitlines():
        status, _, path = line.partition("\t")
        if path:
            changes.append((status[0], path))
    return changes


def _materialize_commit(commit: str, target: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        tar.extractall(target, filter="data")


def run(base: str, head: str, hld_output: Path | None = None) -> str:
    base_files = _git_files(base)
    head_files = _git_files(head)
    diff_status = _git_diff_status(base, head)
    changed_paths = {path for _, path in diff_status}
    modified_or_added = {path for status, path in diff_status if status in {"A", "M", "R"}}
    impact_base_files = [path for path in base_files if path not in modified_or_added]
    with tempfile.TemporaryDirectory(prefix="repo-architecture-head-") as temp_dir:
        head_root = Path(temp_dir)
        _materialize_commit(head, head_root)
        summary = analyze_project(head_root)
    impact = analyze_pr_impact(impact_base_files, head_files, summary)
    changed_names = [Path(item).name for item in impact["changed_files"]]
    removed_names = [Path(item).name for item in impact["removed_files"]]
    artifacts = build_pr_review_artifacts(summary, changed_names, removed_names)

    if hld_output:
        hld_output.write_text(artifacts["hld_svg"], encoding="utf-8")
        hld_section = [f"![PR HLD diagram]({hld_output.name})"]
    else:
        hld_section = ["```svg", artifacts["hld_svg"], "```"]

    lines = [
        f"# Local Architecture PR Review: {base} -> {head}",
        "",
        f"- Base commit: `{base}`",
        f"- Head commit: `{head}`",
        f"- Base tree files: {len(base_files)}",
        f"- Head tree files: {len(head_files)}",
        f"- Git diff paths: {', '.join(sorted(changed_paths)) or 'none'}",
        f"- Changed files: {', '.join(impact['changed_files']) or 'none'}",
        f"- Removed files: {', '.join(impact['removed_files']) or 'none'}",
        f"- Impact summary: {impact['summary']}",
        "",
        "## HLD Diagram",
        "",
        *hld_section,
        "",
        "## Dependency Impact Diagram",
        "",
        "```mermaid",
        artifacts["impact_mermaid"],
        "```",
        "",
        "## Layer Diagram",
        "",
        "```mermaid",
        artifacts["layer_mermaid"],
        "```",
        "",
        "## Architecture Review",
        "",
        render_pr_impact_summary(impact_base_files, head_files, summary),
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze two local Git commits with Repo Architecture Explorer.")
    parser.add_argument("base", help="Base commit, branch, or tag")
    parser.add_argument("head", help="Head commit, branch, or tag")
    parser.add_argument("--output", type=Path, help="Optional output Markdown path")
    args = parser.parse_args()
    hld_output = args.output.with_suffix(".svg") if args.output else None
    report = run(args.base, args.head, hld_output)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(report)