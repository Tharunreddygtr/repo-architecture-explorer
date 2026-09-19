from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

DEFAULT_EXCLUDES = {"__pycache__", ".git", ".venv", "node_modules", "venv", "dist", "build"}


def _classify_layer(name: str) -> str:
    lowercase_name = name.lower()
    if lowercase_name in {"app.py", "main.py"} or lowercase_name.endswith("/main.py"):
        return "entry"
    if any(token in lowercase_name for token in ("service", "handler", "controller")):
        return "service"
    if any(token in lowercase_name for token in ("model", "repo", "dao", "db")):
        return "data"
    return "infra"


def _module_lookup(summary: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for item in summary.get("modules", []):
        name = item.get("name", "")
        relative_path = str(item.get("relative_path", "")).replace("\\", "/")
        if not name:
            continue
        lookup[name] = name
        lookup[Path(name).stem] = name
        if relative_path:
            module_path = relative_path[:-3] if relative_path.endswith(".py") else relative_path
            lookup[module_path] = name
            lookup[module_path.replace("/", ".")] = name
            lookup[Path(relative_path).stem] = name
    return lookup


def _read_python_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        yield path


def _safe_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        value = _safe_name(node.value)
        attr = node.attr
        return f"{value}.{attr}" if value else attr
    if isinstance(node, ast.Call):
        return _safe_name(node.func)
    return None


def _extract_module_info(path: Path, root: Path | None = None) -> dict[str, Any]:
    relative_path = path.relative_to(root) if root is not None else path
    relative_path_text = str(relative_path).replace("\\", "/")
    source = _read_python_file(path)
    if not source:
        return {"name": path.name, "path": str(path), "relative_path": relative_path_text, "classes": [], "functions": [], "imports": []}

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"name": path.name, "path": str(path), "relative_path": relative_path_text, "classes": [], "functions": [], "imports": []}

    classes: list[str] = []
    functions: list[str] = []
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported = ", ".join(a.name for a in node.names)
            imports.append(f"from {module} import {imported}" if module else imported)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.FunctionDef):
            functions.append(node.name)
        elif isinstance(node, ast.AsyncFunctionDef):
            functions.append(node.name)

    return {
        "name": path.name,
        "path": str(path),
        "relative_path": relative_path_text,
        "classes": classes,
        "functions": functions,
        "imports": imports,
    }


def analyze_project(project_root: str | Path) -> dict[str, Any]:
    root = Path(project_root).resolve()
    modules: list[dict[str, Any]] = []
    dependency_edges: list[tuple[str, str]] = []

    for file_path in _iter_python_files(root):
        module = _extract_module_info(file_path, root)
        modules.append(module)

        source = _read_python_file(file_path)
        if not source:
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    dependency_edges.append((module["name"], alias.name))
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                dependency_edges.append((module["name"], module_name))
            elif isinstance(node, ast.Call):
                called = _safe_name(node.func)
                if called and "." in called:
                    dependency_edges.append((module["name"], called))

    return {
        "project_name": root.name,
        "project_root": str(root),
        "modules": modules,
        "dependency_edges": dependency_edges,
        "entrypoints": [m for m in modules if _classify_layer(m["name"]) == "entry"],
    }


def render_hld_markdown(summary: dict[str, Any]) -> str:
    modules = summary.get("modules", [])
    entrypoints = summary.get("entrypoints", [])
    module_lines = []

    for item in modules:
        class_names = ", ".join(item.get("classes", [])) or "none"
        function_names = ", ".join(item.get("functions", [])) or "none"
        module_lines.append(f"- {item['name']}: classes={class_names}; functions={function_names}")

    entry_text = ", ".join(item["name"] for item in entrypoints) if entrypoints else "application bootstrap"

    return f"""# High Level Design

## Overview
This repository is analyzed into a compact architecture view that shows the top-level components, module boundaries, and dependency flow.

## Major Components
- API / entry layer: {entry_text}
- Service / business logic layer: modules that orchestrate domain behavior
- Data / model layer: classes and functions used by services and handlers
- Dependency layer: imports and call relationships between modules

## Module Map
{chr(10).join(module_lines) if module_lines else '- No Python modules discovered'}

## Runtime Flow
1. Entry code loads the main module or startup path.
2. Modules import services and other helpers.
3. Business logic runs inside identified classes and functions.
4. Dependencies and call chains are mapped for impact analysis.
5. The resulting graph can be viewed as HLD and then drilled into selectively.

## Architecture Notes
- This version intentionally keeps the view simple and readable.
- The output is derived from real source code rather than static documentation.
- It is designed to support developer exploration and PR review workflows.
"""


