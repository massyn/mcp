"""Publish to S3 MCP — upload HTML files or convert markdown then upload."""

import os
import tempfile
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from importlib.resources import files as pkg_files
from mddoco.converter import convert_file
from mddoco.pdf import html_to_pdf
from mddoco.renderer import render_html

load_dotenv(Path(__file__).parent / ".env")

_BUCKET = os.environ.get("S3BUCKET", "")
_PROFILE = os.environ.get("AWS_PROFILE", "")
_BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")

mcp = FastMCP("publishs3")


def _available_themes() -> list[str]:
    themes_dir = pkg_files("mddoco").joinpath("themes")
    return sorted(p.stem for p in Path(str(themes_dir)).glob("*.html"))


def _s3_client():
    session = boto3.Session(profile_name=_PROFILE or None)
    return session.client("s3")


def _upload(content: bytes, key: str, content_type: str) -> str:
    if not _BUCKET:
        return "ERROR: S3BUCKET not configured in .env"
    try:
        client = _s3_client()
        client.put_object(
            Bucket=_BUCKET,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        if _BASE_URL:
            base = _BASE_URL
        else:
            region = client.get_bucket_location(Bucket=_BUCKET)["LocationConstraint"] or "us-east-1"
            base = f"http://{_BUCKET}.s3-website-{region}.amazonaws.com"
        url = f"{base}/{key}"
        return f"Published successfully. URL: {url}"
    except (BotoCoreError, ClientError) as e:
        return f"ERROR: {e}"


@mcp.tool()
def publish_html_to_s3(html: str, key: str) -> str:
    """
    Upload an HTML string directly to S3 and return the public URL.

    Args:
        html: The full HTML content to publish.
        key:  The S3 object key (path), e.g. "reports/index.html".
              Must end with .html.
    """
    if not key.endswith(".html"):
        key = key.rstrip("/") + ".html"
    return _upload(html.encode("utf-8"), key, "text/html; charset=utf-8")


def _markdown_to_html(markdown: str, key: str, title: str, theme: str) -> str:
    """Convert a markdown string to a full HTML document via mddoco."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(markdown)
        tmp_path = Path(tmp.name)

    try:
        html_body, _ = convert_file(tmp_path, toc=False)
        page_title = title or Path(key).stem.replace("-", " ").replace("_", " ").title()
        return render_html(
            sections=[(tmp_path, html_body)],
            title=page_title,
            theme=theme,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@mcp.tool()
def list_themes() -> str:
    """Return the available mddoco themes that can be used when publishing markdown."""
    return "Available themes: " + ", ".join(_available_themes())


@mcp.tool()
def publish_markdown_to_s3(markdown: str, key: str, title: str = "", theme: str = "default") -> str:
    """
    Convert a markdown string to HTML using mddoco, then upload to S3.

    Args:
        markdown: The markdown content to convert and publish.
        key:      The S3 object key (path), e.g. "docs/guide.html".
                  The .html extension is added automatically if absent.
        title:    Optional page title for the generated HTML document.
        theme:    mddoco theme name (default: "default"). Call list_themes() to see options.
    """
    if not key.endswith(".html"):
        key = key.rstrip("/") + ".html"
    html = _markdown_to_html(markdown, key, title, theme)
    return _upload(html.encode("utf-8"), key, "text/html; charset=utf-8")


@mcp.tool()
def publish_pdf_to_s3(markdown: str, key: str, title: str = "", theme: str = "default") -> str:
    """
    Convert a markdown string to a PDF using mddoco and Chromium, then upload to S3.

    Args:
        markdown: The markdown content to convert and publish.
        key:      The S3 object key (path), e.g. "docs/report.pdf".
                  The .pdf extension is added automatically if absent.
        title:    Optional page title for the generated document.
        theme:    mddoco theme name (default: "default"). Call list_themes() to see options.
    """
    if not key.endswith(".pdf"):
        key = key.rstrip("/") + ".pdf"

    html = _markdown_to_html(markdown, key, title, theme)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        pdf_path = Path(tmp.name)

    try:
        html_to_pdf(html, pdf_path)
        pdf_bytes = pdf_path.read_bytes()
    except RuntimeError as e:
        return f"ERROR: {e}"
    finally:
        pdf_path.unlink(missing_ok=True)

    return _upload(pdf_bytes, key, "application/pdf")


if __name__ == "__main__":
    mcp.run()
