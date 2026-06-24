"""LIVE smoke test for the public Render deployment.

This is the detector for the gap in #164: test_public_deploy_contract.py validates the
*committed* exports/serve files, but nothing checks that the *served* site actually
matches. This file hits the live URL and compares.

IT IS NOT PART OF THE OFFLINE SUITE. Every test is skipped unless SMOKE_LIVE=1, so the
default `pytest -q` CI run stays fully offline (no network) and the offline guarantee in
the QA brief holds. Run it post-deploy or on a schedule:

    SMOKE_LIVE=1 pytest tests/test_public_deploy_smoke.py -v
    SMOKE_LIVE=1 PUBLIC_DEPLOY_URL=https://staging... pytest tests/test_public_deploy_smoke.py

URL source: docs/SUPERVISOR_HANDOFF.md ("Live public deployment"). Override with
PUBLIC_DEPLOY_URL.
"""

import json
import os
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("SMOKE_LIVE"),
    reason="live-deployment smoke test; set SMOKE_LIVE=1 to run (kept out of offline CI)",
)

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("PUBLIC_DEPLOY_URL", "https://organoid-protocol-atlas.onrender.com").rstrip("/")
UA = {"User-Agent": "opa-qa-smoke/0.1"}
TIMEOUT = 45


def _get(path: str):
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read()


@pytest.fixture(scope="module")
def committed():
    return json.loads((ROOT / "exports/public/manifest.json").read_text())


@pytest.fixture(scope="module")
def live():
    status, body = _get("/exports/public/manifest.json")
    assert status == 200, f"live manifest returned HTTP {status}"
    return json.loads(body)


def test_live_manifest_not_stale_vs_committed(live, committed):
    """The served corpus must be at least as fresh as master's committed manifest.
    Floor-bound (>=), not equality: the deploy may legitimately be AHEAD of this checkout,
    but it must never be BEHIND (which is the stale-deploy failure mode of #159)."""
    for key in ("n_papers",):
        assert live.get(key, 0) >= committed[key], (
            f"live manifest {key}={live.get(key)} is BEHIND master={committed[key]} — stale deploy"
        )
    for table in ("protocols", "reagents"):
        live_n = live.get("tables", {}).get(table, 0)
        master_n = committed["tables"][table]
        assert live_n >= master_n, (
            f"live tables.{table}={live_n} is BEHIND master={master_n} — stale deploy"
        )


def test_live_manifest_schema_version_matches(live, committed):
    """schema_version must match exactly — a mismatch means consumers may misparse."""
    assert live.get("schema_version") == committed["schema_version"], (
        f"live schema_version={live.get('schema_version')!r} != "
        f"master={committed['schema_version']!r}"
    )


@pytest.mark.parametrize("route", ["/", "/llms.txt", "/atlas/protocols.json", "/atlas/reagents.json"])
def test_live_public_routes_serve_non_empty(route):
    """Every promised public route must return 200 with a non-trivial body."""
    status, body = _get(route)
    assert status == 200, f"{route} returned HTTP {status}"
    assert len(body) > 50, f"{route} returned a suspiciously small body ({len(body)} bytes)"


def test_live_llms_txt_advertises_redistribution_terms():
    """The public llms.txt must keep the honesty/licensing note (the deployment's promise)."""
    status, body = _get("/llms.txt")
    assert status == 200
    assert b"does not redistribute" in body, "llms.txt lost its redistribution disclaimer"
