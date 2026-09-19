from __future__ import annotations

from pathlib import Path
from typing import Any


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _module_matches_changed(item: dict[str, Any], changed_paths: set[str], changed_names: set[str]) -> bool:
    module_name = item.get("name", "")
    relative_path = _normalize_path(item.get("relative_path", ""))
    return (
        module_name in changed_names
        or relative_path in changed_paths
        or module_name in changed_paths
        or relative_path.endswith(tuple(f"/{name}" for name in changed_names))
    )


def analyze_pr_impact(base_files: list[str], head_files: list[str], summary: dict[str, Any]) -> dict[str, Any]:
    base_set = {_normalize_path(item) for item in base_files}
    head_set = {_normalize_path(item) for item in head_files}

    touched = sorted(base_set | head_set)
    changed = sorted(head_set - base_set)
    removed = sorted(base_set - head_set)

    modules = summary.get("modules", [])
    impacted_modules = []
    changed_paths = set(changed)
    changed_names = {Path(item).name for item in changed}

    for item in modules:
        if _module_matches_changed(item, changed_paths, changed_names):
            impacted_modules.append(item.get("name", ""))

    for edge_src, edge_dst in summary.get("dependency_edges", []):
        if edge_src in changed_paths or edge_dst in changed_paths or edge_src in changed_names or edge_dst in changed_names:
            impacted_modules.append(f"{edge_src} -> {edge_dst}")

    return {
        "touched_files": touched,
        "changed_files": changed,
        "removed_files": removed,
        "impacted_modules": sorted(set(impacted_modules)),
        "summary": {
            "total_changed": len(changed),
            "total_removed": len(removed),
            "total_impacted": len(set(impacted_modules)),
        },
    }


def render_pr_impact_summary(base_files: list[str], head_files: list[str], summary: dict[str, Any]) -> str:
    impact = analyze_pr_impact(base_files, head_files, summary)
    modules = summary.get("modules", [])
    changed_paths = {_normalize_path(item) for item in head_files}
    changed_names = {Path(p).name for p in changed_paths}

    impacted_module_details = []
    for item in modules:
        relative_path = _normalize_path(item.get("relative_path", ""))
        if relative_path in changed_paths or item.get("name", "") in changed_names:
            classes = ", ".join(item.get("classes", [])) or "none"
            functions = ", ".join(item.get("functions", [])) or "none"
            impacted_module_details.append(f"- {item.get('name')} | classes: {classes} | functions: {functions}")

    if impact["impacted_modules"]:
        module_summary = ", ".join(impact["impacted_modules"])
    else:
        module_summary = "no direct module impact detected"

    if impact["summary"]["total_changed"] > 2:
        risk = "High"
    elif impact["summary"]["total_changed"] > 0:
        risk = "Medium"
    else:
        risk = "Low"

    hld_lines = [
        "# Architecture Review Summary",
        "",
        "## HLD Impact",
        f"- Changed files: {', '.join(impact['changed_files']) if impact['changed_files'] else 'none'}",
        f"- Components affected: {module_summary}",
        f"- Risk: {risk}",
        "- Architectural note: review dependency boundaries and service entry points before merge.",
    ]

    lld_lines = [
        "## LLD Impact",
        "- Changed implementation blocks:",
    ] + (impacted_module_details or ["- No directly impacted low-level modules detected."])

    comments = [
        "## Reviewer Guidance",
        "- Confirm the change is limited to the intended layer.",
        "- Validate downstream calls and imports for blast radius.",
        "- Check whether a shared component or service is now coupled to the modified module.",
    ]

    return "\n".join(hld_lines + ["", *lld_lines, "", *comments])
