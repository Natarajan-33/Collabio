"""Render notification content into its HTML and plain-text bodies."""

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.modules.notify.compose import NotifyContent, NotifyContext
from app.modules.outreach.render import TEMPLATES_DIR, RenderedEmail

# Same convention as the outreach templates: escaping is keyed on `.html.j2`. Block tags on
# their own line leave no blank lines behind.
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html.j2"]),
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def unsubscribe_url(ctx: NotifyContext) -> str:
    return f"{ctx.backend_url.rstrip('/')}/api/v1/unsubscribe/{ctx.reply_token}"


def is_creator_mail(ctx: NotifyContext) -> bool:
    return ctx.kind.startswith("creator_")


def render(content: NotifyContent, ctx: NotifyContext) -> RenderedEmail:
    """The email for `content`; only creator mail carries the unsubscribe link."""
    values = {
        "heading": content.heading,
        "lines": content.lines,
        "cta_label": content.cta_label,
        "cta_url": content.cta_url,
        "ai_written": content.ai_written,
        "brand_name": ctx.brand_name,
        "unsubscribe_url": unsubscribe_url(ctx) if is_creator_mail(ctx) else None,
    }
    return RenderedEmail(
        subject=content.subject,
        html=_env.get_template("notify.html.j2").render(values),
        text=_env.get_template("notify.txt.j2").render(values),
    )
