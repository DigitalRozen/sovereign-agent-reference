"""Server-rendered UI and a small JSON API, all under /agent."""

import secrets
import time
from pathlib import Path
from urllib.parse import quote

import anyio
import httpx
import psycopg
from fastapi import APIRouter, Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from psycopg.rows import dict_row
from pydantic import BaseModel

from .agent import Run, run_agent
from .config import settings
from .oidc import TokenVerifier, User, exchange_code, login_request

COOKIE = "agent_sid"

app = FastAPI(title="agent-api", docs_url=None, redoc_url=None, openapi_url=None)
router = APIRouter(prefix="/agent")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
verifier = TokenVerifier(settings)

# In-memory state: fine for a single-replica demo, documented as a limitation.
sessions: dict[str, User] = {}
pending_logins: dict[str, str] = {}  # state -> PKCE verifier
runs: dict[str, Run] = {}


def session_user(request: Request) -> User | None:
    user = sessions.get(request.cookies.get(COOKIE, ""))
    if user and user.expires_at > time.time() + 5:
        return user
    return None


def require_user(request: Request) -> User:
    user = session_user(request)
    if user is None:
        raise HTTPException(303, headers={"Location": "/agent/login"})
    return user


async def bearer_user(authorization: str | None = Header(default=None)) -> User:
    token = (authorization or "").removeprefix("Bearer ").strip()
    user = await anyio.to_thread.run_sync(verifier.user, token) if token else None
    if user is None:
        raise HTTPException(401, "invalid or missing token")
    return user


def render(request: Request, name: str, user: User | None, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"user": user, **context})


async def query(dsn: str, sql: str, params: tuple = ()) -> list[dict]:
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as conn:
        return await (await conn.execute(sql, params)).fetchall()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    user = session_user(request)
    mine = [r for r in runs.values() if user and r.username == user.username][-10:]
    return render(request, "index.html", user, runs=reversed(mine), model=settings.model)


@router.get("/login")
def login():
    login = login_request(settings)
    pending_logins[login.state] = login.verifier
    return RedirectResponse(login.url, status_code=303)


@router.get("/callback")
async def callback(code: str = "", state: str = ""):
    verifier_for_state = pending_logins.pop(state, None)
    if not code or verifier_for_state is None:
        raise HTTPException(400, "unknown or expired login attempt")
    token = await exchange_code(settings, code, verifier_for_state)
    user = await anyio.to_thread.run_sync(verifier.user, token)
    if user is None:
        raise HTTPException(401, "token verification failed")
    sid = secrets.token_urlsafe(32)
    sessions[sid] = user
    response = RedirectResponse("/agent/", status_code=303)
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", path="/agent")
    return response


@router.post("/logout")
def logout(request: Request):
    sessions.pop(request.cookies.get(COOKIE, ""), None)
    response = RedirectResponse("/agent/", status_code=303)
    response.delete_cookie(COOKIE, path="/agent")
    return response


@router.post("/ask")
async def ask(question: str = Form(...), user: User = Depends(require_user)):
    run = await run_agent(settings, user, question)
    runs[run.id] = run
    return RedirectResponse(f"/agent/runs/{run.id}", status_code=303)


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def show_run(request: Request, run_id: str, user: User = Depends(require_user)):
    run = runs.get(run_id)
    if run is None or (run.username != user.username and "procurement_manager" not in user.roles):
        raise HTTPException(404, "run not found")
    return render(request, "run.html", user, run=run)


@router.get("/drafts", response_class=HTMLResponse)
async def drafts(request: Request, message: str = "", user: User = Depends(require_user)):
    rows = await query(
        settings.reader_dsn,
        "SELECT draft_id, material_id, supplier_id, quantity_kg, rationale, requested_by, status,"
        " created_at FROM ai.po_drafts ORDER BY draft_id DESC LIMIT 20",
    )
    return render(request, "drafts.html", user, drafts=rows, message=message)


@router.post("/drafts/{draft_id}/approve")
async def approve(draft_id: int, user: User = Depends(require_user)):
    # The manager's own token goes to the ERP server, which makes the decision.
    async with httpx.AsyncClient(timeout=15) as http:
        response = await http.post(
            f"{settings.mcp_url}/approvals/{draft_id}",
            headers={"Authorization": f"Bearer {user.access_token}"},
        )
    body = response.json()
    if response.status_code == 200:
        message = (
            f"Draft #{draft_id} approved: ERP order #{body['po_id']} ({body['total_eur']} EUR)."
        )
    else:
        message = f"Draft #{draft_id} not approved ({response.status_code}): {body.get('error')}"
    return RedirectResponse(f"/agent/drafts?message={quote(message)}", status_code=303)


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request, user: User = Depends(require_user)):
    rows = await query(
        settings.audit_dsn,
        "SELECT event_id, occurred_at, actor, action, decision, detail FROM audit.events"
        " ORDER BY event_id DESC LIMIT 60",
    )
    return render(request, "audit.html", user, events=rows)


class AskBody(BaseModel):
    question: str


@router.post("/api/ask")
async def api_ask(body: AskBody, user: User = Depends(bearer_user)) -> JSONResponse:
    """Same agent, called with a bearer token. Used by tests and the CLI demo."""
    run = await run_agent(settings, user, body.question)
    runs[run.id] = run
    return JSONResponse(run.as_dict())


app.include_router(router)


@app.get("/")
def root():
    return RedirectResponse("/agent/", status_code=303)
