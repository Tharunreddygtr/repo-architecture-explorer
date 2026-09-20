# Local Architecture PR Review: 7b7b557043b940185c405fdfff7cf346815aed10 -> a0295c156778159c4e169aaa9f609dfa7e2b21ff

- Base commit: `7b7b557043b940185c405fdfff7cf346815aed10`
- Head commit: `a0295c156778159c4e169aaa9f609dfa7e2b21ff`
- Base tree files: 26
- Head tree files: 26
- Git diff paths: .github/workflows/architecture-pr-check.yml, .github/workflows/publish-architecture-pages.yml, README.md, examples/capacity_service.py, generate_architecture_md.py, local_pr_review.py, tests/test_capacity_service.py
- Changed files: .github/workflows/publish-architecture-pages.yml, README.md, examples/capacity_service.py, local_pr_review.py, tests/test_capacity_service.py
- Removed files: .github/workflows/architecture-pr-check.yml, generate_architecture_md.py
- Impact summary: {'total_changed': 5, 'total_removed': 2, 'total_impacted': 7}

## HLD Diagram

![PR HLD diagram](changes.svg)

## Dependency Impact Diagram

```mermaid
graph TD
    local_pr_review_py[local_pr_review.py]
    architecture_explorer_py[architecture_explorer.py]
    local_pr_review_py --> architecture_explorer_py
    pr_impact_py[pr_impact.py]
    local_pr_review_py --> pr_impact_py
    test_capacity_service_py[test_capacity_service.py]
    capacity_service_py[capacity_service.py]
    test_capacity_service_py --> capacity_service_py
    test_pr_impact_py[test_pr_impact.py]
    test_pr_impact_py --> local_pr_review_py
```

## Layer Diagram

```mermaid
graph LR
    entry[Entry Layer]
    app_py[app.py]
    entry --> app_py
    service[Service Layer]
    capacity_service_py[capacity_service.py]
    service --> capacity_service_py
    test_capacity_service_py[test_capacity_service.py]
    service --> test_capacity_service_py
    data[Data Layer]
    repo_watcher_py[repo_watcher.py]
    data --> repo_watcher_py
    infra[Infra Layer]
    architecture_explorer_py[architecture_explorer.py]
    infra --> architecture_explorer_py
    local_pr_review_py[local_pr_review.py]
    infra --> local_pr_review_py
    pr_impact_py[pr_impact.py]
    infra --> pr_impact_py
    self_analysis_py[self_analysis.py]
    infra --> self_analysis_py
    test_architecture_explorer_py[test_architecture_explorer.py]
    infra --> test_architecture_explorer_py
    test_pr_impact_py[test_pr_impact.py]
    infra --> test_pr_impact_py
```

## Architecture Review

# Architecture Review Summary

## HLD Impact
- Changed files: .github/workflows/publish-architecture-pages.yml, README.md, examples/capacity_service.py, local_pr_review.py, tests/test_capacity_service.py
- Components affected: capacity_service.py, local_pr_review.py, local_pr_review.py -> architecture_explorer.py, local_pr_review.py -> pr_impact.py, test_capacity_service.py, test_capacity_service.py -> capacity_service.py, test_pr_impact.py -> local_pr_review.py
- Risk: High
- Architectural note: review dependency boundaries and service entry points before merge.

## LLD Impact
- Changed implementation blocks:
- capacity_service.py | classes: CapacityService | functions: calculate_capacity
- local_pr_review.py | classes: none | functions: _git_diff_stats, _categorize_paths, _python_symbols, _changed_python_symbols, render_html_report, _git_files, _git_value, _git_diff_status, _materialize_commit, run
- test_capacity_service.py | classes: none | functions: test_calculate_capacity_does_not_return_negative_values

## Reviewer Guidance
- Confirm the change is limited to the intended layer.
- Validate downstream calls and imports for blast radius.
- Check whether a shared component or service is now coupled to the modified module.
