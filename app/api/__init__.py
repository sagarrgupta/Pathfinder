"""HTTP API package.

Everything a browser or external client can hit lives here. The router
is defined in `routes.py` and mounted in `app.main` under
`settings.API_V1_PREFIX`. This package should stay thin — real work
happens in `app.nodes`, `app.tools`, and `app.adapters`. The routes only:

- validate inputs using `app.schemas.models`,
- call into the workflow / graph DB,
- and shape the result back into a Pydantic response model.
"""
