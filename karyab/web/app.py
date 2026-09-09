"""The local review dashboard.

Security posture, because this process holds an API key and can spend money:

  * binds to 127.0.0.1 unless the operator passes an explicit host
  * refuses a non-loopback bind without --i-know, and says why
  * never returns the API key to the browser, only a mask
"""

from __future__ import annotations

import ipaddress
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from ..config import Config, default_config_path
from ..store import Store
from ..api import KarlancerClient
from ..writer.rules import assess, validate
from .secrets import (
    ApiKeyInvalid,
    clear_api_key,
    load_api_key,
    mask_api_key,
    save_api_key,
)

PAGE = (Path(__file__).parent / "index.html")


class ApiKeyIn(BaseModel):
    key: str


class DraftIn(BaseModel):
    text: str


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def today_spend(db_path: str) -> dict:
    """Bids sent in the last 24 hours. The daily cap is a rolling window, not
    a calendar day — a cap that resets at midnight invites a 23:59 spree."""
    from datetime import datetime, timedelta, timezone

    with Store(db_path) as store:
        return store.spend_since(datetime.now(timezone.utc) - timedelta(hours=24))


def create_app(db_path: str, config_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="karyab", docs_url=None, redoc_url=None)
    cfg_path = Path(config_path) if config_path else default_config_path()

    def config() -> Config:
        return Config.load(cfg_path) if cfg_path.exists() else Config.default()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE.read_text(encoding="utf-8")

    @app.get("/api/queue")
    def queue(limit: int = 40, rejected: bool = False):
        cfg = config()
        with Store(db_path) as store:
            rows = store.top_scores(limit=limit)
            written = store.drafts()
        items = [r for r in rows if rejected or not r["rejected"]]
        for item in items:
            draft = written.get(item["project_id"])
            item["draft"] = draft["text"] if draft else ""
            item["draft_source"] = draft["source"] if draft else ""

        candidates = [r for r in items
                      if not r["rejected"] and r["value"] >= cfg.threshold]
        # Real spend, now that applications are recorded: what has actually
        # been sent in the last 24 hours against the daily cap.
        from datetime import datetime, timedelta, timezone
        spent = today_spend(db_path)
        return {
            "threshold": cfg.threshold,
            "daily_cap": cfg.daily_cap,
            "items": items,
            "queued_tokens": sum(r["token"] for r in candidates),
            "candidate_count": len(candidates),
            "sent_today": spent["count"],
            "tokens_today": spent["tokens"],
        }

    @app.get("/api/applied")
    def applied(limit: int = 200):
        with Store(db_path) as store:
            rows = store.applied(limit=limit)
        return {"items": rows,
                "total_tokens": sum(r["token"] for r in rows)}

    @app.post("/api/applied/{project_id}")
    def mark(project_id: int):
        from datetime import datetime, timezone

        with Store(db_path) as store:
            store.mark_applied(project_id, datetime.now(timezone.utc))
        return {"applied": True}

    @app.delete("/api/applied/{project_id}")
    def unmark(project_id: int):
        with Store(db_path) as store:
            store.unmark_applied(project_id)
        return {"applied": False}

    @app.get("/api/voice")
    def voice(skills: str = "", limit: int = 3):
        wanted = tuple(s.strip() for s in skills.split(",") if s.strip())
        with Store(db_path) as store:
            return {"samples": store.teachable_samples(match_skills=wanted, limit=limit),
                    "stats": store.voice_stats()}

    @app.post("/api/check")
    def check(draft: DraftIn):
        """Run a draft through the same gate the writer uses."""
        blocking = [asdict(v) for v in validate(draft.text)]
        a = assess(draft.text)
        return {"blocking": blocking, "assessment": asdict(a)}

    @app.post("/api/actions/scan")
    def action_scan(pages: int = 2):
        """Poll the feed and score it. Reads only; sends nothing."""
        from datetime import datetime, timezone

        from ..scan import run_scan

        cfg = config()
        try:
            with Store(db_path) as store, KarlancerClient() as client:
                result = run_scan(client, store, cfg,
                                  now=datetime.now(timezone.utc), pages=pages)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)[:200]) from exc
        return {"seen": result.seen, "new": result.new, "rejected": result.rejected,
                "promoted": result.promoted, "errors": list(result.errors)}

    @app.post("/api/actions/harvest")
    def action_harvest():
        """Re-read the user's own bid history to refresh the voice corpus."""
        import json as _json
        from datetime import datetime, timezone

        from playwright.sync_api import sync_playwright

        from ..browser.authed import AuthTokenMissing, bearer_header, extract_token
        from ..browser.session import SESSION_PATH, SessionExpired, load_context
        from ..harvest import harvest

        try:
            state = _json.loads(SESSION_PATH.read_text(encoding="utf-8"))
            headers = bearer_header(extract_token(state))
        except FileNotFoundError:
            raise HTTPException(status_code=400,
                                detail="Not logged in. Run: karyab login") from None
        except AuthTokenMissing as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            with sync_playwright() as p:
                browser, context = load_context(p, headless=True)
                with Store(db_path) as store:
                    result = harvest(context.request, headers, store,
                                     datetime.now(timezone.utc))
                    stats = store.voice_stats()
                browser.close()
        except SessionExpired as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {"fetched": result.fetched, **stats}

    @app.get("/api/brief/{project_id}")
    def brief_one(project_id: int):
        """The full writing brief for one project, ready to paste to Claude."""
        from ..cli import matched_terms
        from ..writer.prompt import build_brief

        with Store(db_path) as store:
            rows = store.top_scores(limit=200)
            row = next((r for r in rows if r["project_id"] == project_id), None)
            if row is None:
                raise HTTPException(status_code=404, detail="No such project.")
            voice = store.teachable_samples(
                match_skills=matched_terms(row.get("reasons") or ()), limit=3)
            corpus = store.voice_stats()
        return {"brief": build_brief(row, voice), "title": row["title"],
                "voice_samples": len(voice), "corpus": corpus["teachable"]}

    @app.post("/api/draft/{project_id}")
    def save_one_draft(project_id: int, draft: DraftIn):
        """Store an edited draft so it survives a page reload."""
        from datetime import datetime, timezone

        a = assess(draft.text)
        problems = [v.code for v in validate(draft.text)]
        with Store(db_path) as store:
            store.save_draft(project_id, draft.text, datetime.now(timezone.utc),
                             source="review", score=a.score, blocking=problems)
        return {"saved": True, "score": a.score, "blocking": problems}

    @app.get("/api/settings")
    def get_settings():
        key = load_api_key()
        return {
            "api_key_set": key is not None,
            "api_key_masked": mask_api_key(key),
            "config_path": str(cfg_path),
            "config_exists": cfg_path.exists(),
            "threshold": config().threshold,
        }

    @app.post("/api/settings/api-key")
    def set_api_key(payload: ApiKeyIn):
        try:
            save_api_key(payload.key)
        except ApiKeyInvalid as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"api_key_set": True, "api_key_masked": mask_api_key(load_api_key())}

    @app.delete("/api/settings/api-key")
    def delete_api_key():
        clear_api_key()
        return {"api_key_set": False, "api_key_masked": mask_api_key(None)}

    @app.post("/api/settings/api-key/test")
    def test_api_key():
        """Spend one cheap call to prove the key works."""
        key = load_api_key()
        if not key:
            raise HTTPException(status_code=400, detail="No API key saved yet.")
        try:
            import anthropic
        except ImportError:
            raise HTTPException(status_code=500,
                                detail="The anthropic package is not installed.") from None
        try:
            client = anthropic.Anthropic(api_key=key)
            client.messages.create(
                model="claude-opus-5",
                max_tokens=16,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            )
        except anthropic.AuthenticationError:
            raise HTTPException(status_code=401,
                                detail="Anthropic rejected that key.") from None
        except anthropic.APIConnectionError:
            raise HTTPException(
                status_code=502,
                detail="Could not reach Anthropic. If a proxy is set, note that "
                       "karyab talks to Anthropic directly.") from None
        except anthropic.APIStatusError as exc:
            raise HTTPException(status_code=502,
                                detail=f"Anthropic returned {exc.status_code}.") from None
        return {"ok": True}

    return app


def serve(db_path: str, *, host: str = "127.0.0.1", port: int = 8765,
          allow_remote: bool = False) -> None:
    import uvicorn

    if not is_loopback(host) and not allow_remote:
        raise SystemExit(
            f"Refusing to bind to {host}.\n"
            "This process stores your Anthropic API key and can spend money, "
            "and it has no login.\n"
            "If you really want it reachable from your phone or another "
            "machine, pass --i-know."
        )
    if not is_loopback(host):
        print(f"WARNING: serving on {host} with no authentication. "
              f"Anyone on this network can read your queue and spend your API credit.")

    print(f"karyab review → http://{host}:{port}")
    uvicorn.run(create_app(db_path), host=host, port=port, log_level="warning")
