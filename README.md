# Peblo TV Mini

CMS upload → published catalogue → Netflix-style browse.

An internal CMS where the content team manages shows and artwork, a publish job that
builds an immutable catalogue document, and a viewer app that reads only what has
actually been published.

```
CMS (React) ──► API (FastAPI + Postgres) ──► publish ──► catalog/versions/<run>.json
  :5173                  :8000                              │
                                    Viewer (React) ◄────────┘
                                       :5174
```

---

## Run it

```bash
cp .env.example .env
docker compose up --build
```

That brings up Postgres, the API (migrated and seeded from `data/seed_shows.json`), and
both UIs. First boot takes a couple of minutes for the image builds.

| | URL | |
|---|---|---|
| Viewer | http://localhost:5174 | no sign-in |
| CMS | http://localhost:5173 | sign in below |
| API docs | http://localhost:8000/docs | |
| Health | http://localhost:8000/health | |

Postgres is published on **5433**, not 5432 — a developer machine very often
already has Postgres on 5432, and on Windows both will bind it happily, after
which connections land on whichever answers first. Nothing inside the stack
depends on the host port; change `POSTGRES_PORT` if you prefer.

**Demo accounts**

| Email | Password | Can |
|---|---|---|
| `admin@peblo.test` | `peblo-admin` | edit **and publish** |
| `editor@peblo.test` | `peblo-editor` | edit only — publish returns 403 |

Sign in as the editor first and press **Publish** to see the role actually enforced,
then sign in as the admin.

### Tests

```bash
cd api && pip install -r requirements-dev.txt && pytest
```

59 tests, 71% line coverage overall — the parts that matter most are higher
(validation 96%, catalogue builder 89%, publish 71%). Tests need Postgres; with
the stack already up, the compose one will do:

```bash
docker compose exec db psql -U peblo -d peblo -c "CREATE DATABASE peblo_test;"
cd api && DATABASE_URL=postgresql+psycopg://peblo:peblo@127.0.0.1:5433/peblo_test pytest
```

CI runs its own `postgres:16` service. A real Postgres is deliberate: the schema
leans on partial unique indexes, array containment and `pg_trgm`, none of which
exist on SQLite, so testing there would test something other than what ships.

---

## What I found in the seed data

The brief said the data is deliberately imperfect and doesn't say where. Here is
everything I found, and what the system does about each.

| # | What's wrong | Where | What happens |
|---|---|---|---|
| 1 | `ep_9001` and `ep_0004` both claim `(content_group=motis-many-lives-s01e02, language=hi)` — the same season/episode slot, with **contradictory titles** ("Rain on the Roof" vs "The Lost Kite (v2)") | Moti's Many Lives S1E2 | It violates two constraints at once — `(content_group, language)` and `(season, episode_number, language)` — and the slot one fires first, so that is what the message names. Either way the database refuses it: the importer keeps the first row, records the second in `import_rejects` with a plain-language reason, and it appears on the Publish page under "Import conflicts". |
| 2 | `ep_0036` is `published` with `artwork_available: []` | Discover India with Moti S1E4 | **Blocking** validation error. Publish refuses until it's fixed or unpublished. |
| 3 | `rhyme-rangers` has `section: null` | Rhyme Rangers | All 8 of its episodes are drafts, so the show is a draft too — a **warning**, not a blocker. It can't be published until a section is set. |
| 4 | Season 0 trailers carry only a `thumbnail` | Moti's Many Lives, Tiny Tales | Correct, given the artwork rule below. They're kept in `trailers`, never rendered as "Season 0". |
| 5 | `number-nest` has 2 of 8 episodes in draft | Number Nest | Normal. Publishes with 6. |
| 6 | `peblo-songs-lyrical` duplicates every episode title from `peblo-songs` | Songs | **Not** a defect — it's the read-along version, different categories and a different `content_group` prefix, so nothing collapses. Left alone. |
| 7 | Language coverage is partial: 18 of 76 groups have Hindi, 58 are English-only | Everywhere | Not a defect. Drives the `languages` list per entry. |

Run `docker compose logs api` after a fresh boot — the seeder prints all of this.

