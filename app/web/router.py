from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(tags=["web"])


def _base_context(request: Request) -> dict:
    settings = get_settings()
    return {
        "request": request,
        "asset_version": settings.app_version.replace(".", "-"),
    }


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("landing.html", _base_context(request))


@router.get("/portal/{screen}", response_class=HTMLResponse, include_in_schema=False)
def portal_screen(request: Request, screen: str) -> HTMLResponse:
    allowed = {
        "dashboard",
        "documents",
        "datasets",
        "training",
        "evaluation",
        "deploy",
        "audit",
    }
    selected = screen if screen in allowed else "dashboard"
    context = _base_context(request)
    context["screen"] = selected
    return templates.TemplateResponse("portal.html", context)

