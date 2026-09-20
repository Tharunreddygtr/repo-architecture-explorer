import hashlib
import hmac
import json
from unittest.mock import patch

import pytest

from architecture_explorer import analyze_project, build_mermaid_diagram, build_project_snapshot, build_pr_review_artifacts, build_svg_graph
from pr_impact import analyze_pr_impact, render_pr_impact_summary
from repo_watcher import RepoWatcher
from app import app


def test_build_project_snapshot_groups_modules_by_layer(tmp_path):
    project = tmp_path / "demo_app"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text(
        "class API:\n    def run(self):\n        return 'ok'\n",
        encoding="utf-8",
    )
    (project / "app" / "service.py").write_text(
        "class SearchService:\n    def search(self):\n        return 'ok'\n",
        encoding="utf-8",
    )

    summary = analyze_project(project)
    snapshot = build_project_snapshot(summary)

    assert snapshot["layers"]["entry"]
    assert snapshot["layers"]["service"]
    assert snapshot["components"]


def test_pr_impact_flags_changed_dependencies(tmp_path):
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
    impact = analyze_pr_impact(["app/main.py"], ["app/main.py", "app/service.py"], summary)
    pr_summary = render_pr_impact_summary(["app/main.py"], ["app/main.py", "app/service.py"], summary)

    assert impact["summary"]["total_changed"] >= 1
    assert impact["impacted_modules"]
    assert "Architecture Review Summary" in pr_summary
    assert "HLD Impact" in pr_summary
    assert "LLD Impact" in pr_summary
    assert "Risk" in pr_summary
    assert "service.py" in pr_summary


def test_build_mermaid_diagram_contains_nodes_and_edges(tmp_path):
    project = tmp_path / "demo_app"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text(
        "from app.service import SearchService\nclass API:\n    def run(self):\n        return SearchService().search()\n",
        encoding="utf-8",
    )
    (project / "app" / "service.py").write_text(
        "class SearchService:\n    def search(self):\n        return 'ok'\n",
        encoding="utf-8",
    )

    summary = analyze_project(project)
    mermaid = build_mermaid_diagram(summary)

    assert "graph TD" in mermaid
    assert "main.py" in mermaid
    assert "service.py" in mermaid


def test_app_exposes_summary_and_mermaid_api():
    client = app.test_client()

    summary_response = client.get("/api/summary")
    mermaid_response = client.get("/api/mermaid")
    watcher_response = client.get("/api/watcher-status")

    assert summary_response.status_code == 200
    assert mermaid_response.status_code == 200
    assert watcher_response.status_code == 200
    assert "project_name" in summary_response.get_json()
    assert "graph TD" in mermaid_response.get_data(as_text=True)
    assert "repo_path" in watcher_response.get_json()


def test_repo_watcher_detects_changes_and_status(tmp_path):
    package = tmp_path / "repo"
    package.mkdir()
    file_path = package / "main.py"
    file_path.write_text("class API:\n    pass\n", encoding="utf-8")

    watcher = RepoWatcher(package)
    assert watcher.status()["module_count"] >= 1

    file_path.write_text("class API:\n    def run(self):\n        return 'updated'\n", encoding="utf-8")
    assert watcher.has_changes() is True


def test_app_refresh_endpoint_updates_snapshot_and_status():
    client = app.test_client()
    response = client.post("/api/refresh")

    assert response.status_code == 200
    payload = response.get_json()
    assert "watch_status" in payload
    assert "modules" in payload
    assert payload["watch_status"]["repo_path"]


def test_github_pr_webhook_generates_architecture_review_summary():
    client = app.test_client()
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 12,
            "title": "Update architecture service",
            "base": {"ref": "main"},
            "head": {"ref": "feature/service-update"},
            "changed_files": ["app/main.py", "app/service.py"],
        },
    }

    response = client.post("/api/github/pr-webhook", json=payload)
    data = response.get_json()

    assert response.status_code == 200
    assert data["event"] == "pull_request"
    assert data["summary"]["total_changed"] >= 1
    assert "Architecture Review Summary" in data["report"]
    assert "HLD Impact" in data["report"]


def test_github_pr_webhook_validates_signature_and_uses_diff_data():
    app.config["GITHUB_WEBHOOK_SECRET"] = "supersecret"
    client = app.test_client()
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 33,
            "title": "Service diff review",
            "base": {"ref": "main"},
            "head": {"ref": "feature/service-test"},
            "changed_files": ["app/main.py", "app/service.py"],
        },
        "base_files": ["app/main.py"],
        "head_files": ["app/main.py", "app/service.py"],
    }
    raw = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(b"supersecret", raw, hashlib.sha256).hexdigest()

    invalid_response = client.post(
        "/api/github/pr-webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=invalid"},
    )
    assert invalid_response.status_code == 401

    valid_response = client.post(
        "/api/github/pr-webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "pull_request"},
    )
    data = valid_response.get_json()

    assert valid_response.status_code == 200
    assert data["diff_summary"]["base_files"] == ["app/main.py"]
    assert data["diff_summary"]["head_files"] == ["app/main.py", "app/service.py"]


