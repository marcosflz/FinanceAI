"""Utilidades comunes de las herramientas del asistente."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from pydantic.fields import FieldInfo


class ToolError(Exception):
    pass


def _invoke(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Llama a un handler FastAPI resolviendo los ``Query(...)`` por defecto."""
    target = inspect.unwrap(fn)
    for name, param in inspect.signature(target).parameters.items():
        if name in kwargs:
            continue
        if isinstance(param.default, FieldInfo):
            kwargs[name] = param.default.default if param.default.default is not ... else None
    return fn(**kwargs)


def _safe(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Convierte errores de negocio en ``{"error": …}`` para el modelo."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except HTTPException as exc:
            return {"error": str(exc.detail)}
        except (ToolError, ValueError) as exc:
            return {"error": str(exc)}

    return wrapper
