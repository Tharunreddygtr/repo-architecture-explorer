from __future__ import annotations

import argparse
import ast
import html
import io
import subprocess
import tempfile
import tarfile
from pathlib import Path

from architecture_explorer import analyze_project, build_pr_review_artifacts
from pr_impact import analyze_pr_impact, render_pr_impact_summary


ROOT = Path(__file__).resolve().parent


def _git_diff_stats(base: str, head: str, statuses: list[tuple[str, str]]) -> list[dict[str, object]]:
    status_by_path = {path: status for status, path in statuses}
    output = _git_value(["git", "diff", "--numstat", base, head])
    stats = []
    for line in output.splitlines():
        additions, deletions, path = line.split("\t", 2)
        stats.append({
            "path": path,
            "status": status_by_path.get(path, "M"),
            "additions": 0 if additions == "-" else int(additions),
            "deletions": 0 if deletions == "-" else int(deletions),
        })
    return stats


def _categorize_paths(paths: list[str]) -> dict[str, list[str]]:
    categories = {"API": [], "Database": [], "Config": [], "Tests": [], "Code": []}
    for path in paths:
        lowercase = path.lower()
        if any(token in lowercase for token in ("test", "spec")):
            category = "Tests"
        elif any(token in lowercase for token in ("migration", "schema", "model", "dao", "repository", "repo", ".sql")):
            category = "Database"
        elif any(token in lowercase for token in ("route", "endpoint", "api", "controller", "handler")):
            category = "API"
        elif any(token in lowercase for token in ("config", ".env", "settings", ".yml", ".yaml", ".json", ".toml")):
            category = "Config"
        else:
            category = "Code"
        categories[category].append(path)
    return categories


def _python_symbols(root: Path, relative_path: str) -> dict[tuple[str, str], str]:
    path = root / relative_path
    if path.suffix != ".py" or not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    symbols = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols[("class", node.name)] = ast.dump(node, include_attributes=False)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols[("function", node.name)] = ast.dump(node, include_attributes=False)
    return symbols


def _changed_python_symbols(base_root: Path, head_root: Path, paths: list[str]) -> list[dict[str, str]]:
    changes = []
    for path in paths:
        base_symbols = _python_symbols(base_root, path)
        head_symbols = _python_symbols(head_root, path)
        for key in sorted(set(base_symbols) | set(head_symbols)):
            kind, name = key
            if key not in base_symbols:
                change = "added"
            elif key not in head_symbols:
                change = "removed"
            elif base_symbols[key] != head_symbols[key]:
                change = "modified"
            else:
                continue
            changes.append({"path": path, "kind": kind, "name": name, "change": change})
    return changes


