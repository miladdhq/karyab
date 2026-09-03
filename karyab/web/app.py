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
        items = [r for r in rows if rejected or not r["rejected"]]
        # Nothing is submitted until Phase 4, so there is no spend to report
        # yet. The meter shows what the queue would COST if every candidate
        # above the threshold were sent — which is the decision actually in
        # front of the user — rather than a zero dressed up as a number.
        candidates = [r for r in items
                      if not r["rejected"] and r["value"] >= cfg.threshold]
        return {
            "threshold": cfg.threshold,
            "daily_cap": cfg.daily_cap,
            "items": items,
            "queued_tokens": sum(r["token"] for r in candidates),
            "candidate_count": len(candidates),
        }

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
