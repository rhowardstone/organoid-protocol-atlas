"""
/discover-data.json — evidence-based candidate-factor discovery.

Answers "how would one discover high-probability successful *new* protocols?" by
cross-type transfer: for each organoid type, find signaling factors that are core
in the most *similar* organoid systems but under-used in this one. These are
hypotheses (analysis tier), not validated recommendations.

Computed server-side directly against the DB (not via the row-capped HTTP API),
cached per process since the served DB is static for a deploy. Live from the
5,119-protocol corpus — never hardcoded.

Method:
  prevalence[type][factor] = (# distinct protocols of `type` using `factor`)
                             / (# distinct protocols of `type` with signaling)
  similarity(A,B)          = cosine of the two types' prevalence vectors
  top_factors(type)        = the type's signaling factors ranked by prevalence
                             (the established recipe backbone; thresholds are
                             rank-based, not an absolute cutoff, because real
                             corpus prevalence rarely exceeds 50% once canonical
                             variants are split)
  candidates(type)         = factors that are well-established (>= NEIGHBOR_ESTABLISHED)
                             in a similar type but under-used (< UNDERUSED) in this
                             one, scored by Σ similarity(type,S) * prevalence[S][factor]
                             over the top similar types S. Hypotheses, not advice.
"""
import math

from datasette import hookimpl, Response

_CACHE = {}

TOP_N = 15                      # how many top factors form the displayed recipe backbone
DISPLAY_FLOOR = 0.05           # don't show backbone factors rarer than 5%
NEIGHBOR_ESTABLISHED = 0.30    # factor counts as "established" in a neighbour at >= 30%
UNDERUSED_THRESHOLD = 0.10     # factor is "under-used" in the target at < 10%
POOL_MIN_PROTOCOLS = 5         # types below this are too small to anchor similarity
TOP_SIMILAR = 5                # number of neighbour types to borrow candidates from
MAX_CANDIDATES = 12


def _cosine(a, b):
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[c] * b[c] for c in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


async def _compute(datasette):
    if "data" in _CACHE:
        return _CACHE["data"]

    db = datasette.get_database("atlas")
    n_rows = (
        await db.execute(
            "select organoid_type as t, count(distinct pmcid) as n from reagents "
            "where kind='signaling' and organoid_type is not null and trim(organoid_type)!='' "
            "group by organoid_type"
        )
    ).rows
    n_by_type = {r["t"]: r["n"] for r in n_rows}

    f_rows = (
        await db.execute(
            "select organoid_type as t, canonical as c, count(distinct pmcid) as k from reagents "
            "where kind='signaling' and organoid_type is not null and trim(organoid_type)!='' "
            "and canonical is not null and trim(canonical)!='' "
            "group by organoid_type, canonical"
        )
    ).rows

    prev = {}   # prev[type][factor] = prevalence
    for r in f_rows:
        n = n_by_type.get(r["t"], 0)
        if n:
            prev.setdefault(r["t"], {})[r["c"]] = r["k"] / n

    pool = [t for t, n in n_by_type.items() if n >= POOL_MIN_PROTOCOLS]
    by_type = {}

    for t, n in n_by_type.items():
        vt = prev.get(t, {})
        top_factors = sorted(
            ({"factor": c, "prevalence": round(p, 3), "k": round(p * n)}
             for c, p in vt.items() if p >= DISPLAY_FLOOR),
            key=lambda x: -x["prevalence"],
        )[:TOP_N]
        sims = sorted(
            ((s, _cosine(vt, prev.get(s, {}))) for s in pool if s != t),
            key=lambda x: -x[1],
        )
        top_sims = [(s, sim) for s, sim in sims[:TOP_SIMILAR] if sim > 0]

        scores, support = {}, {}
        for s, sim in top_sims:
            for c, ps in prev.get(s, {}).items():
                if ps < NEIGHBOR_ESTABLISHED:        # only borrow factors established in a neighbour
                    continue
                if vt.get(c, 0.0) >= UNDERUSED_THRESHOLD:   # already used here
                    continue
                scores[c] = scores.get(c, 0.0) + sim * ps
                support.setdefault(c, []).append(
                    {"type": s, "prevalence": round(ps, 3), "similarity": round(sim, 3)}
                )
        candidates = sorted(
            ({"factor": c,
              "score": round(sc, 3),
              "prevalence_here": round(vt.get(c, 0.0), 3),
              "support": sorted(support[c], key=lambda x: -x["prevalence"])[:4]}
             for c, sc in scores.items()),
            key=lambda x: -x["score"],
        )[:MAX_CANDIDATES]

        by_type[t] = {
            "n_protocols": n,
            "top_factors": top_factors,
            "similar_types": [{"type": s, "similarity": round(sim, 3)} for s, sim in top_sims],
            "candidates": candidates,
        }

    result = {
        "types": sorted(by_type.keys()),
        "by_type": by_type,
        "params": {
            "neighbor_established": NEIGHBOR_ESTABLISHED,
            "underused_threshold": UNDERUSED_THRESHOLD,
            "top_similar": TOP_SIMILAR,
            "denominator": "protocols of the type that have >=1 signaling factor",
        },
    }
    _CACHE["data"] = result
    return result


async def route_discover_data(datasette, request):
    try:
        return Response.json(await _compute(datasette))
    except Exception as e:   # DB missing/empty — degrade to an empty payload
        return Response.json({"types": [], "by_type": {}, "error": str(e)})


@hookimpl
def register_routes():
    return [(r"^/discover-data\.json$", route_discover_data)]