def render_lld_markdown(summary: dict[str, Any]) -> str:
    modules = summary.get("modules", [])
    parts = ["# Low Level Design", "", "## Modules"]

    for item in modules:
        class_text = ", ".join(item.get("classes", [])) if item.get("classes") else "none"
        function_text = ", ".join(item.get("functions", [])) if item.get("functions") else "none"
        imports_text = ", ".join(item.get("imports", [])[:5]) if item.get("imports") else "none"

        parts.append(f"### {item['name']}")
        parts.append(f"- Classes: {class_text}")
        parts.append(f"- Functions: {function_text}")
        parts.append(f"- Imports: {imports_text}")

    dependency_edges = summary.get("dependency_edges", [])
    if dependency_edges:
        parts.append("")
        parts.append("## Dependency Flow")
        for src, dst in dependency_edges[:20]:
            parts.append(f"- {src} -> {dst}")

    return "\n".join(parts)


def render_hld_html(summary: dict[str, Any]) -> str:
    modules = summary.get("modules", [])
    cards = []
    for item in modules:
        classes = ", ".join(item.get("classes", [])) or "none"
        functions = ", ".join(item.get("functions", [])) or "none"
        cards.append(
            "<article class='card'>"
            f"<h3>{item['name']}</h3>"
            f"<p><strong>Classes:</strong> {classes}</p>"
            f"<p><strong>Functions:</strong> {functions}</p>"
            "</article>"
        )

    summary_cards = "\n".join(cards) if cards else "<p>No modules detected.</p>"
    return (
        "<section class='panel'>"
        "<h2>High Level Design</h2>"
        "<div class='metric-row'>"
        "<div class='metric'><span>Project</span><strong>{project_name}</strong></div>"
        "<div class='metric'><span>Modules</span><strong>{module_count}</strong></div>"
        "<div class='metric'><span>Edges</span><strong>{edge_count}</strong></div>"
        "</div>"
        "<div class='cards'>" + summary_cards + "</div>"
        "</section>"
    ).format(
        project_name=summary.get("project_name", "unknown"),
        module_count=len(modules),
        edge_count=len(summary.get("dependency_edges", [])),
    )


def render_lld_html(summary: dict[str, Any]) -> str:
    modules = summary.get("modules", [])
    rows = []
    for item in modules:
        classes = ", ".join(item.get("classes", [])) or "none"
        functions = ", ".join(item.get("functions", [])) or "none"
        imports = ", ".join(item.get("imports", [])[:5]) or "none"
        rows.append(
            "<tr>"
            f"<td>{item['name']}</td>"
            f"<td>{classes}</td>"
            f"<td>{functions}</td>"
            f"<td>{imports}</td>"
            "</tr>"
        )

    return (
        "<section class='panel'>"
        "<h2>Low Level Design</h2>"
        "<table><thead><tr><th>Module</th><th>Classes</th><th>Functions</th><th>Imports</th></tr></thead><tbody>"
        + ("".join(rows) if rows else "<tr><td colspan='4'>No modules available</td></tr>")
        + "</tbody></table></section>"
    )


def build_dashboard_payload(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_name": summary.get("project_name", "unknown"),
        "modules": summary.get("modules", []),
        "dependency_edges": summary.get("dependency_edges", []),
        "hld_markdown": render_hld_markdown(summary),
        "lld_markdown": render_lld_markdown(summary),
        "hld_html": render_hld_html(summary),
        "lld_html": render_lld_html(summary),
    }