**Why the seed still produces a working viewer.** Defect 2 is a genuine blocker, so a
first publish would refuse and a reviewer would open an empty viewer. The seeder instead
does a `force` publish with a recorded reason: everything that validates goes live, the
one broken episode is excluded, and the exclusion is visible in the run history and on
the Publish page. That felt more honest than either quietly fixing the row or shipping an
empty app.

---

## Decisions I made where the brief was open

**Which artwork is required, per surface.** An episode needs a **thumbnail**; a show
needs a **poster and a banner**. That maps exactly to where each is used — poster in the
browse rows, banner in the hero, thumbnail in the episode list. Requiring all three on
every episode would block the trailers over artwork nothing renders.

**Show status is derived at import.** `seed_shows.json` carries status per episode, not
per show. A show is published if any of its episodes is and it has a section.

**Two severities, not one.** `blocking` (published content that can't be represented in
the catalogue) refuses the publish. `warning` (a draft show with no section, an import
conflict) doesn't. Without the split, one incomplete draft would hold the whole
catalogue hostage; without blocking at all, an editor's "published" episode would
silently never appear.

**Forced publish exists, but it costs something.** Admin only, requires a written reason,
and both the reason and the list of excluded items land in the run record. Real content
teams do have 6pm launches with artwork arriving tomorrow.

**Categories are a Postgres array with a GIN index**, not a join table. Small fixed
vocabulary from `reference.json`, always read with the show, only ever queried by
containment. A join table would never be queried on its own.

**`reference.json` is served to the CMS at `GET /reference`**, so the dropdowns and the
upload hints can't drift from the rules the server enforces.

---

## API

Public (no token — the viewer uses only these):

```
GET  /catalog                       the published document, ETag = publish checksum
GET  /catalog/search?q=&category=&language=&section=&kind=
GET  /catalog/shows/{slug}
```

Editor or admin:

```
GET/POST/PATCH/DELETE  /admin/shows[/{id}]     ?q=&section=&status=&language=&category=&page=
POST                   /admin/shows/{id}/seasons
POST/PATCH/DELETE      /admin/episodes[/{id}]
GET                    /admin/episodes/{id}/group      other language variants
POST/DELETE            /admin/artwork/{show|episode}/{id}/{poster|banner|thumbnail}
GET                    /admin/validation-report
GET                    /admin/catalog/runs
POST                   /admin/catalog/publish/dry-run
```

Admin only:

```
POST  /admin/catalog/publish            {force, force_reason}
POST  /admin/catalog/rollback/{run_id}
```

Errors are `{error, problem, fix}` — one sentence on what went wrong, one on what to do.
The CMS renders `problem` in red and `fix` underneath.

---

## Schema

```
shows ──< seasons ──< episodes
  │                      │
  └──────────┬───────────┘
       artworks (owner_type, owner_id, kind)

publish_runs ──< catalog_entries        import_rejects        users
```

Indexes that earn their place:

| Index | Why |
|---|---|
| `uq_episodes_group_language` — **partial**, `WHERE content_group IS NOT NULL` | The rule from the brief. Partial because `NULL` means "ungrouped"; a plain unique index would allow exactly one ungrouped episode per language in the whole catalogue. |
| `uq_publish_runs_current` — **partial**, `WHERE is_current` | Makes "two live catalogues at once" unrepresentable rather than merely unlikely. |
| `ix_shows_status`, `ix_shows_section_sort` | The publish job's driving query and the CMS list ordering. |
| `ix_catalog_entries_run*` | Every search pins the run first, so `run_id` leads. |
| `ix_catalog_entries_search_trgm` (GIN, `gin_trgm_ops`) | Makes `ILIKE '%kite%'` an index scan. |
| `*_categories/languages` (GIN) | `categories @> '{music}'` — the two composable filters. |

Migrations are hand-written, not autogenerated, so the partial indexes and the `pg_trgm`
extension are explicit. CI runs `upgrade → downgrade → upgrade` on every commit.

---

## Part E — written

### How publishing is atomic, and what happens if the process dies mid-publish

Nothing ever overwrites the live file. A publish writes to an **immutable, run-scoped
key** (`catalog/versions/<run_id>.json`) that nothing is serving, reads those bytes back
and compares them to what it built, and only then moves the pointer — a single database
transaction that clears `is_current` on the old run, sets it on the new one, and inserts
the new run's search rows. Readers resolve the pointer, so the cutover is one committed
row update. A partial unique index on `is_current` means two live runs can't exist even
if the code were wrong.

