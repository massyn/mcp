# Publish S3 MCP

An MCP server for publishing HTML and markdown content directly to an AWS S3 static website bucket. Markdown is converted to styled HTML via [mddoco](https://github.com/philm/doco) before upload. PDF export is also supported via Playwright/Chromium.

---

## Requirements

- Python 3.10+
- Claude Desktop (or any MCP-compatible client)
- AWS credentials configured (via `~/.aws/credentials` or environment)
- `mddoco` installed (see below)
- Playwright + Chromium (PDF export only)

---

## Installation

```bash
pip install -r requirements.txt
```

For PDF export:

```bash
pip install playwright
playwright install chromium
```

Register with Claude Desktop from the repository root:

```bash
python install.py publishs3
```

Restart Claude Desktop after running.

---

## Configuration

Copy `.env_example` to `.env` and fill in your values:

| Variable | Required | Description |
|----------|----------|-------------|
| `S3BUCKET` | Yes | S3 bucket name |
| `AWS_PROFILE` | No | AWS credentials profile to use |
| `BASE_URL` | No | Base URL for published links (e.g. `https://static.example.com`). If omitted, defaults to the standard S3 website endpoint |

If `BASE_URL` is not set, the URL is derived from the bucket's region:

```
http://{bucket}.s3-website-{region}.amazonaws.com/{key}
```

---

## MCP Tools

### `list_themes()`

Returns the available mddoco themes that can be passed to the markdown and PDF tools.

```
list_themes() -> str
```

Current themes: `academic`, `academic-wide`, `dark`, `dark-wide`, `default`, `default-wide`, `professional`, `professional-wide`.

---

### `publish_html_to_s3(html, key)`

Upload a raw HTML string directly to S3.

```
publish_html_to_s3(html: str, key: str) -> str
```

| Argument | Description |
|----------|-------------|
| `html` | Full HTML content to publish |
| `key` | S3 object key, e.g. `reports/index.html`. `.html` is appended if absent |

Returns the public URL on success, or an error message.

---

### `publish_markdown_to_s3(markdown, key, title, theme)`

Convert markdown to HTML using mddoco, then upload to S3.

```
publish_markdown_to_s3(markdown: str, key: str, title: str = "", theme: str = "default") -> str
```

| Argument | Description |
|----------|-------------|
| `markdown` | Markdown content to convert and publish |
| `key` | S3 object key, e.g. `docs/guide.html`. `.html` is appended if absent |
| `title` | Page title for the HTML document. Derived from the key if omitted |
| `theme` | mddoco theme name. Call `list_themes()` to see options |

Returns the public URL on success, or an error message.

---

### `publish_pdf_to_s3(markdown, key, title, theme)`

Convert markdown to PDF via mddoco and Chromium, then upload to S3.

```
publish_pdf_to_s3(markdown: str, key: str, title: str = "", theme: str = "default") -> str
```

| Argument | Description |
|----------|-------------|
| `markdown` | Markdown content to convert and publish |
| `key` | S3 object key, e.g. `docs/report.pdf`. `.pdf` is appended if absent |
| `title` | Page title for the document. Derived from the key if omitted |
| `theme` | mddoco theme name. Call `list_themes()` to see options |

Requires Playwright and Chromium. Returns the public URL on success, or an error message.

---

## File Structure

```
install.py            — registers MCP servers with Claude Desktop (repo root)
publishs3/
  mcp.json            — install manifest (entry point + alwaysAllow list)
  publishs3_mcp.py    — MCP server and tools
  requirements.txt    — dependencies
  .env_example        — configuration template
  .env                — your local configuration (not committed)
```