def build_project_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    modules = summary.get("modules", [])
    layers = {
        "entry": [],
        "service": [],
        "data": [],
        "infra": [],
    }

    for item in modules:
        name = item.get("name", "")
        lowercase_name = name.lower()
        layers[_classify_layer(name)].append(name)

    return {
        "project_name": summary.get("project_name", "unknown"),
        "layers": layers,
        "components": [
            {
                "name": item.get("name"),
                "classes": item.get("classes", []),
                "functions": item.get("functions", []),
                "relative_path": item.get("relative_path"),
            }
            for item in modules
        ],
        "dependency_edges": summary.get("dependency_edges", []),
    }


def build_mermaid_diagram(summary: dict[str, Any]) -> str:
    modules = summary.get("modules", [])
    lines = ["graph TD"]
    seen = set()

    module_lookup = _module_lookup(summary)
    for item in modules:
        name = item.get("name", "")
        if name:
            lines.append(f"    {name}[{name}]")
            seen.add(name)

    for src, dst in summary.get("dependency_edges", []):
        resolved_src = module_lookup.get(src, src)
        resolved_dst = module_lookup.get(dst, dst)
        if resolved_src in seen and resolved_dst in seen:
            lines.append(f"    {resolved_src} --> {resolved_dst}")

    if len(lines) == 1:
        lines.append("    Repo[Repository]")

    return "\n".join(lines)


def build_svg_graph(
    summary: dict[str, Any],
    added_names: list[str] | None = None,
    removed_names: list[str] | None = None,
    view_name: str = "Architecture",
    visible_layers: list[str] | None = None,
    max_depth: int | None = None,
) -> str:
    modules = summary.get("modules", [])
    layer_order = ["entry", "service", "data", "infra"]
    all_modules = [item.get("name", "") for item in modules if item.get("name")]
    added_names = set((added_names or []) or [])
    removed_names = set((removed_names or []) or [])
    visible_layers = set((visible_layers or []) or [])
    if added_names or removed_names:
        view_name = "PR"
    if not all_modules:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='200' viewBox='0 0 1200 200'><text x='50%' y='50%' text-anchor='middle' fill='#e2e8f0'>No modules detected</text></svg>"

    def layer_for(name: str) -> str:
        lower = name.lower()
        return _classify_layer(name)

    if visible_layers:
        layer_order = [layer for layer in layer_order if layer in visible_layers]

    module_index = {item.get("name", ""): item for item in modules if item.get("name")}
    directed_graph = {name: [] for name in all_modules}
    module_lookup = _module_lookup(summary)
    for src, dst in summary.get("dependency_edges", []):
        resolved_src = module_lookup.get(src)
        resolved_dst = module_lookup.get(dst)
        if resolved_src in directed_graph and resolved_dst in directed_graph:
            directed_graph[resolved_src].append(resolved_dst)

    allowed_nodes: set[str] = set()
    if max_depth is not None and max_depth >= 0:
        start_nodes = [name for name in all_modules if layer_for(name) == "entry"]
        if not start_nodes:
            start_nodes = all_modules[:1]
        queue: list[tuple[str, int]] = [(node, 0) for node in start_nodes]
        visited: set[str] = set()
        while queue:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            if depth <= max_depth:
                allowed_nodes.add(current)
            if depth >= max_depth:
                continue
            for neighbor in directed_graph.get(current, []):
                if neighbor in module_index:
                    queue.append((neighbor, depth + 1))
        if not allowed_nodes:
            allowed_nodes = set(all_modules)
    else:
        allowed_nodes = set(all_modules)

    if visible_layers:
        allowed_nodes = {name for name in allowed_nodes if layer_for(name) in visible_layers}

    x_positions = {"entry": 220, "service": 520, "data": 820, "infra": 1040}
    y_step = 110
    node_w = 180
    node_h = 60
    lines = []
    lines.append("<svg id='architecture-svg' xmlns='http://www.w3.org/2000/svg' width='1200' height='620' viewBox='0 0 1200 620' aria-label='Architecture diagram'>")
    lines.append("<defs><style>.edge{stroke:#60a5fa;stroke-width:2;fill:none;stroke-linecap:round}.node{cursor:pointer;stroke-width:2;rx:12}.node:hover{opacity:0.9}.node-text{font: 14px Arial, sans-serif; fill:#e2e8f0; text-anchor:middle; dominant-baseline:middle}</style></defs>")
    lines.append(f"<text x='20' y='32' fill='#cbd5e1' font-size='18' font-family='Arial'>{view_name} View</text>")

    matrix: dict[str, list[str]] = {layer: [] for layer in layer_order}
    for name in sorted(all_modules):
        if name not in allowed_nodes:
            continue
        matrix.setdefault(layer_for(name), []).append(name)

    for layer in layer_order:
        items = matrix.get(layer, [])
        for idx, name in enumerate(items):
            x = x_positions.get(layer, 180)
            y = 90 + idx * y_step
            if name in added_names:
                fill = '#22c55e'
            elif name in removed_names:
                fill = '#ef4444'
            else:
                fill = '#111827'
            lines.append(f"<g class='node' data-module='{name}' data-layer='{layer}' tabindex='0' role='button'><title>{name}</title><rect x='{x - 90}' y='{y - 30}' width='{node_w}' height='{node_h}' rx='10' style='fill:{fill};stroke:#60a5fa' class='node'/><text x='{x}' y='{y}' class='node-text'>{name}</text></g>")

    for src, dst in summary.get("dependency_edges", []):
        if src not in allowed_nodes or dst not in allowed_nodes:
            continue
        resolved_src = module_lookup.get(src)
        resolved_dst = module_lookup.get(dst)
        if not resolved_src or not resolved_dst:
            continue
        src_layer = layer_for(resolved_src)
        dst_layer = layer_for(resolved_dst)
        src_idx = next((index for index, name in enumerate(matrix.get(src_layer, [])) if name == resolved_src), None)
        dst_idx = next((index for index, name in enumerate(matrix.get(dst_layer, [])) if name == resolved_dst), None)
        if src_idx is None or dst_idx is None:
            continue
        src_x = x_positions.get(src_layer, 180)
        dst_x = x_positions.get(dst_layer, 180)
        src_y = 90 + src_idx * y_step
        dst_y = 90 + dst_idx * y_step
        lines.append(f"<line class='edge' x1='{src_x + 10}' y1='{src_y}' x2='{dst_x - 10}' y2='{dst_y}'/>")

    lines.append("</svg>")
    return "\n".join(lines)


