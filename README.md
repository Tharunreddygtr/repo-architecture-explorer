# Repo Architecture Explorer

Repo Architecture Explorer is a standalone architecture intelligence service for developers, reviewers, and platform teams. It scans a repository, derives architecture from source code, renders HLD and LLD views, explains dependency impact, and connects selected architecture components to GitHub pull-request review.

The service is intentionally separate from the application repository it analyzes. The default implementation uses Python AST analysis and Flask, so it can run locally, in CI, or as a small internal review service.

## Capabilities

### Repository analysis

- Recursively scans Python source files.
- Excludes common generated and dependency directories: `.git`, `.venv`, `venv`, `node_modules`, `dist`, `build`, and `__pycache__`.
- Extracts module names and paths.
- Extracts classes, synchronous functions, asynchronous functions, imports, and call expressions.
- Builds dependency edges between discovered modules.
- Normalizes Windows and POSIX paths for cross-platform use.
- Classifies modules heuristically into `entry`, `service`, `data`, and `infra` layers based on file names.

### HLD and LLD documentation

- Generates High Level Design Markdown.
- Generates Low Level Design Markdown.
- Generates HTML HLD and LLD fragments for the dashboard.
- Produces a layered project snapshot for downstream tooling.
- Lists entry points and major dependency flow.

### Interactive architecture explorer

- Renders an SVG architecture graph with clickable components.
- Shows hover labels and layer metadata for nodes.
- Opens component details on demand, including classes, functions, imports, dependencies, and reverse dependencies.
- Supports nested drilldown by following dependency and reverse-dependency buttons.
- Supports zoom in, zoom out, and reset controls.
- Filters the graph by layer visibility.
- Limits the graph by dependency depth from detected entry modules.

### Mermaid and graph output

- Generates Mermaid `graph TD` output for documentation and external rendering.
- Generates filtered SVG graph output for browser clients.
- Supports PR coloring when callers provide added and removed component names: additions are green and deletions are red.

### Pull-request impact analysis

- Compares base and head file lists.
- Identifies changed and removed files.
- Maps changed files to analyzed modules.
- Reports directly impacted dependency edges.
- Produces an architecture review summary with HLD impact, LLD impact, risk, and reviewer guidance.

### Repository refresh and watching

- Tracks repository file state through `RepoWatcher`.
- Detects when the analyzed repository has changed.
- Refreshes the analysis snapshot on demand.
- Exposes watcher status and refresh APIs.

### GitHub integration

- Validates GitHub webhook signatures with `X-Hub-Signature-256`.
- Automatically retrieves the real changed-file list from the GitHub pull-request API when `GITHUB_TOKEN` is configured.
- Automatically generates and stores the latest PR review bundle when a pull-request webhook arrives.
- Shows the latest PR HLD diagram, dependency-impact diagram, layer diagram, Mermaid graph, HLD, and LLD in the dashboard.
- Exposes the stored review bundle through `/api/pr-review` for external tooling.
- Posts a real issue-style pull-request comment through the GitHub REST API.
- Enriches comments with the selected module, layer, dependencies, and reverse dependencies.
- Returns explicit errors when the token, repository, PR number, or comment data is missing.

## Architecture

```text
Repository source
        |
        v
architecture_explorer.py  ->  summary, layers, dependency graph, HLD/LLD, SVG/Mermaid
        |
        +--> pr_impact.py   ->  changed files, blast radius, review summary
        |
        +--> repo_watcher.py -> snapshot state, stale detection, refresh
        |
        v
app.py / Flask
        |
        +--> browser dashboard
        +--> JSON APIs
        +--> GitHub webhook and PR comment integration
```

## Project structure

```text
repo-architecture-explorer/
├── app.py                         Flask dashboard and API routes
├── architecture_explorer.py       AST analysis and architecture rendering
├── pr_impact.py                   Pull-request impact analysis
├── repo_watcher.py                File-state tracking and refresh
├── requirements.txt               Runtime and test dependencies
├── Dockerfile                     Gunicorn container packaging
├── .env.example                   Environment variable template
├── self_analysis.py               Reproducible self-analysis report generator
├── docs/self-analysis.md          Checked-in HLD/LLD report for this repository
├── examples/                      Integration and API sample templates
└── tests/test_pr_impact.py        Regression and integration tests
```

## Local setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open the dashboard at <http://localhost:8000/>.

`.env.example` is a configuration template. The local Flask command reads process environment variables; it does not parse a `.env` file automatically. Set variables in the VS Code launch configuration, PowerShell session, or deployment environment before running `python app.py`. Docker can load them directly with `--env-file`.

The service analyzes the directory containing `app.py` by default. To analyze another repository, construct `RepoWatcher` with that repository path or adapt the application configuration before deployment.

