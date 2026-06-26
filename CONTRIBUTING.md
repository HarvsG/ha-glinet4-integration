# Contributing

## Running the tests

```bash
scripts/test                        # whole suite, across every router profile
scripts/test tests/test_sensor.py   # a single module
scripts/test -k uptime              # a single test by keyword
```

`scripts/test` runs `pytest` in an ephemeral [uv](https://docs.astral.sh/uv/)
environment with the pinned test dependencies, so it needs no project sync or
lockfile. CI (`.github/workflows/pytest.yml`) runs the same command with
coverage.

The pre-commit hooks (ruff, mypy, pylint, codespell, prettier) run via
`uv run`; install them with `uvx pre-commit install`.

## The dynamic profile model

The suite is **profile-driven**. Every directory under `tests/fixtures/` that
contains a `profile.json` is a "profile": a router model + firmware plus the API
responses captured from it. `tests/conftest.py` discovers every profile and
parametrizes the `profile` fixture over it, so **each test runs once per
profile** (its node id gains a `[<profile-id>]` suffix), and the snapshot tests
keep a separate snapshot per profile.

```
tests/fixtures/
  mt6000/                # the real, sanitised capture (Flint 2)
  mt6000_no_wireguard/   # derived edge profile
  mt6000_no_tailscale/   # derived edge profile
  mt3000_beryl_ax/       # derived: a different, smaller model
  wifi7_mlo_client/      # derived: reproduces a real interface-index crash
```

Each `profile.json` declares the model/firmware, capability flags
(`has_wireguard`, `has_tailscale`, …) and `expected` counts. Tests read their
expectations from the manifest instead of hard-coding values, and
feature-specific tests (the WireGuard/Tailscale switches) are skipped for
profiles that lack the feature.

`build_mock_api` in `tests/conftest.py` backs an `AsyncMock` GL-iNet client with
a profile's fixtures, coercing any **omitted** endpoint to the type the real
client returns (`[]` / `{}` / `False`), so a feature-absent profile exercises
the real "feature absent" code path rather than a truthy mock.

## Adding a router profile

### From real hardware (preferred)

```bash
GLINET_PASSWORD=... scripts/capture-fixtures \
    --host http://192.168.8.1 --username root --profile-id flint3
```

This calls only read-only endpoints (no router state is changed),
deterministically sanitises the responses (MACs, IPs, SSIDs, hostnames and
secrets), and writes `tests/fixtures/flint3/`. The whole suite then runs against
it with **no code changes**. Generate the snapshots for the new profile with
`scripts/test --snapshot-update` and review the diff. Fill in the `semantic`
block of the new `profile.json` with a couple of stable values to assert.

The sanitiser is covered by `tests/test_capture_fixtures.py`, which fails if a
real MAC, IP or secret could survive into a committed fixture.

### Synthetic edge profiles

The derived profiles are generated from `mt6000` by
`scripts/synthesize_profiles.py`; re-run it after changing the base capture or
to add a new edge case. They are regression guards, not ground truth — replace
them with real captures when you have the hardware.

## Snapshots

`tests/test_snapshots.py` snapshots each platform's entity-registry entries and
states per profile via Home Assistant's `snapshot_platform`. The clock is frozen
so the uptime sensor's derived boot timestamp is deterministic.

```bash
scripts/test tests/test_snapshots.py --snapshot-update   # after intentional changes
```

CI never passes `--snapshot-update`, so any drift in the committed
`tests/snapshots/*.ambr` fails the build — review snapshot diffs the same way you
review code.

## Bumping the Home Assistant version

`pytest-homeassistant-custom-component` pins an exact HA core version
(`0.13.313` → HA 2026.2.0). When you target a newer HA, bump it **and**
`homeassistant-stubs` in `pyproject.toml` in lockstep (uv resolves the `dev` and
`test` groups together), then regenerate the snapshots — expect a sizeable but
legitimate `.ambr` diff as HA's internal entity/state fields change.
