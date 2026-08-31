# Research artefacts

Raw API responses captured from karlancer.com on 2026-08-31 while writing the
design. They are the evidence for the claims in
`../superpowers/specs/2026-08-31-karyab-design.md` — in particular that
`users_bid` and `successful_projects_percentage` carry no usable signal.

- `sample-search-projects.json` — `GET /api/publics/search/projects?page=1`
- `sample-project-detail.json` — `GET /api/publics/projects/{slug}`

Kept so the scorer can be unit-tested without touching the live site.
