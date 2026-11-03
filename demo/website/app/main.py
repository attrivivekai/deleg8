from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.content import PLANS, STEPS, TEAM_SIZES
from app.db import WaitlistSignup, get_session

BASE_DIR = Path(__file__).parent
settings = get_settings()

app = FastAPI(title="deleg8")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["url"] = lambda path="/": f"{settings.base_path}{path}"
templates.env.globals["static_mode"] = settings.static_mode

PLAN_IDS = {p["id"] for p in PLANS}


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"plans": PLANS, **ctx})


# ---------------------------------------------------------------- validation
def is_valid_email(email: str) -> bool:
    return "@" in email


class SignupIn(BaseModel):
    email: str
    company: str = ""
    team_size: str = "1-10"
    plan_interest: str = "starter"


def create_signup(session: Session, data: SignupIn) -> WaitlistSignup:
    email = data.email.strip().lower()
    if not is_valid_email(email):
        raise HTTPException(status_code=422, detail="Please enter a valid email address.")
    if data.plan_interest not in PLAN_IDS:
        raise HTTPException(status_code=422, detail="Unknown plan.")
    signup = WaitlistSignup(
        email=email,
        company=data.company.strip(),
        team_size=data.team_size if data.team_size in TEAM_SIZES else "1-10",
        plan_interest=data.plan_interest,
    )
    session.add(signup)
    session.commit()
    return signup


# --------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return render(request, "home.html", steps=STEPS, team_sizes=TEAM_SIZES)


@app.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request):
    return render(request, "how_it_works.html", steps=STEPS)


@app.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return render(request, "pricing.html")


@app.post("/waitlist")
def waitlist_form(
    email: str = Form(...),
    company: str = Form(""),
    team_size: str = Form("1-10"),
    plan_interest: str = Form("starter"),
    session: Session = Depends(get_session),
):
    create_signup(
        session,
        SignupIn(email=email, company=company, team_size=team_size, plan_interest=plan_interest),
    )
    return RedirectResponse(url=f"{settings.base_path}/thanks", status_code=303)


@app.get("/thanks", response_class=HTMLResponse)
def thanks(request: Request):
    return render(request, "thanks.html")


# ----------------------------------------------------------------------- api
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/waitlist", status_code=201)
def waitlist_api(data: SignupIn, session: Session = Depends(get_session)):
    signup = create_signup(session, data)
    return {"id": signup.id, "email": signup.email}


@app.get("/api/waitlist/count")
def waitlist_count(session: Session = Depends(get_session)):
    total = session.scalar(select(func.count()).select_from(WaitlistSignup)) or 0
    return {"count": total}
