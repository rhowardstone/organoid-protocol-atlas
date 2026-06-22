"""
Redirect raw Datasette table/database/query pages to /explore for human browsers.
JSON API calls (?_shape=, .json, .csv, Accept: application/json) pass through
so the /explore page can still fetch data from the same endpoints.
"""
import functools
from datasette import hookimpl

# Paths that should redirect HTML browsers to /explore
_HTML_BLOCK = {
    "/atlas",
    "/atlas/protocols",
    "/atlas/reagents",
    "/atlas/signaling_by_type",
    "/atlas/compare_reagent",
    "/atlas/grounding_by_protocol",
}


def _is_api(scope):
    """Return True if this looks like a JSON/CSV API request, not a browser."""
    qs = scope.get("query_string", b"").decode()
    headers = dict(scope.get("headers", []))
    accept = headers.get(b"accept", b"").decode()
    path = scope.get("path", "")
    return (
        "_shape=" in qs
        or "_format=" in qs
        or "application/json" in accept
        or path.endswith(".json")
        or path.endswith(".csv")
    )


@hookimpl
def asgi_wrapper(datasette):
    def wrap(app):
        @functools.wraps(app)
        async def middleware(scope, receive, send):
            if scope.get("type") == "http":
                path = scope.get("path", "").rstrip("/") or "/"
                if path in _HTML_BLOCK and not _is_api(scope):
                    await send({
                        "type": "http.response.start",
                        "status": 302,
                        "headers": [[b"location", b"/explore"]],
                    })
                    await send({"type": "http.response.body", "body": b""})
                    return
            await app(scope, receive, send)
        return middleware
    return wrap
