"""Jinja2 SQL template renderer."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates" / "sql"),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def render(template_name: str, **ctx) -> str:
    return _env.get_template(template_name).render(**ctx).strip()