def test_pr_review_artifacts_include_multiple_diagrams():
    summary = {
        "project_name": "demo_app",
        "entrypoints": [{"name": "main.py"}],
        "modules": [
            {"name": "main.py", "relative_path": "app/main.py", "classes": [], "functions": [], "imports": []},
            {"name": "service.py", "relative_path": "app/service.py", "classes": [], "functions": [], "imports": []},
        ],
        "dependency_edges": [("main.py", "service.py")],
    }

    artifacts = build_pr_review_artifacts(summary, ["service.py"])

    assert {"hld_svg", "dependency_mermaid", "layer_mermaid", "impact_mermaid", "hld_markdown", "lld_markdown"} <= set(artifacts)
    assert "PR HLD View" in artifacts["hld_svg"]
    assert "service.py" in artifacts["impact_mermaid"]


def test_webhook_persists_diagram_first_review(monkeypatch):
    client = app.test_client()
    monkeypatch.setattr(
        "app._fetch_pr_file_changes",
        lambda repository, pr_number: (["app.py"], ["app.py"], []),
    )
    app.config["GITHUB_WEBHOOK_SECRET"] = None

    response = client.post(
        "/api/github/pr-webhook",
        json={
            "action": "opened",
            "repository": {"full_name": "example/repo"},
            "pull_request": {"number": 44, "title": "Architecture change", "changed_files": 1},
            "base_files": [],
            "head_files": ["app.py"],
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["pr_number"] == 44
    assert "hld_svg" in data["artifacts"]
    assert "layer_mermaid" in data["artifacts"]
    stored = client.get("/api/pr-review")
    assert stored.status_code == 200
    assert stored.get_json()["pr_number"] == 44


def test_webhook_can_post_diagram_review_to_github(monkeypatch):
    client = app.test_client()
    monkeypatch.setattr(
        "app._fetch_pr_file_changes",
        lambda repository, pr_number: (["app.py"], ["app.py"], []),
    )
    posted = {}

    def fake_comment(repository, pr_number, comment):
        posted["repository"] = repository
        posted["pr_number"] = pr_number
        posted["comment"] = comment
        return {"id": 123}, 201

    monkeypatch.setattr("app._post_github_issue_comment", fake_comment)
    app.config["GITHUB_WEBHOOK_SECRET"] = None
    app.config["AUTO_COMMENT_ON_PR"] = True

    try:
        response = client.post(
            "/api/github/pr-webhook",
            json={
                "action": "opened",
                "repository": {"full_name": "example/repo"},
                "pull_request": {"number": 45, "title": "Post architecture review", "changed_files": 1},
                "base_files": [],
                "head_files": ["app.py"],
            },
        )
    finally:
        app.config["AUTO_COMMENT_ON_PR"] = False

    data = response.get_json()
    assert response.status_code == 200
    assert data["auto_comment"]["posted"] is True
    assert posted["repository"] == "example/repo"
    assert posted["pr_number"] == 45
    assert "```mermaid" in posted["comment"]
    assert "HLD / LLD Review" in posted["comment"]


def test_github_webhook_secret_can_be_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "env-secret")
    app.config["GITHUB_WEBHOOK_SECRET"] = None
    client = app.test_client()

    raw = json.dumps({"action": "opened", "pull_request": {"changed_files": ["app/main.py"]}}).encode("utf-8")
    invalid = client.post(
        "/api/github/pr-webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": "sha256=invalid", "X-GitHub-Event": "pull_request"},
    )
    assert invalid.status_code == 401

    valid_signature = "sha256=" + hmac.new(b"env-secret", raw, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/github/pr-webhook",
        data=raw,
        content_type="application/json",
        headers={"X-Hub-Signature-256": valid_signature, "X-GitHub-Event": "pull_request"},
    )

    assert response.status_code == 200
    assert response.get_json()["event"] == "pull_request"


def test_hld_is_first_and_module_details_are_clickable():
    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "High Level Design" in html
    assert "details" in html.lower()
    assert "module-details" in html
    assert "svg" in html.lower()


def test_pr_view_highlights_additions_and_deletions_in_svg():
    summary = {
        "project_name": "demo_app",
        "modules": [
            {"name": "main.py", "relative_path": "app/main.py", "classes": [], "functions": [], "imports": []},
            {"name": "service.py", "relative_path": "app/service.py", "classes": [], "functions": [], "imports": []},
        ],
        "dependency_edges": [("main.py", "service.py")],
    }

    svg = build_svg_graph(summary, added_names=["service.py"], removed_names=["main.py"])

    assert "#22c55e" in svg
    assert "#ef4444" in svg
    assert "PR View" in svg


def test_module_details_api_returns_real_component_data():
    client = app.test_client()
    response = client.get("/api/module/app.py")

    assert response.status_code == 200
    data = response.get_json()
    assert data["name"] == "app.py"
    assert "classes" in data or "functions" in data