If the process dies:

- **Before the pointer moves** — the versioned object is orphaned garbage that nothing
  references, and viewers stay on the previous catalogue. The run sits in `running`;
  startup reaps anything older than 15 minutes into `failed` with an explanation.
- **During the pointer move** — it's one transaction, so it either happened or it didn't.
- **After the commit, before the CDN mirror** — the mirror write is best-effort and
  logged; `GET /catalog` resolves the database pointer, so the product is fine and only
  the static convenience copy is stale.

Two admins pressing Publish simultaneously is serialised by a Postgres advisory lock
held on its own connection (not the ORM session's — publish commits several times, and a
pooled connection handed back mid-run would carry a session-level lock to whatever
request checked it out next). The loser gets a 409 that says to try again.

Publishing is idempotent: `generated_at` and `run_id` are excluded from the content
checksum, so re-publishing unchanged content writes nothing, leaves the pointer alone,
and records the run as `unchanged`.

### The storage abstraction: what changes to move to Cloudflare R2

`STORAGE_BACKEND=r2` plus four credentials. That's the whole change.

`app/storage/base.py` is a six-method ABC; `get_storage()` is the one function that knows
which subclass exists. Nothing above it imports boto3 or touches a path.
`LocalStorage.put_atomic` writes to a temp file in the same directory, fsyncs, and
`os.replace`s; `R2Storage.put_atomic` is just `put`, because R2's PutObject is already
atomic per key. `app/storage/r2.py` is written and ready — it isn't exercised by the
compose stack, which is the honest caveat.

Two things beyond the class: `STORAGE_PUBLIC_BASE_URL` becomes the bucket/CDN origin
(artwork URLs are stored absolute), and the API stops mounting `/media`, so it leaves the
image path entirely. Artwork keys are content-addressed (`artwork/<kind>/<sha256>`), so
they're immutable, deduplicated across owners, and safe to serve with a one-year cache.

### Search: how, where it breaks, what's next

Search runs against `catalog_entries` — a flattened, published-only table the publish job
writes **inside the pointer-swap transaction**. That's the important part: querying the
`shows` table directly would happily return an episode someone flipped to "published" in
the CMS five minutes ago, and the viewer would follow the link into a 404. Filters
compose as SQL (`categories @> '{x}'`, `languages @> '{y}'`, `section =`), and `q` is
`ILIKE '%term%'` over a denormalised `search_text`, index-backed by a `pg_trgm` GIN
index. Substring rather than word matching, because a child types "kite", not "kites".

**Where it stops working:** trigram indexes are fine to roughly 10⁵–10⁶ rows. The first
thing to go is ranking, not speed — `ILIKE` has no notion of relevance, so the ordering
is a title-prefix boost and then the editor's `sort_index`. That's adequate at 76 entries
and obviously wrong at 50,000, where "kite" would return a hundred equally-ranked things.

**Next:** add a stored `tsvector` with weighted fields (title > synopsis > category) and
rank with `ts_rank_cd`, keeping the trigram index for typo and prefix tolerance. Past a
few hundred thousand entries, or the first time someone asks for "did you mean" or
multilingual stemming for Hindi, move to a real search engine (Typesense/Meilisearch)
fed by the publish job — the publish job is already the single write point, so that's an
additive change, not a rewrite.

### Why serve a pre-published file at all

Four reasons: the viewer can't see half-finished editing; a catalogue read is one object
fetch that a CDN can serve without touching Postgres; a checksum makes ETag/304
revalidation nearly free; and a bad publish is undone by moving a pointer rather than by
restoring a database.

**Where it bites.** Publishing is now an explicit act someone must remember — "I changed
it and it's not live" is a support question this design creates. Everything is
all-or-nothing, so one urgent typo fix republishes the world. The document is a single
blob, so at a few thousand shows the viewer downloads far more than the home screen
needs (the fix is splitting it: a small home document plus per-show documents, which the
build already has the shape for). And there are two sources of truth to keep honest —
which is exactly why search reads `catalog_entries` and not `shows`, and why `/catalog`
serves stored bytes rather than rebuilding.

