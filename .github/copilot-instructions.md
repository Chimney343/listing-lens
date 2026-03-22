# listing-lens

Automated system to scrape, deduplicate, store, score, and track property listings advertised in Poland. Focused on Otodom, Gratka, and Morizon portals. Built with Scrapy, PostgreSQL.

## Codebase Memory (codebase-memory-mcp)

When this MCP server is available, prefer graph tools over grep/file search 
for structural code questions. Graph queries return precise results in a single 
tool call vs file-by-file exploration.

### Indexing
- Always use repo_path="/mnt/c/Users/mkkom/listing-lens"
- The indexed project name is **mnt-c-Users-mkkom-listing-lens** — always use this as the `project` parameter in all graph tool calls
- Never ask the user for the WSL repo path

### When to use graph tools
- "Who calls X?": `trace_call_path(function_name="X", direction="inbound")`
- "What does X call?": `trace_call_path(function_name="X", direction="outbound")`
- Find functions by pattern: `search_graph(label="Function", name_pattern=".*Pattern.*")`
- Dead code: `search_graph(label="Function", relationship="CALLS", direction="inbound", max_degree=0, exclude_entry_points=true)`
- Cross-service HTTP calls: `search_graph(relationship="HTTP_CALLS")`
- REST routes: `search_graph(label="Route")`
- Understand structure first: `get_graph_schema` before writing complex queries
- Read source after finding a function: `get_code_snippet(qualified_name="...")`
- Complex multi-hop patterns: `query_graph` with Cypher syntax

### When NOT to use graph tools
- Text search (string literals, error messages, config values) — use grep/Glob
- Single file reads — use the Read tool directly
- Syntax or formatting questions

## Architecture

Scrapy spiders → Dedup (SHA-256 hash) → PostgreSQL + MinIO → LLM scoring → Feedback loop

## Tech Stack

- **Scraping**: Scrapy + `scrapy-impersonate` (TLS/JA3 spoofing) + `scrapy-fake-useragent` + AutoThrottle
- **Database**: Self-hosted PostgreSQL via `psycopg` (sync). All DB calls are synchronous — no async/await on DB methods.
- **Photo storage**: MinIO (S3-compatible, self-hosted). Store actual photo binary files, never just URLs.
- **LLM scoring**: `instructor` + Pydantic v2 for structured output. Provider-agnostic (Claude, OpenAI, Gemini, Ollama).
- **Scheduling**: APScheduler. Scrapy spiders launched via `subprocess.run()` to avoid Twisted reactor issues.
- **Config**: `pydantic-settings` + `.env`

## Environment & Execution

- This project uses **Poetry** for dependency management. The virtualenv is managed by Poetry.
- All Python commands must be run via `poetry run` — e.g. `poetry run scrapy crawl otodom`, `poetry run python main.py`.
- When installing packages, use `poetry add <package>` (not pip).
- Dev dependencies go under `poetry add --group dev <package>`.
- The `pyproject.toml` is the single source of truth for dependencies. Never create or modify `requirements.txt`.
- When generating shell commands, scripts, Dockerfiles, or systemd units, always prefix Python/Scrapy invocations with `poetry run`.

## Key Conventions

- Python 3.11+. Type hints everywhere.
- Pydantic v2 for all data models and validation.
- All Scrapy spider search areas are parameterized via `-a` spider arguments (`city`, `districts`, `price_min`, `price_max`, `max_pages`).
- Price history is append-only — never UPDATE existing price rows, always INSERT new ones.
- Dedup hash: `SHA-256(district|area_m2|floor|price_pln|rooms|street)[:16]`
- Listings are only marked "gone" after 3 consecutive absence confirmations, never on first failure.
- Otodom is a Next.js app — parse `<script id="__NEXT_DATA__">` JSON, not HTML selectors.
- Gratka and Morizon are server-rendered HTML — use `response.css()` / `response.xpath()`.
- All CSS selectors for gratka/morizon should be defined as class-level constants for easy maintenance.

## Project Layout

```
property-pipeline/
├── .github/                    # Copilot instructions + prompts
├── scrapy_project/
│   ├── scrapy.cfg
│   └── property_scraper/
│       ├── settings.py         # Anti-bot config (impersonate, AutoThrottle, etc.)
│       ├── items.py            # RawListingItem
│       ├── pipelines.py        # Validation → Dedup → PhotoDownload → DB insert
│       ├── middlewares.py
│       ├── area_config.py      # SearchArea dataclass + per-portal URL builders
│       └── spiders/
│           ├── otodom.py
│           ├── gratka.py
│           └── morizon.py
├── storage/
│   ├── db.py                   # psycopg DatabaseClient (sync)
│   ├── photos.py               # MinIO PhotoManager
│   └── models.py
├── scoring/
│   ├── schemas.py              # ListingScore Pydantic model
│   ├── adapter.py              # LLMAdapter (instructor)
│   ├── prompts.py              # SCORING_SYSTEM_PROMPT
│   └── scorer.py               # ListingScorer orchestration
├── feedback/
│   ├── feedback.py             # FeedbackManager
│   └── cli.py                  # typer CLI (view_top, record, analyze)
├── scheduler/
│   └── jobs.py                 # APScheduler + subprocess spider launch
├── config/
│   ├── settings.py             # StorageSettings (pydantic-settings)
│   └── .env.example
└── main.py
```
