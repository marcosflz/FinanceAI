"""
Aplicación FastAPI de financial-tools.

Solo se exponen las rutas ``/api/v3`` (sesión + CSRF) y ``/api/v3/health``.
Las rutas legacy sin autenticación (``/api/documents``, ``/api/pockets``,
``/api/v2``, ``/api/imports``…) se han eliminado: el frontend proxya todo
``/api/*`` al backend, así que cualquier ruta sin ``require_user`` quedaba
expuesta públicamente.
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api_v3 import health_router, protected_router as v3_protected_router
from .api_v3 import public_router as v3_public_router
from .api_v3_data import router as v3_data_router
from .auth.dependencies import require_csrf, require_user
from .config import get_settings
from .db.session import init_db
from .imports_api import router as imports_router
from .v2_api import router as v2_router

_settings = get_settings()
app = FastAPI(
    title="Financial Tools API",
    version="0.3.0",
    # En producción no se exponen docs/OpenAPI sin autenticación.
    docs_url=None if _settings.is_production else "/docs",
    redoc_url=None if _settings.is_production else "/redoc",
    openapi_url=None if _settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_protected = [Depends(require_user), Depends(require_csrf)]

app.include_router(v3_public_router)
app.include_router(v3_protected_router)
app.include_router(v3_data_router)
app.include_router(health_router)
app.include_router(v2_router, prefix="/api/v3", dependencies=_protected)
app.include_router(imports_router, prefix="/api/v3/imports", dependencies=_protected)


@app.on_event("startup")
def startup():
    init_db()
    try:
        from .v2_api import cleanup_stale_jobs

        cleanup_stale_jobs()
    except Exception:
        pass  # no crítico