## Configuration

Copy [.env.example](.env.example) and set values for the deployment.

| Variable | Required for | Description |
| --- | --- | --- |
| `GITHUB_WEBHOOK_SECRET` | Signed webhooks | Secret used to validate `X-Hub-Signature-256`. |
| `GITHUB_TOKEN` | Real PR comments | GitHub token with permission to write pull-request issue comments. |
| `GITHUB_REPOSITORY` | Dashboard defaults | Repository in `owner/name` format. The request body can override it. |
| `AUTO_COMMENT_ON_PR` | Automatic PR diagrams | Set to `true` to post Mermaid diagrams and HLD/LLD text automatically on PR events. |
| `PORT` | Container/runtime | Port used by the deployment command. |

Never commit real tokens or webhook secrets. Use a secret manager or CI/CD secret store in deployed environments.

## Dashboard workflows

1. Open the HLD graph.
2. Select or clear `entry`, `service`, `data`, and `infra` layers.
3. Optionally enter a maximum dependency depth and apply the filter.
4. Hover a component to identify it, then click it for details.
5. Follow dependency or reverse-dependency buttons for nested drilldown.
6. Enter a repository, pull-request number, and comment to post a real GitHub PR comment for the selected component.

The dashboard uses `/api/graph` to refresh the SVG graph without reloading the page.

## Self-analysis report

The repository runs the explorer against itself. The checked-in result is available at [docs/self-analysis.md](docs/self-analysis.md), including the current HLD, LLD, layers, internal dependency graph, and component drilldown.

Regenerate the report from the repository root with:

```powershell
python self_analysis.py > docs/self-analysis.md
```

## Generate an HTML PR report

The local PR analyzer can generate a browser-ready report containing the inline HLD SVG, Mermaid impact diagrams, and architecture review summary:

```powershell
python local_pr_review.py <base> <head> --html-output docs/changes.html
```

The HTML report can be opened directly from the filesystem. Mermaid diagrams use the Mermaid browser bundle from jsDelivr; the HLD SVG is embedded in the page. Markdown output remains available with `--output`.

GitHub Actions can run the same command for every pull request and upload `changes.html` as a downloadable workflow artifact.

On a pull request, open the workflow run and download the `pr-architecture-report` artifact to inspect the generated `changes.html` report.

## Publish the report to GitHub Pages

The `Publish architecture report to Pages` workflow publishes the latest report at the repository's GitHub Pages URL whenever `main` changes. Enable **Settings > Pages > Build and deployment > Source: GitHub Actions** once, then open the `page_url` shown in the workflow run's deployment environment.

For a manual report, run the workflow from the Actions tab and optionally provide `base` and `head` commit, branch, or tag values. Pull requests continue to receive the downloadable artifact because deploying untrusted pull-request code directly to the shared Pages site would overwrite the published report.

## API reference

### `GET /api/summary`

Returns the project name, analyzed modules, layer groups, dependency edges, and watcher status.

### `GET /api/mermaid`

Returns a plain-text Mermaid dependency graph.

### `GET /api/graph`

Returns a JSON object containing filtered SVG.

Query parameters:

- `layers`: comma-separated values from `entry`, `service`, `data`, and `infra`.
- `depth`: non-negative dependency depth from detected entry modules.
- `focus`: optional module name. When present, the selected module becomes the graph root and downstream dependencies are rendered automatically; the default focused depth is `2`.

Example:

```text
GET /api/graph?layers=entry,service&depth=1
```

When a user clicks a node in the dashboard, it uses the focused form automatically:

```text
GET /api/graph?focus=app.py&depth=2
```

### `GET /api/module/<module-name>`

Returns component details, including classes, functions, imports, dependencies, reverse dependencies, and nested detail references. Module paths such as `app/service.py` are accepted.

### `POST /api/pr-comment`

Creates a local structured review record. It does not call GitHub.

```json
{
  "module_name": "service.py",
  "comment": "Please verify the downstream dependency."
}
```

### `POST /api/github/pr-comment`

Posts a real comment to the pull request through GitHub's issue-comment API. It requires `GITHUB_TOKEN` and a repository in `owner/name` format.

```json
{
  "repository": "owner/repository",
  "pr_number": 42,
  "module_name": "service.py",
  "comment": "Please verify the downstream dependency."
}
```

### `GET /api/pr-summary`

Returns a text architecture review summary for the configured sample file comparison used by the dashboard.

### `GET /api/watcher-status`

Returns watcher state, repository path, module count, and last refresh information.

### `GET|POST /api/refresh`

Forces a repository rescan and returns the refreshed project snapshot.

### `POST /api/github/pr-webhook`

