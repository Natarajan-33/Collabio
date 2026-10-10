"""Render a drafted outreach email into its HTML and plain-text bodies."""

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.contact import first_name
from app.core.money import format_cents
from app.modules.outreach.prompts import EmailDraft, OutreachContext

# backend/templates/email, resolved from this file so it works from any working directory.
TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates" / "email"

# Templates are named `*.html.j2` / `*.txt.j2`, so HTML escaping is keyed on `.html.j2`;
# the plain-text one must not be escaped.
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html.j2"]),
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


def render_email(
    ctx: OutreachContext, draft: EmailDraft, *, offer_url: str, unsubscribe_url: str
) -> RenderedEmail:
    values = {
        "first_name": first_name(ctx.creator_name),
        "draft": draft,
        "brand_name": ctx.brand_name,
        "package_name": ctx.package.name,
        "listed_videos": ctx.delta.listed_videos,
        "ask_videos": ctx.delta.ask_videos,
        "listed_price": format_cents(ctx.delta.listed_price_cents),
        "ask_price": format_cents(ctx.delta.ask_price_cents),
        "go_live_by": f"{ctx.go_live_by:%B} {ctx.go_live_by.day}, {ctx.go_live_by.year}",
        "offer_url": offer_url,
        "unsubscribe_url": unsubscribe_url,
    }
    return RenderedEmail(
        subject=draft.subject,
        html=_env.get_template("outreach.html.j2").render(values),
        text=_env.get_template("outreach.txt.j2").render(values),
    )
