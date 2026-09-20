#!/usr/bin/env python3
"""
Generate ARCHITECTURE.md from repository analysis.
This script analyzes the repository and generates a comprehensive ARCHITECTURE.md file.
"""

import argparse
import json
import sys
from pathlib import Path

# Add the current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from local_pr_review import run
from architecture_explorer import analyze_project, build_project_snapshot, render_hld_markdown, render_lld_markdown
from pathlib import Path


def generate_architecture_md(repo_path: Path, output_path: Path) -> None:
    """Generate ARCHITECTURE.md from repository analysis."""
    print(f"Analyzing repository at {repo_path}...")
    
    # Analyze the project
    summary = analyze_project(repo_path)
    snapshot = build_project_snapshot(summary)
    
    # Generate HLD and LLD markdown
    hld_md = render_hld_markdown(summary)
    lld_md = render_lld_markdown(summary)
    
    # Build architecture markdown
    lines = [
        "# Architecture Documentation",
        "",
        f"Generated from repository analysis of `{repo_path.name}`",
        "",
        "---",
        "",
        hld_md,
        "",
        "---",
        "",
        lld_md,
        "",
        "---",
        "",
        "## Module Details",
        "",
    ]
    
    # Add module details
    for module in summary.get("modules", []):
        name = module.get("name", "unknown")
        path = module.get("relative_path", "")
        classes = module.get("classes", [])
        functions = module.get("functions", [])
        imports = module.get("imports", [])
        
        lines.append(f"### {name}")
        lines.append(f"**Path:** `{path}`")
        lines.append("")
        
        if classes:
            lines.append(f"**Classes:** {', '.join(classes)}")
        else:
            lines.append("**Classes:** None")
            
        if functions:
            lines.append(f"**Functions:** {', '.join(functions)}")
        else:
            lines.append("**Functions:** None")
            
        if imports:
            lines.append(f"**Imports:** {', '.join(imports[:10])}{'...' if len(imports) > 10 else ''}")
        else:
            lines.append("**Imports:** None")
            
        lines.append("")
    
    # Add dependency information
    lines.append("---")
    lines.append("")
    lines.append("## Dependencies")
    lines.append("")
    
    dep_edges = summary.get("dependency_edges", [])
    if dep_edges:
        lines.append("| From | To |")
        lines.append("|------|----|")
        for src, dst in dep_edges:
            lines.append(f"| {src} | {dst} |")
    else:
        lines.append("No dependencies detected.")
    lines.append("")
    
    # Write output
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"ARCHITECTURE.md written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate ARCHITECTURE.md from repository analysis")
    parser.add_argument("repo_path", type=Path, help="Path to repository root")
    parser.add_argument("-o", "--output", type=Path, default=Path("ARCHITECTURE.md"), help="Output file path")
    args = parser.parse_args()
    
    generate_architecture_md(args.repo_path.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()