Validates a GitHub pull-request webhook, retrieves changed files, generates the diagram-first review bundle, stores it for the dashboard, and returns the complete architecture review. Send `X-GitHub-Event: pull_request` and a matching `X-Hub-Signature-256` header when `GITHUB_WEBHOOK_SECRET` is configured. `GITHUB_TOKEN` allows the service to retrieve the actual changed filenames because GitHub's native `changed_files` field is only a count.

### `GET /api/pr-review`

Returns the latest automatically generated pull-request review bundle, including `hld_svg`, `dependency_mermaid`, `layer_mermaid`, `impact_mermaid`, `hld_markdown`, and `lld_markdown`. It returns `404` until a webhook has been received.

## GitHub pull-request setup

1. Deploy this service at a reachable HTTPS URL.
2. Configure `GITHUB_WEBHOOK_SECRET` in the service and in the GitHub webhook.
3. Create a GitHub webhook pointing to `/api/github/pr-webhook`.
4. Select the `Pull requests` event and JSON content type.
5. Configure `GITHUB_TOKEN` and `GITHUB_REPOSITORY` so the service can fetch PR file names and support dashboard-originated comments.
6. Give the token only the repository permissions needed to read pull requests and write pull-request comments.

The webhook automatically generates the architecture artifacts and makes them visible in the dashboard. Set `AUTO_COMMENT_ON_PR=true` to post a GitHub PR comment containing Mermaid dependency, layer, and impact diagrams plus HLD/LLD review text. The SVG HLD remains available in the dashboard and generated report because GitHub comments cannot safely embed a local repository SVG asset.

With GitHub CLI authenticated, the repository webhook can be created from PowerShell:

```powershell
cd C:\MEDPLUS-HRMS\repo-architecture-explorer
.\examples\create-github-webhook.ps1 -BaseUrl "https://architecture.example.com"
```

The script prompts for the webhook secret in the terminal and configures the `pull_request` event. Set the same secret as `GITHUB_WEBHOOK_SECRET` in the deployed service before creating the hook. Do not put the secret in the command line or commit it.

## Sample templates

Copyable examples are in [examples](examples):

- [environment.template](examples/environment.template) - deployment configuration checklist.
- [graph-filter-request.txt](examples/graph-filter-request.txt) - filtered graph request.
- [github-pr-webhook.json](examples/github-pr-webhook.json) - webhook payload shape for local testing.
- [github-pr-comment.json](examples/github-pr-comment.json) - selected-component comment request.
- [create-github-webhook.ps1](examples/create-github-webhook.ps1) - GitHub CLI webhook creation script.
- [github-actions-architecture-review.yml](examples/github-actions-architecture-review.yml) - CI workflow template for calling the webhook.

## Docker

```powershell
docker build -t repo-architecture-explorer .
docker run --rm -p 8000:8000 --env-file .env -e PORT=8000 repo-architecture-explorer
```

## Testing

Run the complete regression suite:

```powershell
python -m pytest -q
```

## Local commit PR review

You can test the PR-review capability locally before configuring a GitHub webhook. The command accepts any local Git branch, tag, or commit ref. It compares complete Git trees, detects modified/added/deleted files, analyzes the selected head commit snapshot, and generates HLD, dependency-impact, and layer diagrams.

```powershell
python local_pr_review.py <base-commit> <head-commit> --output .\docs\local-pr-review.md
```

When `--output` is provided, the command also writes a neighboring `.svg` asset for the HLD and inserts a Markdown image link, so the HLD renders in GitHub and VS Code instead of appearing as SVG source text. The Mermaid diagrams render in GitHub and Mermaid-enabled Markdown previews.

Example using the repository's published commits:

```powershell
python local_pr_review.py 57ba752 d59f4c7 --output .\docs\local-pr-review.md
```

For a real feature branch after fetching it locally:

```powershell
git fetch origin main feature/my-change
python local_pr_review.py origin/main origin/feature/my-change --output .\docs\feature-my-change-review.md
```

The command uses the same `analyze_pr_impact`, `build_pr_review_artifacts`, and report rendering capabilities used by the webhook. It does not contact GitHub and does not require a token.

The suite covers AST extraction, layer classification, dependency mapping, HLD-first rendering, SVG PR colors, graph filters, watcher behavior, webhook signature validation, and GitHub comment request construction.

## Current boundaries

- The analyzer currently scans Python source files; JavaScript, Java, and other languages need additional parsers.
- Layer classification is filename-based and should be treated as an initial architectural heuristic.
- The current GitHub comment integration posts issue-style PR comments, not line-level review comments.
- A webhook payload normally needs an external step to resolve exact base/head file lists; the example payload includes those lists for deterministic local testing.

This service is intentionally decoupled from the application repository so it can support developer understanding, architecture documentation, and pull-request review workflows across multiple repositories.
