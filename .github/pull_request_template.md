## Proposed Change

<!-- Describe the changes proposed in this pull request and the rationale behind them. -->

### Upstream Dependency

<!--
If this PR depends on a gli4py PR or branch to pass upstream tests, specify it below in order to ensure that tests run against the correct version of gli4py
Examples:
  Depends-on: HarvsG/gli4py#<PR_NUMBER>
  gli4py: <branch-name>
-->

---

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Code quality / maintenance / refactoring

---

## Checklist

- [ ] The code follows the project style guidelines (`uv run pre-commit run --all-files` passes).
- [ ] New or modified code is covered by tests (`uv run pytest --cov` passes with >=98% coverage).
- [ ] Type annotations are added and `uv run mypy custom_components/glinet tests` passes.
- [ ] If this PR depends on a `gli4py` PR:
  - [ ] The linked `gli4py` PR is referenced above.
  - [ ] The `Pytest (Upstream gli4py)` CI check passes.
  - [ ] Before merging: `gli4py` is released on PyPI, and `manifest.json` + `pyproject.toml` are updated to the released version so `Pytest (Pinned gli4py)` passes.
