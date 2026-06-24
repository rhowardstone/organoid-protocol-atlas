"""
Expose per-organoid-type protocol counts to Jinja2 templates as `type_counts`.

The landing page renders this server-side as a data table (the no-JS fallback
for the type-distribution chart) and also hands the same numbers to Observable
Plot. Computed live from the DB — never hardcoded — so it tracks the corpus as
it grows. Cached per process since the served DB is static for a deploy.
"""
from datasette import hookimpl

_CACHE = {}


@hookimpl
def extra_template_vars(datasette):
    async def inner():
        if "type_counts" not in _CACHE:
            try:
                db = datasette.get_database("atlas")
                rows = (
                    await db.execute(
                        "select organoid_type, count(*) as c from protocols "
                        "where organoid_type is not null and trim(organoid_type) != '' "
                        "group by organoid_type order by c desc, organoid_type"
                    )
                ).rows
                _CACHE["type_counts"] = [
                    {"type": r["organoid_type"], "count": r["c"]} for r in rows
                ]
            except Exception:
                # DB missing/empty or no protocols table — degrade gracefully.
                _CACHE["type_counts"] = []
        return {"type_counts": _CACHE["type_counts"]}

    return inner