### What I left out, and the AI question

**Left out, deliberately:** no video playback (the viewer's play buttons are inert —
`video_url` is seeded but there are no media files); no user management UI (accounts come
from the seeder); no image resizing on upload — we reject and tell the editor how to
re-export, because silently re-encoding a designer's artwork is worse than a clear error;
no orphaned-object sweep (content-addressed keys are never deleted, so storage grows —
it needs a mark-and-sweep against `artworks.storage_key`); no rate limiting; no
pagination on `/admin/catalog/runs` beyond a limit. The R2 backend is written but
unexercised. `catalog_entries` rows accumulate per run and want pruning past the last
handful.

**Stretch items that are in:** versioned catalogue with **rollback** (a pointer move —
nearly free given the design), and a **publish dry-run** showing a diff of what would
change. No audit log of who changed what.

**AI tools.** I used Claude throughout — for scaffolding the CRUD routes and the React
pages, for the migration boilerplate, and as a reviewer on the publish logic. What I
accepted: the routine shape of the routers, the TanStack Query wiring, the CSS. What I
rejected or rewrote: its first publish implementation overwrote `catalog.json` in place,
which is explicitly on the list of things that count against you here — the versioned
key plus pointer swap is the correction. It also reached for `pg_try_advisory_lock` on
the ORM session's connection, which leaks the lock into the connection pool across the
mid-publish commits; that became a dedicated connection. And its first pass at artwork
errors read like HTTP status codes, which is the opposite of the brief. The judgment
calls in "Decisions I made" are mine.

---

## Operability

**Health.** `GET /health` touches Postgres and does a real storage round-trip, and
reports the current catalogue's run id and age. A check that only proves the process is
alive tells you nothing the load balancer didn't already know.

**The one thing I'd alert on: catalogue age.** Page when
`health.checks.catalog.age_seconds` exceeds ~26 hours, or when `catalog.ok` is false.

Why that one: every other failure here is already loud. A dead database 500s, a failed
publish shows up in the run history and in the response to the person who pressed the
button. The dangerous failure is the *silent* one — publishing quietly stopping working
while the last good catalogue keeps being served perfectly. Viewers see a working app,
the CMS looks fine, and nobody notices until someone asks why last week's episode still
isn't live. Catalogue age is the one number that catches "the pipeline is broken but
nothing is on fire". The threshold is a bit over a day because Peblo publishes daily —
it should be set from the actual cadence, not from a round number.

Also worth a lower-priority alert: publish runs stuck in `running` (the reaper marks
them failed, but a rising count means something is killing the process mid-publish), and
`5xx` rate on `/admin/artwork/*` (an editor who can't upload is an editor who can't work).

**Secrets.** `.env.example` lists every variable the stack reads. `.env` is git-ignored
and only ever holds throwaway local values. In production: `JWT_SECRET` and the R2
credentials come from the platform's secret manager (AWS Secrets Manager / Doppler /
Fly secrets) injected as env vars at container start, never baked into an image and never
in the repo. `JWT_SECRET` is the one worth care — anyone holding it can mint an admin
token, so it's rotated on a schedule and immediately if anyone with access leaves;
rotation means accepting both old and new for one token lifetime. R2 keys are scoped to
the one bucket with no delete permission for the API's key. The two frontends are the
awkward case: Vite inlines `VITE_*` at **build** time, so the API URL is a build arg and
each environment gets its own image — nothing secret ever belongs in those bundles,
because everything in them is public.

---

## Time spent

| | |
|---|---|
| Reading the brief, analysing the seed data, finding the defects | ~1h |
| Part A — schema, migrations, storage, artwork, publish, search, auth | ~5h |
| Part B — CMS | ~3h |
| Part C — viewer | ~2h |
| Part D — compose, CI, health | ~1.5h |
| Tests | ~1.5h |
| Part E / README | ~1h |

## Layout

```
api/     FastAPI. app/services/ holds publish, catalog_builder, validation, artwork.
cms/     React + TS + TanStack Query. Editor-facing.
viewer/  React + TS. Reads only /catalog*.
data/    reference.json, seed_shows.json, assets/ — mounted read-only.
```
