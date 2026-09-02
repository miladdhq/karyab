"""SQLite persistence for everything the feed has shown us.

Two invariants matter here:

  * `first_seen_at` is written once and never moves. It is the only
    trustworthy freshness signal, because the API's `past_time` is a
    localised display string and `created_at` costs a detail request.
  * Rejected projects are stored with their reasons. Tuning the matcher
    means looking at what it threw away, so throwing it away is not an
    option.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import Project

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id             INTEGER PRIMARY KEY,
    user_id        INTEGER NOT NULL DEFAULT 0,
    title          TEXT    NOT NULL DEFAULT '',
    slug           TEXT    NOT NULL DEFAULT '',
    category_id    INTEGER NOT NULL DEFAULT 0,
    min_budget     INTEGER NOT NULL DEFAULT 0,
    max_budget     INTEGER NOT NULL DEFAULT 0,
    token          INTEGER NOT NULL DEFAULT 0,
    skills         TEXT    NOT NULL DEFAULT '[]',
    first_seen_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    project_id  INTEGER NOT NULL,
    stage       INTEGER NOT NULL,
    value       REAL    NOT NULL,
    rejected    INTEGER NOT NULL,
    reasons     TEXT    NOT NULL DEFAULT '[]',
    scored_at   TEXT    NOT NULL,
    PRIMARY KEY (project_id, stage),
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE INDEX IF NOT EXISTS scores_by_value ON scores(value DESC);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        self._db.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def has_seen(self, project_id: int) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return row is not None

    def first_seen(self, project: Project, now: datetime) -> datetime:
        """Record the project if new; return when we first saw it.

        The INSERT is deliberately not an upsert on first_seen_at: the
        whole point of the column is that it does not move.
        """
        self._db.execute(
            """
            INSERT INTO projects
                (id, user_id, title, slug, category_id,
                 min_budget, max_budget, token, skills, first_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title      = excluded.title,
                max_budget = excluded.max_budget,
                min_budget = excluded.min_budget,
                token      = excluded.token,
                skills     = excluded.skills
            """,
            (
                project.id,
                project.user_id,
                project.title,
                project.slug,
                project.category_id,
                project.min_budget,
                project.max_budget,
                project.token,
                json.dumps(list(project.skills), ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._db.commit()

        row = self._db.execute(
            "SELECT first_seen_at FROM projects WHERE id = ?", (project.id,)
        ).fetchone()
        return datetime.fromisoformat(row["first_seen_at"])

    def record_score(
        self,
        project_id: int,
        stage: int,
        value: float,
        rejected: bool,
        reasons: list[str],
        now: datetime,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO scores (project_id, stage, value, rejected, reasons, scored_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, stage) DO UPDATE SET
                value     = excluded.value,
                rejected  = excluded.rejected,
                reasons   = excluded.reasons,
                scored_at = excluded.scored_at
            """,
            (
                project_id,
                stage,
                float(value),
                1 if rejected else 0,
                json.dumps(reasons, ensure_ascii=False),
                now.isoformat(),
            ),
        )
        self._db.commit()

    def latest_scores(self, limit: int = 50) -> list[dict]:
        rows = self._db.execute(
            """
            SELECT s.project_id, s.stage, s.value, s.rejected, s.reasons,
                   s.scored_at, p.title, p.slug, p.min_budget, p.max_budget,
                   p.token, p.category_id, p.first_seen_at
            FROM scores s
            JOIN projects p ON p.id = s.project_id
            ORDER BY s.value DESC, s.scored_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                "project_id": r["project_id"],
                "stage": r["stage"],
                "value": r["value"],
                "rejected": bool(r["rejected"]),
                "reasons": json.loads(r["reasons"]),
                "scored_at": r["scored_at"],
                "title": r["title"],
                "slug": r["slug"],
                "min_budget": r["min_budget"],
                "max_budget": r["max_budget"],
                "token": r["token"],
                "category_id": r["category_id"],
                "first_seen_at": r["first_seen_at"],
            }
            for r in rows
        ]
