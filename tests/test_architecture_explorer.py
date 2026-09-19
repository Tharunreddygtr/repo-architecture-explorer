from pathlib import Path

from architecture_explorer import analyze_project, render_hld_markdown, render_lld_markdown


def test_analyze_project_finds_modules_and_dependencies(tmp_path):
    project = tmp_path / "demo_app"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text(
        "from app.service import SearchService\n\nclass API:\n    def run(self):\n        return SearchService().search()\n",
        encoding="utf-8",
    )
    (project / "app" / "service.py").write_text(
        "class SearchService:\n    def search(self):\n        return 'ok'\n",
        encoding="utf-8",
    )

    summary = analyze_project(project)

    assert summary["modules"]
    assert any(m["name"].endswith("main.py") for m in summary["modules"])
    assert any("app.service" in dep for dep in summary["dependency_edges"])


def test_render_hld_markdown_has_summary_sections():
    summary = {
        "project_name": "demo_app",
        "modules": [
            {"name": "main.py", "classes": ["API"], "functions": [], "imports": ["from app.service import SearchService"]},
            {"name": "service.py", "classes": ["SearchService"], "functions": ["search"], "imports": []},
        ],
        "dependency_edges": [("main.py", "app.service")],
    }

    hld = render_hld_markdown(summary)
    assert "High Level Design" in hld
    assert "Major Components" in hld
    assert "Runtime Flow" in hld


def test_render_lld_markdown_contains_module_details():
    summary = {
        "project_name": "demo_app",
        "modules": [
            {"name": "service.py", "classes": ["SearchService"], "functions": ["search"], "imports": []},
        ],
        "dependency_edges": [],
    }

    lld = render_lld_markdown(summary)
    assert "Low Level Design" in lld
    assert "SearchService" in lld
    assert "search" in lld
