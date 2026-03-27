# listing-lens

Automated system to scrape, deduplicate, store, score, and track property listings advertised in Poland. Focused on Otodom, Gratka, and Morizon portals. Built with Scrapy, PostgreSQL.

## Codebase Memory (codebase-memory-mcp)

**BLOCKING REQUIREMENT**: At the start of EVERY conversation involving structural
code questions, you MUST first call `tool_search_tool_regex` with pattern `mcp_codebase`
to load the graph tools. These are deferred tools — they are NOT available until
discovered via `tool_search_tool_regex`. Calling them without loading first will fail.

For ALL structural code questions (who calls X, what does X call, find functions by
pattern, dead code analysis, cross-service HTTP calls, REST routes), you MUST use
graph tools. Never substitute grep, file search, or read_file for structural questions.

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

Scrapy spiders → Dedup (SHA-256 hash) → PostgreSQL + NVMe filesystem → LLM scoring → Feedback loop

## Tech Stack

- **Scraping**: Scrapy + `scrapy-impersonate` (TLS/JA3 spoofing) + `scrapy-fake-useragent` + AutoThrottle
- **Database**: Self-hosted PostgreSQL via `psycopg` (sync). All DB calls are synchronous — no async/await on DB methods.
- **Photo storage**: NVMe filesystem via `PhotoStorage` protocol (`put`/`get`). Abstracted for future S3 migration. Store actual photo binary files, never just URLs.
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
listing-lens/
├── .github/                    # Copilot instructions + prompts
├── alembic/                    # Alembic migration scripts
│   └── versions/
├── data/                       # Spider run output (gitignored)
├── logs/                       # Structured log files (gitignored)
├── tests/                      # pytest test suite
├── logging_config.py           # Shared structured logging (structlog)
├── storage/
│   ├── __init__.py
│   ├── db.py                   # psycopg SQL helpers (sync)
│   ├── photos.py               # PhotoStorage protocol + implementations  # TODO: Stage 3
│   └── models.py               # Shared Pydantic models                   # TODO: Stage 3
├── scoring/                    # TODO: Stage 5
│   ├── schemas.py
│   ├── adapter.py
│   ├── prompts.py
│   └── scorer.py
├── feedback/                   # TODO: Stage 6
│   ├── feedback.py
│   └── cli.py
├── scheduler/                  # TODO: Stage 4
│   └── jobs.py
├── config/
│   └── .env.example
├── main.py                     # TODO: Stage 4 — APScheduler entry point
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
└── alembic.ini
```
