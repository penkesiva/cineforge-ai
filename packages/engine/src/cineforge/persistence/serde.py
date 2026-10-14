"""JSON (de)serialization helpers for contract models.

Some contract models expose ``computed_field`` properties (``ReviewFinding.blocking``,
``ReviewReport.passed``) that appear in ``model_dump`` output but are rejected on
re-validation because contract models use ``extra="forbid"``. Stored JSON must
therefore be dumped without computed fields and stripped of them on load.
"""

from __future__ import annotations

import types
import typing
from typing import Any, Union

from pydantic import BaseModel


def dump(model: BaseModel) -> dict[str, Any]:
    """JSON-safe dict without computed fields (safe to re-validate)."""
    return model.model_dump(mode="json", exclude_computed_fields=True)


def _model_types(annotation: Any) -> list[type[BaseModel]]:
    """Every BaseModel subclass nested in an annotation (Optional, list, dict values...)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    origin = typing.get_origin(annotation)
    if origin is None:
        return []
    args = typing.get_args(annotation)
    if origin in (Union, types.UnionType, list, tuple, set, frozenset, dict):
        found: list[type[BaseModel]] = []
        for arg in args:
            found.extend(_model_types(arg))
        return found
    if origin is typing.Annotated:
        return _model_types(args[0])
    return []


def strip_computed(model_cls: type[BaseModel], data: Any) -> Any:
    """Recursively drop computed-field keys so ``model_cls`` can validate ``data``."""
    if not isinstance(data, dict):
        return data
    computed = set(model_cls.model_computed_fields)
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key in computed:
            continue
        field = model_cls.model_fields.get(key)
        nested = _model_types(field.annotation) if field is not None else []
        if nested:
            value = _strip_value(nested, value)
        out[key] = value
    return out


def _strip_value(candidates: list[type[BaseModel]], value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_value(candidates, v) for v in value]
    if isinstance(value, dict):
        # A dict may be a nested model or a mapping of models; try model shape first.
        for cls in candidates:
            if set(value) & set(cls.model_fields):
                return strip_computed(cls, value)
        return {k: _strip_value(candidates, v) for k, v in value.items()}
    return value


def load[M: BaseModel](model_cls: type[M], data: Any) -> M:
    """Validate stored JSON into ``model_cls`` (tolerates dumped computed fields)."""
    return model_cls.model_validate(strip_computed(model_cls, data))
