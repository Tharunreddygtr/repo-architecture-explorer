from __future__ import annotations

import argparse
import html
import io
import subprocess
import tempfile
import tarfile
from pathlib import Path

from architecture_explorer import analyze_project, build_pr_review_artifacts
from pr_impact import analyze_pr_impact, render_pr_impact_summary


ROOT = Path(__file__).resolve().parent


def render_html_report(
        base: str,
        head: str,
        base_files: list[str],
        head_files: list[str],
        changed_paths: set[str],
        impact: dict,
        summary: dict,
        artifacts: dict[str, str],
) -> str:
        title = f"Architecture PR Review: {base} -> {head}"
        escaped_title = html.escape(title)
        escaped_base = html.escape(base)
        escaped_head = html.escape(head)
        changed_files = html.escape(", ".join(impact["changed_files"]) or "none")
        removed_files = html.escape(", ".join(impact["removed_files"]) or "none")
        diff_paths = html.escape(", ".join(sorted(changed_paths)) or "none")
        impact_summary = html.escape(str(impact["summary"]))
        review_summary = html.escape(render_pr_impact_summary(base_files, head_files, summary))

        return f"""<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escaped_title}</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>document.addEventListener('DOMContentLoaded', () => mermaid.initialize({{ startOnLoad: true, securityLevel: 'strict' }}));</script>
    <style>
        :root {{ color-scheme: dark; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }}
        body {{ max-width: 1280px; margin: 0 auto; padding: 32px; }}
        h1 {{ margin-top: 0; }}
        section {{ background: #111827; border: 1px solid #334155; border-radius: 10px; padding: 20px; margin-top: 20px; }}
        .metrics {{ display: flex; gap: 12px; flex-wrap: wrap; }}
        .metric {{ background: #1e293b; padding: 12px 16px; border-radius: 6px; }}
        .metric strong {{ display: block; margin-top: 4px; }}
        .diagram {{ overflow-x: auto; background: #020817; padding: 12px; border-radius: 6px; }}
        .diagram svg {{ display: block; min-width: 900px; max-width: 100%; height: auto; }}
        .mermaid {{ background: #020817; padding: 16px; overflow-x: auto; }}
        pre {{ white-space: pre-wrap; line-height: 1.5; }}
        code {{ color: #93c5fd; }}
    </style>
</head>
<body>
    <h1>Architecture PR Review</h1>
    <p><code>{escaped_base}</code> &rarr; <code>{escaped_head}</code></p>
    <section>
        <div class="metrics">
            <div class="metric">Base files<strong>{len(base_files)}</strong></div>
            <div class="metric">Head files<strong>{len(head_files)}</strong></div>
            <div class="metric">Changed<strong>{impact["summary"]["total_changed"]}</strong></div>
            <div class="metric">Removed<strong>{impact["summary"]["total_removed"]}</strong></div>
            <div class="metric">Impacted<strong>{impact["summary"]["total_impacted"]}</strong></div>
        </div>
        <p><strong>Diff paths:</strong> {diff_paths}</p>
        <p><strong>Changed files:</strong> {changed_files}</p>
        <p><strong>Removed files:</strong> {removed_files}</p>
        <p><strong>Impact summary:</strong> {impact_summary}</p>
    </section>
    <section><h2>High Level Design</h2><div class="diagram">{artifacts["hld_svg"]}</div></section>
    <section><h2>Dependency Impact</h2><div class="mermaid">{artifacts["impact_mermaid"]}</div></section>
    <section><h2>Layer Diagram</h2><div class="mermaid">{artifacts["layer_mermaid"]}</div></section>
    <section><h2>Repository Dependency Graph</h2><div class="mermaid">{artifacts["dependency_mermaid"]}</div></section>
    <section><h2>Architecture Review</h2><pre>{review_summary}</pre></section>
</body>
</html>
"""


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


def run(
    base: str,
    head: str,
    hld_output: Path | None = None,
    html_output: Path | None = None,
) -> str:
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

    if html_output:
        html_output.parent.mkdir(parents=True, exist_ok=True)
        html_output.write_text(
            render_html_report(base, head, base_files, head_files, changed_paths, impact, summary, artifacts),
            encoding="utf-8",
        )

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
    parser.add_argument("--html-output", type=Path, help="Optional standalone HTML report path")
    args = parser.parse_args()
    hld_output = args.output.with_suffix(".svg") if args.output else None
    report = run(args.base, args.head, hld_output, args.html_output)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(report)