def test_svg_graph_supports_layer_and_depth_filters():
    summary = {
        "project_name": "demo_app",
        "modules": [
            {"name": "main.py", "relative_path": "app/main.py", "classes": [], "functions": [], "imports": []},
            {"name": "service.py", "relative_path": "app/service.py", "classes": [], "functions": [], "imports": []},
            {"name": "repository.py", "relative_path": "app/repository.py", "classes": [], "functions": [], "imports": []},
        ],
        "dependency_edges": [("main.py", "service.py"), ("service.py", "repository.py")],
    }

    svg = build_svg_graph(summary, visible_layers=["entry", "service"], max_depth=1)

    assert "main.py" in svg
    assert "service.py" in svg
    assert "repository.py" not in svg


def test_pr_comment_generation_for_selected_component():
    client = app.test_client()
    response = client.post(
        "/api/pr-comment",
        json={"module_name": "service.py", "comment": "Looks stable but validate downstream calls."},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["module_name"] == "service.py"
    assert "comment" in data or "review" in data


def test_graph_api_applies_browser_filters():
    client = app.test_client()
    response = client.get("/api/graph?layers=entry,service&depth=1")

    assert response.status_code == 200
    data = response.get_json()
    assert data["layers"] == ["entry", "service"]
    assert data["max_depth"] == 1
    assert "architecture-svg" in data["svg"]


def test_github_pr_comment_posts_architecture_context():
    class FakeResponse:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'{"id": 42, "html_url": "https://github.com/example/repo/issues/7#issuecomment-42"}'

    previous_token = app.config.get("GITHUB_TOKEN")
    app.config["GITHUB_TOKEN"] = "test-token"
    try:
        with patch("app.urlopen", return_value=FakeResponse()) as mocked_urlopen:
            client = app.test_client()
            response = client.post(
                "/api/github/pr-comment",
                json={
                    "repository": "example/repo",
                    "pr_number": 7,
                    "module_name": "service.py",
                    "comment": "Please verify the downstream dependency.",
                },
            )

        assert response.status_code == 201
        data = response.get_json()
        assert data["github_comment"]["id"] == 42
        request_body = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        assert "service.py" in request_body["body"]
        assert "Please verify" in request_body["body"]
        assert mocked_urlopen.call_args.args[0].full_url.endswith("/repos/example/repo/issues/7/comments")
    finally:
        app.config["GITHUB_TOKEN"] = previous_token


def test_architecture_quality_classifies_real_layers_and_dependencies(tmp_path):
    project = tmp_path / "quality_repo"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text(
        "from app.service import OrderService\n\nclass App:\n    def run(self):\n        return OrderService().create()\n",
        encoding="utf-8",
    )
    (project / "app" / "service.py").write_text(
        "from app.repository import OrderRepository\n\nclass OrderService:\n    def create(self):\n        return OrderRepository().fetch()\n",
        encoding="utf-8",
    )
    (project / "app" / "repository.py").write_text(
        "class OrderRepository:\n    def fetch(self):\n        return 'ok'\n",
        encoding="utf-8",
    )
    (project / "app" / "util.py").write_text(
        "def helper():\n    return 'unused'\n",
        encoding="utf-8",
    )

    summary = analyze_project(project)
    snapshot = build_project_snapshot(summary)
    mermaid = build_mermaid_diagram(summary)

    assert "main.py" in snapshot["layers"]["entry"]
    assert "service.py" in snapshot["layers"]["service"]
    assert "repository.py" in snapshot["layers"]["data"]
    assert "main.py" in mermaid and "service.py" in mermaid and "repository.py" in mermaid
    assert "main.py --> service.py" in mermaid or "service.py --> main.py" in mermaid


def test_pr_impact_quality_tracks_real_blast_radius_not_just_changed_files(tmp_path):
    project = tmp_path / "blast_radius_repo"
    (project / "app").mkdir(parents=True)
    (project / "app" / "main.py").write_text(
        "from app.service import OrderService\n\nclass App:\n    def run(self):\n        return OrderService().create()\n",
        encoding="utf-8",
    )
    (project / "app" / "service.py").write_text(
        "from app.repository import OrderRepository\n\nclass OrderService:\n    def create(self):\n        return OrderRepository().fetch()\n",
        encoding="utf-8",
    )
    (project / "app" / "repository.py").write_text(
        "class OrderRepository:\n    def fetch(self):\n        return 'ok'\n",
        encoding="utf-8",
    )
    (project / "app" / "notifier.py").write_text(
        "class Notifier:\n    def send(self):\n        return 'nope'\n",
        encoding="utf-8",
    )

    summary = analyze_project(project)
    impact = analyze_pr_impact(["app/main.py"], ["app/main.py", "app/service.py"], summary)
    pr_report = render_pr_impact_summary(["app/main.py"], ["app/main.py", "app/service.py"], summary)

    assert "service.py" in " ".join(impact["impacted_modules"])
    assert "notifier.py" not in " ".join(impact["impacted_modules"])
    assert "service.py" in pr_report
    assert "repository.py" in pr_report or "OrderRepository" in pr_report