def render_html_report(
    base: str,
    head: str,
    base_files: list[str],
    head_files: list[str],
    impact_base_files: list[str],
    changed_paths: set[str],
    impact: dict,
    summary: dict,
    artifacts: dict[str, str],
    file_stats: list[dict[str, object]] | None = None,
    categories: dict[str, list[str]] | None = None,
    symbols: list[dict[str, str]] | None = None,
    metadata: dict[str, str] | None = None,
) -> str:
    file_stats = file_stats or []
    categories = categories or {}
    symbols = symbols or []
    metadata = metadata or {}
    title = f"Architecture PR Review: {base} -> {head}"
    escaped_title = html.escape(title)
    escaped_base = html.escape(base)
    escaped_head = html.escape(head)
    changed_files = html.escape(", ".join(impact["changed_files"]) or "none")
    removed_files = html.escape(", ".join(impact["removed_files"]) or "none")
    diff_paths = html.escape(", ".join(sorted(changed_paths)) or "none")
    impact_summary = html.escape(str(impact["summary"]))
    review_summary = html.escape(render_pr_impact_summary(impact_base_files, head_files, summary))
    pr_number = html.escape(metadata.get("number", ""))
    pr_title = html.escape(metadata.get("title", ""))
    pr_author = html.escape(metadata.get("author", ""))
    pr_url = html.escape(metadata.get("url", ""), quote=True)
    metadata_line = f"<p><strong>PR #{pr_number}</strong> &middot; {pr_author} &middot; <a href='{pr_url}'>Open on GitHub</a><br>{pr_title}</p>" if pr_number else ""
    file_rows = "".join(
        f"<tr><td><span class='status status-{html.escape(str(item['status']))}'>{html.escape(str(item['status']))}</span> <code>{html.escape(str(item['path']))}</code></td><td>+{item['additions']}</td><td>-{item['deletions']}</td></tr>"
        for item in file_stats
    ) or "<tr><td colspan='3'>No file changes detected.</td></tr>"
    category_sections = "".join(
        f"<div class='category'><h3>{html.escape(name)}</h3><ul>{''.join(f'<li><code>{html.escape(path)}</code></li>' for path in paths) or '<li>None</li>'}</ul></div>"
        for name, paths in categories.items()
    )
    symbol_rows = "".join(
        f"<tr><td>{html.escape(item['change'])}</td><td>{html.escape(item['kind'])}</td><td><code>{html.escape(item['path'])}</code></td><td>{html.escape(item['name'])}</td></tr>"
        for item in symbols
    ) or "<tr><td colspan='4'>No changed Python classes or functions detected.</td></tr>"

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
        .toolbar {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
        .toolbar input {{ flex: 1; min-width: 220px; background: #020817; color: #e2e8f0; border: 1px solid #475569; border-radius: 6px; padding: 10px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border-bottom: 1px solid #334155; padding: 10px; text-align: left; }}
        .status {{ display: inline-block; min-width: 22px; text-align: center; border-radius: 4px; padding: 2px 5px; font-weight: 700; }}
        .status-A {{ background: #166534; }} .status-M {{ background: #854d0e; }} .status-D {{ background: #991b1b; }}
        .categories {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }}
        .category {{ background: #0b1220; border: 1px solid #334155; padding: 12px; border-radius: 6px; }}
        .category h3 {{ margin-top: 0; }}
        .diagram {{ overflow-x: auto; background: #020817; padding: 12px; border-radius: 6px; }}
        .diagram svg {{ display: block; min-width: 900px; max-width: 100%; height: auto; }}
        .mermaid {{ background: #020817; padding: 16px; overflow-x: auto; }}
        pre {{ white-space: pre-wrap; line-height: 1.5; }}
        code {{ color: #93c5fd; }}
    </style>
</head>
<body>
    <h1>Architecture PR Review</h1>
    {metadata_line}
    <p><code>{escaped_base}</code> &rarr; <code>{escaped_head}</code></p>
    <div class="toolbar"><input id="report-search" type="search" placeholder="Filter files and symbols"><span class="small">Generated from Git diff and Python AST</span></div>
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
    <section><h2>Files Changed</h2><table id="file-stats"><thead><tr><th>File</th><th>Added</th><th>Deleted</th></tr></thead><tbody>{file_rows}</tbody></table></section>
    <section><h2>Change Categories</h2><div class="categories">{category_sections}</div></section>
    <section><h2>Changed Classes and Functions</h2><table id="symbol-stats"><thead><tr><th>Change</th><th>Kind</th><th>File</th><th>Symbol</th></tr></thead><tbody>{symbol_rows}</tbody></table></section>
    <section><h2>High Level Design</h2><div class="diagram">{artifacts["hld_svg"]}</div></section>
    <section><h2>Dependency Impact</h2><div class="mermaid">{artifacts["impact_mermaid"]}</div></section>
    <section><h2>Layer Diagram</h2><div class="mermaid">{artifacts["layer_mermaid"]}</div></section>
    <section><h2>Repository Dependency Graph</h2><div class="mermaid">{artifacts["dependency_mermaid"]}</div></section>
    <section><h2>Architecture Review</h2><pre>{review_summary}</pre></section>
        <script>
            document.getElementById('report-search').addEventListener('input', (event) => {{
                const query = event.target.value.toLowerCase();
                document.querySelectorAll('#file-stats tbody tr, #symbol-stats tbody tr, .category li').forEach((item) => {{
                    item.hidden = query && !item.textContent.toLowerCase().includes(query);
                }});
            }});
        </script>
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
    metadata: dict[str, str] | None = None,
    output_format: str = "markdown",
    exclude_patterns: list[str] | None = None,
) -> str:
    base_files = _git_files(base)
    head_files = _git_files(head)
    diff_status = _git_diff_status(base, head)
    changed_paths = {path for _, path in diff_status}
    
    # Apply exclude patterns if provided
    if exclude_patterns:
        import fnmatch
        filtered_paths = set()
        for path in changed_paths:
            if not any(fnmatch.fnmatch(path, pattern) for pattern in exclude_patterns):
                filtered_paths.add(path)
        changed_paths = filtered_paths
    
    file_stats = _git_diff_stats(base, head, diff_status)
    categories = _categorize_paths(sorted(changed_paths))
    modified_or_added = {path for status, path in diff_status if status in {"A", "M", "R"}}
    impact_base_files = [path for path in base_files if path not in modified_or_added]
    with tempfile.TemporaryDirectory(prefix="repo-architecture-review-") as temp_dir:
        review_root = Path(temp_dir)
        base_root = review_root / "base"
        head_root = review_root / "head"
        base_root.mkdir()
        head_root.mkdir()
        _materialize_commit(base, base_root)
        _materialize_commit(head, head_root)
        summary = analyze_project(head_root)
        symbols = _changed_python_symbols(base_root, head_root, sorted(changed_paths))
    impact = analyze_pr_impact(impact_base_files, head_files, summary)
    changed_names = [Path(item).name for item in impact["changed_files"]]
    removed_names = [Path(item).name for item in impact["removed_files"]]
    artifacts = build_pr_review_artifacts(summary, changed_names, removed_names)

    if html_output:
        html_output.parent.mkdir(parents=True, exist_ok=True)
        html_output.write_text(
            render_html_report(
                base,
                head,
                base_files,
                head_files,
                impact_base_files,
                changed_paths,
                impact,
                summary,
                artifacts,
                file_stats,
                categories,
                symbols,
                metadata,
            ),
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
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format (default: markdown)")
    parser.add_argument("--exclude-patterns", nargs="*", help="Optional glob patterns to exclude from analysis")
    parser.add_argument("--pr-number", help="Optional pull-request number for HTML metadata")
    parser.add_argument("--pr-title", help="Optional pull-request title for HTML metadata")
    parser.add_argument("--pr-author", help="Optional pull-request author for HTML metadata")
    parser.add_argument("--pr-url", help="Optional pull-request URL for HTML metadata")
    args = parser.parse_args()
    hld_output = args.output.with_suffix(".svg") if args.output else None
    metadata = {
        key: value
        for key, value in {
            "number": args.pr_number,
            "title": args.pr_title,
            "author": args.pr_author,
            "url": args.pr_url,
        }.items()
        if value
    }
    report = run(
        args.base,
        args.head,
        hld_output,
        args.html_output,
        metadata,
        args.format,
        args.exclude_patterns,
    )
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(report)