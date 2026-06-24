"""
Expose live landing-page aggregates to Jinja2 templates, computed from the DB
(never hardcoded) and cached per process since the served DB is static:

- `type_counts`       — per-organoid-type protocol counts (type-distribution chart)
- `grounding_buckets` — distribution of per-protocol grounding_rate across the
                        corpus in ten 10-point bins (the evidence-trust histogram)

Both render server-side as data tables (the no-JS fallback) and also feed the
Observable Plot charts on the landing page.
"""
from datasette import hookimpl

_CACHE = {}


async def _type_counts(db):
    rows = (
        await db.execute(
            "select organoid_type, count(*) as c from protocols "
            "where organoid_type is not null and trim(organoid_type) != '' "
            "group by organoid_type order by c desc, organoid_type"
        )
    ).rows
    return [{"type": r["organoid_type"], "count": r["c"]} for r in rows]


async def _grounding_buckets(db):
    # Bin grounding_rate (0.0–1.0) into ten 10-point bins; 100% lands in the
    # top bin. Protocols with a null rate (no extracted factors) are excluded.
    rows = (
        await db.execute(
            "select min(9, cast(grounding_rate * 10 as int)) as b, count(*) as c "
            "from protocols where grounding_rate is not null "
            "group by b"
        )
    ).rows
    counts = {int(r["b"]): r["c"] for r in rows}
    labels = ["0–10%", "10–20%", "20–30%", "30–40%", "40–50%",
              "50–60%", "60–70%", "70–80%", "80–90%", "90–100%"]
    return [{"bucket": i, "label": labels[i], "count": counts.get(i, 0)} for i in range(10)]


@hookimpl
def extra_template_vars(datasette):
    async def inner():
        if "type_counts" not in _CACHE:
            try:
                db = datasette.get_database("atlas")
                _CACHE["type_counts"] = await _type_counts(db)
                _CACHE["grounding_buckets"] = await _grounding_buckets(db)
            except Exception:
                # DB missing/empty or no protocols table — degrade gracefully.
                _CACHE["type_counts"] = []
                _CACHE["grounding_buckets"] = []
        return {
            "type_counts": _CACHE["type_counts"],
            "grounding_buckets": _CACHE.get("grounding_buckets", []),
        }

    return inner
