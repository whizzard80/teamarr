"""Templates API endpoints."""

import json
import logging

from fastapi import APIRouter, HTTPException, status

from teamarr.api.models import (
    TemplateCreate,
    TemplateFullResponse,
    TemplateResponse,
    TemplateUpdate,
)
from teamarr.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

# JSON fields that need serialization from Pydantic models to strings
_JSON_FIELDS = {
    "xmltv_flags",
    "xmltv_video",
    "xmltv_categories",
    "pregame_periods",
    "pregame_fallback",
    "postgame_periods",
    "postgame_fallback",
    "postgame_conditional",
    "idle_content",
    "idle_conditional",
    "idle_offseason",
    "conditional_descriptions",
}


def _pydantic_to_plain(key: str, value):
    """Convert Pydantic model field to plain Python type for database layer.

    The database layer handles its own JSON serialization for known fields.
    This only converts Pydantic sub-models to dicts/lists.
    """
    if key in _JSON_FIELDS and value is not None:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        elif isinstance(value, list):
            return [v.model_dump() if hasattr(v, "model_dump") else v for v in value]
    return value


def _parse_json_fields(row: dict) -> dict:
    """Parse JSON string fields into Python objects for API response."""
    result = dict(row)
    for field in _JSON_FIELDS:
        if field in result and result[field]:
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return result


@router.get("/templates", response_model=list[TemplateResponse])
def list_templates():
    """List all templates with usage counts."""
    from teamarr.database.templates import list_templates_with_counts

    with get_db() as conn:
        return list_templates_with_counts(conn)


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
def create_template(template: TemplateCreate):
    """Create a new template."""
    from teamarr.database.templates import create_template as db_create

    # Convert Pydantic models to plain types for database layer
    data = template.model_dump()
    name = data.pop("name")
    template_type = data.pop("template_type", "team")

    # Convert Pydantic sub-models to plain dicts
    kwargs = {}
    for k, v in data.items():
        if v is not None:
            kwargs[k] = _pydantic_to_plain(k, getattr(template, k, v))

    with get_db() as conn:
        try:
            template_id = db_create(conn, name=name, template_type=template_type, **kwargs)
            from teamarr.database.templates import get_template_raw

            return get_template_raw(conn, template_id)
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Template with this name already exists",
                ) from None
            raise


@router.get("/templates/{template_id}", response_model=TemplateFullResponse)
def get_template(template_id: int):
    """Get a template by ID with all JSON fields parsed."""
    from dataclasses import asdict

    from teamarr.database.templates import get_template as db_get

    with get_db() as conn:
        template = db_get(conn, template_id)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        # Template dataclass already has parsed JSON fields
        return asdict(template)


@router.put("/templates/{template_id}", response_model=TemplateResponse)
def update_template(template_id: int, template: TemplateUpdate):
    """Update a template."""
    from teamarr.database.templates import update_template as db_update

    updates = {k: v for k, v in template.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    # Convert Pydantic sub-models to plain types for database layer
    kwargs = {k: _pydantic_to_plain(k, getattr(template, k, v)) for k, v in updates.items()}

    with get_db() as conn:
        if not db_update(conn, template_id, **kwargs):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Template not found"
            )
        logger.info("[UPDATED] Template id=%d fields=%s", template_id, list(updates.keys()))
        from teamarr.database.templates import get_template_raw

        return get_template_raw(conn, template_id)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: int):
    """Delete a template."""
    from teamarr.database.templates import delete_template as db_delete

    with get_db() as conn:
        if not db_delete(conn, template_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
