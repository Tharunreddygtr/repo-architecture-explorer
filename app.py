import hashlib
import hmac
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Flask, jsonify, render_template_string, request
from pathlib import Path

from architecture_explorer import (
  analyze_project,
  build_dashboard_payload,
  build_pr_review_artifacts,
  build_mermaid_diagram,
  build_module_details,
  build_project_snapshot,
  build_svg_graph,
)
from pr_impact import analyze_pr_impact, render_pr_impact_summary
from repo_watcher import RepoWatcher

app = Flask(__name__)
app.config["WATCHER"] = RepoWatcher(Path(__file__).resolve().parent)
app.config["GITHUB_WEBHOOK_SECRET"] = os.getenv("GITHUB_WEBHOOK_SECRET")
app.config["GITHUB_TOKEN"] = os.getenv("GITHUB_TOKEN")
app.config["GITHUB_REPOSITORY"] = os.getenv("GITHUB_REPOSITORY")
app.config["LATEST_PR_REVIEW"] = None

HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Architecture Explorer</title>
  <style>
    body { font-family: Arial, sans-serif; background: #0f172a; color: #e2e8f0; margin: 0; padding: 24px; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { margin-bottom: 12px; }
    .panel { background: #111827; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-top: 20px; }
    .metric-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
    .metric { background: #1e293b; border-radius: 8px; padding: 12px 16px; min-width: 100px; }
    .metric span { display: block; color: #94a3b8; font-size: 12px; text-transform: uppercase; }
    .metric strong { font-size: 20px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
    .card { background: #0b1220; border: 1px solid #374151; border-radius: 8px; padding: 14px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; border-bottom: 1px solid #334155; padding: 10px; vertical-align: top; }
    th { color: #cbd5e1; }
    .small { color: #94a3b8; font-size: 12px; }
    pre { white-space: pre-wrap; background: #020817; padding: 16px; border-radius: 10px; border: 1px solid #334155; }
    .layer { margin-top: 14px; }
    .diagram-shell { overflow: auto; border: 1px solid #334155; background: #020817; border-radius: 12px; padding: 10px; }
    .diagram-toolbar { display: flex; gap: 10px; margin-bottom: 12px; }
    .diagram-toolbar button { background: #1e293b; color: #e2e8f0; border: 1px solid #475569; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
    .filter-bar { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; padding: 12px; background: #0b1220; border: 1px solid #334155; border-radius: 8px; }
    .filter-bar label { font-size: 13px; color: #cbd5e1; }
    .filter-bar input[type='number'], .review-form input, .review-form textarea { background: #020817; color: #e2e8f0; border: 1px solid #475569; border-radius: 6px; padding: 8px; }
    .filter-bar input[type='number'] { width: 70px; }
    .module-details { margin-top: 12px; background: #020817; border: 1px solid #334155; border-radius: 10px; padding: 16px; min-height: 120px; }
    .module-details button, .review-form button { background: #2563eb; color: white; border: 0; border-radius: 6px; padding: 8px 12px; cursor: pointer; }
    .nested-list { margin: 8px 0 0 16px; padding-left: 16px; }
    .review-form { display: grid; gap: 8px; margin-top: 16px; }
    .review-form textarea { min-height: 70px; resize: vertical; }
    .review-status { color: #93c5fd; }
    .pr-diagrams { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
    .pr-diagram { background: #020817; border: 1px solid #334155; border-radius: 8px; padding: 12px; }
    .hidden { display: none; }
    svg { display: block; max-width: 100%; background: #020817; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Architecture Explorer</h1>
    <div class="small">Project: {{ project_name }}</div>

    <section class="panel">
      <h2>High Level Design</h2>
      <div class="filter-bar" aria-label="Architecture filters">
        <strong>Layers</strong>
        <label><input type="checkbox" class="layer-filter" value="entry" checked /> Entry</label>
        <label><input type="checkbox" class="layer-filter" value="service" checked /> Service</label>
        <label><input type="checkbox" class="layer-filter" value="data" checked /> Data</label>
        <label><input type="checkbox" class="layer-filter" value="infra" checked /> Infra</label>
        <label for="depth-filter">Dependency depth
          <input id="depth-filter" type="number" min="0" placeholder="all" />
        </label>
        <button type="button" id="apply-filters">Apply</button>
      </div>
      <div class="diagram-toolbar">
        <button type="button" id="zoom-in">Zoom In</button>
        <button type="button" id="zoom-out">Zoom Out</button>
        <button type="button" id="zoom-reset">Reset</button>
      </div>
      <div class="diagram-shell">
        {{ hld_svg | safe }}
      </div>
      <div id="module-details" class="module-details">
        <div class="small">Hover a node for its label, then click to explore nested dependencies.</div>
      </div>
      <form id="review-form" class="review-form">
        <strong>Comment on selected component</strong>
        <input id="github-repository" placeholder="owner/repository" value="{{ github_repository or '' }}" />
        <input id="github-pr-number" type="number" min="1" placeholder="Pull request number" />
        <textarea id="github-comment" placeholder="Write a review comment..."></textarea>
        <button type="submit">Post GitHub PR comment</button>
        <div id="review-status" class="review-status small"></div>
      </form>
    </section>

    <details class="panel" open>
      <summary>View internal components</summary>
      <div style="margin-top: 14px;">
        {{ lld_html | safe }}
      </div>
    </details>

    <section class="panel">
      <h2>Layered Architecture</h2>
      {% for layer_name, items in layers.items() %}
      <div class="layer">
        <strong>{{ layer_name.title() }}</strong>
        {% if items %}
        <ul>
          {% for item in items %}
          <li>{{ item }}</li>
          {% endfor %}
        </ul>
        {% else %}
        <div class="small">No items detected.</div>
        {% endif %}
      </div>
      {% endfor %}
    </section>

    <section class="panel">
      <h2>Mermaid Diagram</h2>
      <pre>{{ mermaid }}</pre>
    </section>

    <section class="panel">
      <h2>Watch Status</h2>
      <div class="small">Last refresh: {{ refresh_status.last_updated or 'unknown' }}</div>
      <div class="small">Dirty state: {{ refresh_status.changed }}</div>
    </section>

    <section class="panel">
      <h2>PR Review Summary</h2>
      {% if pr_review %}
      <div class="small">Latest webhook: PR #{{ pr_review.pr_number }} | {{ pr_review.action }} | {{ pr_review.repository }}</div>
      <div class="pr-diagrams">
        <div class="pr-diagram"><h3>PR HLD</h3>{{ pr_review.artifacts.hld_svg | safe }}</div>
        <div class="pr-diagram"><h3>Dependency Impact</h3><pre>{{ pr_review.artifacts.impact_mermaid }}</pre></div>
        <div class="pr-diagram"><h3>Layer View</h3><pre>{{ pr_review.artifacts.layer_mermaid }}</pre></div>
        <div class="pr-diagram"><h3>Repository Dependency Graph</h3><pre>{{ pr_review.artifacts.dependency_mermaid }}</pre></div>
      </div>
      <details open><summary>HLD and LLD artifacts</summary><pre>{{ pr_review.artifacts.hld_markdown }}

{{ pr_review.artifacts.lld_markdown }}</pre></details>
      {% endif %}
      <pre>{{ pr_summary }}</pre>
    </section>
  </div>

  <script>
    let svg = document.getElementById('architecture-svg');
    const detailsPanel = document.getElementById('module-details');
    let selectedModule = null;
    const defaultScale = 1;
    let currentScale = defaultScale;

    function setScale(scale) {
      if (!svg) return;
      currentScale = Math.max(0.5, Math.min(2.2, scale));
      svg.style.transform = 'scale(' + currentScale + ')';
      svg.style.transformOrigin = 'center center';
      svg.style.transition = 'transform 0.15s ease';
    }

    document.getElementById('zoom-in')?.addEventListener('click', () => setScale(currentScale + 0.15));
    document.getElementById('zoom-out')?.addEventListener('click', () => setScale(currentScale - 0.15));
    document.getElementById('zoom-reset')?.addEventListener('click', () => setScale(defaultScale));

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>'"]/g, (character) => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[character]));
    }

    async function loadModule(moduleName, append = false) {
      if (!moduleName) return;
      try {
        const response = await fetch('/api/module/' + encodeURIComponent(moduleName));
        const data = await response.json();
        if (!response.ok || !data.name) throw new Error('module unavailable');
        selectedModule = data.name;
        const dependencies = (data.dependencies || []).map((item) => '<li><button type="button" class="nested-module" data-module="' + escapeHtml(item) + '">' + escapeHtml(item) + '</button></li>').join('');
        const parents = (data.reverse_dependencies || []).map((item) => '<li><button type="button" class="nested-module" data-module="' + escapeHtml(item) + '">' + escapeHtml(item) + '</button></li>').join('');
        const content = '<h3>' + escapeHtml(data.name) + ' <span class="small">(' + escapeHtml(data.layer) + ')</span></h3>' +
          '<div><strong>Classes:</strong> ' + escapeHtml((data.classes || []).join(', ') || 'none') + '</div>' +
          '<div><strong>Functions:</strong> ' + escapeHtml((data.functions || []).join(', ') || 'none') + '</div>' +
          '<div><strong>Imports:</strong> ' + escapeHtml((data.imports || []).slice(0, 5).join(', ') || 'none') + '</div>' +
          '<div><strong>Dependencies</strong><ul class="nested-list">' + (dependencies || '<li class="small">none</li>') + '</ul></div>' +
          '<div><strong>Used by</strong><ul class="nested-list">' + (parents || '<li class="small">none</li>') + '</ul></div>';
        detailsPanel.innerHTML = append ? detailsPanel.innerHTML + '<hr />' + content : content;
      } catch (error) {
        detailsPanel.innerHTML = '<div class="small">Unable to load details for this module.</div>';
      }
    }

    document.addEventListener('click', (event) => {
      const node = event.target.closest('[data-module]');
      if (node) loadModule(node.getAttribute('data-module'));
    });
    detailsPanel.addEventListener('click', (event) => {
      const node = event.target.closest('.nested-module');
      if (node) loadModule(node.getAttribute('data-module'), true);
    });

    async function applyFilters() {
      const layers = Array.from(document.querySelectorAll('.layer-filter:checked')).map((item) => item.value).join(',');
      const depth = document.getElementById('depth-filter').value;
      const query = new URLSearchParams({layers});
      if (depth !== '') query.set('depth', depth);
      const response = await fetch('/api/graph?' + query.toString());
      const data = await response.json();
      document.querySelector('.diagram-shell').innerHTML = data.svg;
      svg = document.getElementById('architecture-svg');
      setScale(currentScale);
    }
    document.getElementById('apply-filters')?.addEventListener('click', applyFilters);

    document.getElementById('review-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const status = document.getElementById('review-status');
      if (!selectedModule) { status.textContent = 'Select a component first.'; return; }
      status.textContent = 'Posting comment...';
      const response = await fetch('/api/github/pr-comment', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
        repository: document.getElementById('github-repository').value,
        pr_number: document.getElementById('github-pr-number').value,
        module_name: selectedModule,
        comment: document.getElementById('github-comment').value
      })});
      const data = await response.json();
      status.textContent = response.ok ? 'GitHub comment posted.' : (data.error || 'Unable to post comment.');
    });
  </script>
</body>
</html>
"""


def _analyze_current_repo():
    watcher = app.config["WATCHER"]
    summary, snapshot = watcher.scan()
    payload = build_dashboard_payload(summary)
    return summary, payload, snapshot, watcher.status()


def _post_github_issue_comment(repository: str, pr_number: int, comment: str) -> tuple[dict, int]:
    token = app.config.get("GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        return {"error": "GITHUB_TOKEN is not configured"}, 503

    endpoint = f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments"
    body = json.dumps({"body": comment}).encode("utf-8")
    github_request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "repo-architecture-explorer",
        },
    )
    try:
        with urlopen(github_request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except HTTPError as error:
        return {"error": f"GitHub API returned HTTP {error.code}"}, error.code
    except URLError:
        return {"error": "GitHub API could not be reached"}, 502


def _github_get_json(endpoint: str) -> tuple[object, int]:
    token = app.config.get("GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "repo-architecture-explorer",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(endpoint, method="GET", headers=headers), timeout=15) as response:
            return json.loads(response.read().decode("utf-8")), response.status
    except HTTPError as error:
        return {"error": f"GitHub API returned HTTP {error.code}"}, error.code
    except URLError:
        return {"error": "GitHub API could not be reached"}, 502


def _fetch_pr_file_changes(repository: str, pr_number: int) -> tuple[list[str], list[str], list[str]]:
    endpoint = f"https://api.github.com/repos/{repository}/pulls/{pr_number}/files?per_page=100"
    response, status = _github_get_json(endpoint)
    if status >= 400 or not isinstance(response, list):
        return [], [], []

    changed = []
    added = []
    removed = []
    for item in response:
        filename = item.get("filename") if isinstance(item, dict) else None
        if not filename:
            continue
        changed.append(filename)
        if item.get("status") == "removed":
            removed.append(filename)
        else:
            added.append(filename)
    return changed, added, removed


@app.route("/")
def index():
    summary, payload, snapshot, refresh_status = _analyze_current_repo()
    pr_summary = render_pr_impact_summary(["app.py"], ["app.py", "architecture_explorer.py"], summary)
    mermaid = build_mermaid_diagram(summary)
    hld_svg = build_svg_graph(summary)
    return render_template_string(
        HTML_TEMPLATE,
        project_name=payload["project_name"],
        hld_html=payload["hld_html"],
        lld_html=payload["lld_html"],
        hld_svg=hld_svg,
        layers=snapshot["layers"],
        mermaid=mermaid,
        pr_summary=pr_summary,
        pr_review=app.config.get("LATEST_PR_REVIEW"),
        refresh_status=refresh_status,
        github_repository=app.config.get("GITHUB_REPOSITORY") or os.getenv("GITHUB_REPOSITORY", ""),
    )


@app.route("/api/summary")
def api_summary():
    summary, payload, snapshot, refresh_status = _analyze_current_repo()
    response = {
        "project_name": payload["project_name"],
        "modules": payload["modules"],
        "layers": snapshot["layers"],
        "dependency_edges": payload["dependency_edges"],
        "watch_status": refresh_status,
    }
    return jsonify(response)


@app.route("/api/mermaid")
def api_mermaid():
    summary, _, _, _ = _analyze_current_repo()
    return (build_mermaid_diagram(summary), 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/api/graph")
def api_graph():
  summary, _, _, _ = _analyze_current_repo()
  requested_layers = [item.strip() for item in request.args.get("layers", "").split(",") if item.strip()]
  depth_value = request.args.get("depth", "")
  try:
    max_depth = int(depth_value) if depth_value else None
  except ValueError:
    return jsonify({"error": "depth must be an integer"}), 400

  svg = build_svg_graph(summary, visible_layers=requested_layers or None, max_depth=max_depth)
  return jsonify({"svg": svg, "layers": requested_layers, "max_depth": max_depth})


@app.route("/api/module/<path:module_name>")
def api_module_details(module_name):
    summary, _, _, _ = _analyze_current_repo()
    normalized = module_name.replace('\\', '/').lstrip('/')
    target_name = normalized.rsplit('/', 1)[-1] if '/' in normalized else normalized
    module_data = None
    for item in summary.get('modules', []):
        item_name = str(item.get('name', ''))
        item_path = str(item.get('relative_path', '')).replace('\\', '/')
        if item_name == target_name or item_path == normalized or item_name.endswith('/' + normalized) or item_name.endswith(normalized):
            module_data = build_module_details(summary, item_name)
            break

    if module_data is None:
        return jsonify({"error": "module not found", "name": normalized}), 404
    return jsonify(module_data)


@app.route("/api/pr-comment", methods=["POST"])
def api_pr_comment():
    payload = request.get_json(silent=True) or {}
    module_name = str(payload.get("module_name") or "").strip()
    comment = str(payload.get("comment") or "").strip()

    if not module_name:
        return jsonify({"error": "module_name is required"}), 400

    summary, _, _, _ = _analyze_current_repo()
    details = build_module_details(summary, module_name)

    review_entry = {
        "module_name": module_name,
        "comment": comment or "Review accepted with no blocking issues.",
        "layer": details.get("layer", "unknown"),
        "dependencies": details.get("dependencies", []),
        "reverse_dependencies": details.get("reverse_dependencies", []),
    }

    return jsonify({"ok": True, "module_name": module_name, "comment": review_entry["comment"], "review": review_entry})


@app.route("/api/github/pr-comment", methods=["POST"])
def api_github_pr_comment():
    payload = request.get_json(silent=True) or {}
    repository = str(
        payload.get("repository")
        or app.config.get("GITHUB_REPOSITORY")
        or os.getenv("GITHUB_REPOSITORY")
        or ""
    ).strip()
    module_name = str(payload.get("module_name") or "").strip()
    comment = str(payload.get("comment") or "").strip()
    try:
        pr_number = int(payload.get("pr_number"))
    except (TypeError, ValueError):
        pr_number = 0

    if not repository or "/" not in repository:
        return jsonify({"error": "repository must be in owner/name format"}), 400
    if pr_number <= 0:
        return jsonify({"error": "pr_number must be a positive integer"}), 400
    if not module_name or not comment:
        return jsonify({"error": "module_name and comment are required"}), 400

    summary, _, _, _ = _analyze_current_repo()
    details = build_module_details(summary, module_name)
    review_body = (
        f"### Architecture Explorer review: `{module_name}`\n\n"
        f"{comment}\n\n"
        f"**Layer:** `{details.get('layer', 'unknown')}`  \n"
        f"**Dependencies:** {', '.join(details.get('dependencies', [])) or 'none'}  \n"
        f"**Reverse dependencies:** {', '.join(details.get('reverse_dependencies', [])) or 'none'}"
    )
    result, status = _post_github_issue_comment(repository, pr_number, review_body)
    if status >= 400:
        return jsonify({"error": result.get("error", "GitHub comment failed"), "repository": repository, "pr_number": pr_number}), status
    return jsonify({
        "ok": True,
        "repository": repository,
        "pr_number": pr_number,
        "module_name": module_name,
        "comment": comment,
        "github_comment": result,
    }), 201


@app.route("/api/pr-summary")
def api_pr_summary():
    summary, _, _, _ = _analyze_current_repo()
    result = render_pr_impact_summary(["app.py"], ["app.py", "architecture_explorer.py"], summary)
    return (result, 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/api/pr-review")
def api_pr_review():
    review = app.config.get("LATEST_PR_REVIEW")
    if not review:
        return jsonify({"error": "no pull-request review has been received"}), 404
    return jsonify(review)


@app.route("/api/watcher-status")
def api_watcher_status():
    watcher = app.config["WATCHER"]
    return jsonify(watcher.status())


@app.route("/api/refresh", methods=["POST", "GET"])
def api_refresh():
    watcher = app.config["WATCHER"]
    summary, snapshot = watcher.force_refresh()
    payload = build_dashboard_payload(summary)
    return jsonify({
        "project_name": payload["project_name"],
        "modules": payload["modules"],
        "layers": snapshot["layers"],
        "dependency_edges": payload["dependency_edges"],
        "watch_status": watcher.status(),
    })


@app.route("/api/github/pr-webhook", methods=["POST"])
def api_github_pr_webhook():
    raw_body = request.get_data(cache=True, as_text=False)
    signature = request.headers.get("X-Hub-Signature-256")
    secret = app.config.get("GITHUB_WEBHOOK_SECRET") or os.getenv("GITHUB_WEBHOOK_SECRET")
    if secret:
        app.config["GITHUB_WEBHOOK_SECRET"] = secret
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature or "", expected):
            return jsonify({"error": "invalid GitHub webhook signature"}), 401

    payload = request.get_json(silent=True) or {}
    pr_data = payload.get("pull_request") or {}
    repository = ((payload.get("repository") or {}).get("full_name") or app.config.get("GITHUB_REPOSITORY") or "").strip()
    pr_number = pr_data.get("number")
    changed_files, added_files, removed_files = ([], [], [])
    if repository and pr_number:
      changed_files, added_files, removed_files = _fetch_pr_file_changes(repository, int(pr_number))

    payload_changed_files = pr_data.get("changed_files") or []
    if not changed_files and isinstance(payload_changed_files, list):
      changed_files = payload_changed_files
      added_files = payload_changed_files

    base_files = payload.get("base_files") or []
    head_files = payload.get("head_files") or changed_files
    if not isinstance(base_files, list):
        base_files = []
    if not isinstance(head_files, list):
        head_files = changed_files

    if not base_files and not head_files and changed_files:
        base_files = []
        head_files = changed_files

    watcher = app.config["WATCHER"]
    summary, _ = watcher.scan()
    impact = analyze_pr_impact(base_files, head_files, summary)
    report = render_pr_impact_summary(base_files, head_files, summary)
    changed_names = [Path(item).name for item in changed_files]
    artifacts = build_pr_review_artifacts(summary, changed_names, [Path(item).name for item in removed_files])
    review = {
      "event": request.headers.get("X-GitHub-Event", "pull_request"),
      "action": payload.get("action", "unknown"),
      "repository": repository,
      "pr_number": pr_number,
      "title": pr_data.get("title"),
      "base_ref": (pr_data.get("base") or {}).get("ref"),
      "head_ref": (pr_data.get("head") or {}).get("ref"),
      "changed_files": changed_files,
      "diff_summary": {"base_files": base_files, "head_files": head_files},
      "summary": impact["summary"],
      "report": report,
      "artifacts": artifacts,
    }
    app.config["LATEST_PR_REVIEW"] = review

    return jsonify(review)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