def build_module_details(summary: dict[str, Any], module_name: str) -> dict[str, Any]:
    module = next((item for item in summary.get("modules", []) if item.get("name") == module_name), None)
    if not module:
        return {"name": module_name, "classes": [], "functions": [], "imports": [], "dependencies": [], "reverse_dependencies": [], "layer": "unknown"}

    module_lookup = _module_lookup(summary)
    resolved_module_name = module_lookup.get(module_name, module_name)
    dependencies = sorted({
        module_lookup[dst]
        for src, dst in summary.get("dependency_edges", [])
        if module_lookup.get(src) == resolved_module_name and module_lookup.get(dst)
    })
    reverse_dependencies = sorted({
        module_lookup[src]
        for src, dst in summary.get("dependency_edges", [])
        if module_lookup.get(dst) == resolved_module_name and module_lookup.get(src)
    })
    layer = _classify_layer(resolved_module_name)

    return {
        "name": module_name,
        "path": module.get("relative_path") or module.get("path"),
        "layer": layer,
        "classes": module.get("classes", []),
        "functions": module.get("functions", []),
        "imports": module.get("imports", []),
        "dependencies": dependencies,
        "reverse_dependencies": reverse_dependencies,
        "nested_details": {
            "children": dependencies,
            "parents": reverse_dependencies,
        },
    }


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    summary = analyze_project(target)
    payload = build_dashboard_payload(summary)
    print(payload["hld_markdown"])
    print("\n---\n")
    print(payload["lld_markdown"])
