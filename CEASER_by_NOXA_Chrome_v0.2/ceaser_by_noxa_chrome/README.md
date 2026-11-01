# CEASER by NOXA — Chrome-based Market Intelligence Agent (v0.2)

Runnable **FastAPI + HTML/CSS/JavaScript** development prototype. CEASER uses:

- **Your own NOXA AI API** (OpenAI-style chat/completions) for planning and report synthesis.
- **Google Chrome** controlled through **Playwright** for public website searching and reading. **No Brave Search API key.**
- **Google Search** as the *search website* by default. Optional **Bing** search page if Google blocks automation or results cannot be extracted.
- SQLite for investigations and a black/gold dashboard.

**Important distinction:** Chrome is the browser used to visit sites; Google and Bing are search engines. This prototype automates the public search-result pages, not Google's private internal APIs. Search pages change markup, may block automation or require consent, and are not guaranteed to work continuously. It **does not bypass** challenges or log in to social platforms.

## Windows PowerShell setup

Extract the ZIP, open PowerShell in `ceaser_by_noxa_chrome`, and run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

**Chrome must be installed on the same computer running the Python server.** The default `CEASER_BROWSER_CHANNEL=chrome` tells Playwright to control the Chrome installation. For an alternative browser executable supported by Playwright, you can install the bundled Chromium:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Then set `CEASER_BROWSER_CHANNEL=chromium` in `.env`. This is optional when Google Chrome is installed.

Open **http://127.0.0.1:8000** in your preferred browser. You may open the web UI in Chrome, but the **agent's browser** is a separate automated headless instance on the backend.

If Google web search blocks the agent, you can change `CEASER_SEARCH_ENGINE=bing` in `.env` and restart the Python server. Bing's page can also change or block access; this is a fallback, not a guarantee.

## API setup (.env)

| Variable | Meaning |
|---|---|
| `NOXA_API_BASE_URL` | OpenAI-compatible base URL including `/v1` (do not append `/chat/completions`) |
| `NOXA_API_KEY` | Your NOXA model API key (stored on server only) |
| `NOXA_MODEL` | Identifier accepted by your NOXA endpoint |
| `CEASER_BROWSER_CHANNEL` | `chrome` (default) or `chromium` |
| `CEASER_SEARCH_ENGINE` | `google` (default) or `bing` |
| `CEASER_MAX_SOURCE_PAGES` | Maximum number of results whose page text is actually visited; default 6 |
| `CEASER_MAX_SEARCHES` | Upper bound on generated queries |
| `CEASER_MAX_SOURCES` | Upper bound on deduplicated result URLs |
| `CEASER_ACCESS_KEY` | Optional shared prototype access key; *not* user authentication |
| `CEASER_DB_PATH` | SQLite database location |

Do not commit `.env` files or expose CEASER directly to the internet. Chrome will make outbound requests from the **server's IP address**; this version does not anonymize the server and should not be used to evade website restrictions.

## Research lifecycle

1. Enter research objective, region and depth in the CEASER dashboard.
2. NOXA API plans up to 2/4/6 search queries by depth, including disconfirming search angles.
3. CEASER launches a fresh, credential-free, headless Chrome browser through Playwright.
4. The agent visits public Google Search (or Bing) pages, extracts external HTTPS results and deduplicates sources.
5. Chrome opens up to `CEASER_MAX_SOURCE_PAGES` public result pages and captures a **limited excerpt** from each when accessible. The browser blocks images, font/media, downloads, service workers and non-public/non-HTTPS URLs as basic prototype hardening.
6. NOXA API produces findings, recommendations, source references and explicit uncertainty from the collected material.
7. The backend validates source IDs and downgrades uncited factual assertions or those with no fetched page excerpt to `UNDETERMINED`.
8. Inspect progress, source URLs and excerpts on the dashboard; download a Markdown report.

When the browser is blocked or a page fails to load, the backend logs the limitation and does **not** invent the missing evidence. Search-result excerpts are not exhaustive validation and cannot by themselves establish market share, representative consumer sentiment, or causal impact.

## HTTP endpoints

- `GET /api/health` — configuration modes (browser launch is **not** verified by this health check)
- `POST /api/investigations` — create investigation
- `GET /api/investigations` — recent investigations
- `GET /api/investigations/{id}` — research detail, sources, findings, logs
- `GET /api/investigations/{id}/report` — Markdown download

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Unit tests use simulated browser and NOXA API responses. They cannot prove external Google/Bing access or compatibility with the actual NOXA API. A local Chromium smoke test can validate DOM extraction when an installed browser is available.

## Not consumer-ready

- The Google/Bing web UI can change or block automated access; reliable commercial search likely requires licensed/official search APIs or permitted feeds.
- Requires durable queue, concurrency controls, rate/cost limits, retries, auth, isolation, audits, source provenance and better market methodology.
- Browser URL screening is an initial defense, **not** full protection against server-side request forgery (e.g. DNS rebinding). Run browser workers in a restricted network sandbox before serving untrusted users.
- Chrome page content may contain prompt injection and false information. Treat all fetched content as untrusted evidence.
- NOXA API credentials are not provided and are required for actual runs. Model output format can require a custom adapter.
- No verified end-to-end browser/search + real NOXA model test has been performed.

## Upgrading from v0.1

The archive deliberately contains no existing database or API secrets. To preserve investigations, copy your old `ceaser.db` into this directory while the old server is stopped. To preserve the NOXA API configuration, copy the previous `.env` and add the new `CEASER_BROWSER_CHANNEL`, `CEASER_SEARCH_ENGINE` and `CEASER_MAX_SOURCE_PAGES` settings. Remove the obsolete `BRAVE_SEARCH_API_KEY`; it is ignored.
