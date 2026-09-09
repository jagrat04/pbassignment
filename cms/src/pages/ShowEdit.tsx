import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { ArtworkSlot } from "../ArtworkSlot";
import { Empty, ErrorNotice, Field, Loading, StatusPill, formatDuration } from "../components";
import { useReference } from "../useReference";
import type { ArtworkKind, Episode, Season, ShowDetail } from "../types";

const ARTWORK_HELP: Record<ArtworkKind, string> = {
  poster: "Shown in the browse rows on the home screen.",
  banner: "Shown behind the featured show at the top of the home screen.",
  thumbnail: "Shown next to each episode in the episode list.",
};

export function ShowEdit() {
  const { showId } = useParams();
  const isNew = showId === "new";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const reference = useReference();

  const query = useQuery({
    queryKey: ["show", showId],
    queryFn: () => api<ShowDetail>(`/admin/shows/${showId}`),
    enabled: !isNew,
  });

  const [form, setForm] = useState({
    slug: "",
    title: "",
    synopsis: "",
    section: "",
    categories: [] as string[],
    status: "draft" as "draft" | "published",
    sort_index: 0,
  });

  useEffect(() => {
    if (query.data) {
      setForm({
        slug: query.data.slug,
        title: query.data.title,
        synopsis: query.data.synopsis ?? "",
        section: query.data.section ?? "",
        categories: query.data.categories,
        status: query.data.status,
        sort_index: query.data.sort_index,
      });
    }
  }, [query.data]);

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        title: form.title,
        synopsis: form.synopsis || null,
        section: form.section || null,
        categories: form.categories,
        status: form.status,
        sort_index: form.sort_index,
      };
      if (isNew) {
        return api<{ id: string }>("/admin/shows", {
          method: "POST",
          body: { ...body, slug: form.slug },
        });
      }
      return api<{ id: string }>(`/admin/shows/${showId}`, { method: "PATCH", body });
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["shows"] });
      qc.invalidateQueries({ queryKey: ["show", showId] });
      qc.invalidateQueries({ queryKey: ["validation"] });
      if (isNew) navigate(`/shows/${res.id}`);
    },
  });

  if (!isNew && query.isPending) {
    return (
      <div className="page">
        <Loading rows={8} label="Loading show" />
      </div>
    );
  }
  if (!isNew && query.isError) {
    return (
      <div className="page">
        <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
        <Link to="/shows">Back to shows</Link>
      </div>
    );
  }

  const show = query.data;
  const saveError = save.error instanceof ApiError ? save.error : null;
  const specs = reference.data?.artwork_specs;

  return (
    <div className="page">
      <p className="small">
        <Link to="/shows">← Shows</Link>
      </p>
      <div className="spread">
        <div>
          <h1>{isNew ? "New show" : form.title || show?.title}</h1>
          <p className="sub mono">{form.slug || "—"}</p>
        </div>
        {show && <StatusPill status={show.status} />}
      </div>

      {saveError && (
        <div className="notice error">
          <strong>{saveError.problem}</strong>
          {saveError.fix && <p className="fix">{saveError.fix}</p>}
        </div>
      )}
      {save.isSuccess && !save.isPending && !isNew && (
        <div className="notice ok">
          <strong>Saved.</strong>
          <p className="fix">
            Changes go live the next time an admin publishes the catalogue.
          </p>
        </div>
      )}

      <div className="panel">
        <h2>Details</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Field label="Title">
              <input
                type="text"
                required
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
              />
            </Field>
            <Field
              label="URL slug"
              hint={isNew ? "Lowercase letters, numbers and hyphens. Can't be changed later." : "Fixed once created."}
              error={saveError?.field === "slug" ? saveError.problem : undefined}
            >
              <input
                type="text"
                required
                disabled={!isNew}
                pattern="[a-z0-9]+(-[a-z0-9]+)*"
                value={form.slug}
                onChange={(e) => setForm({ ...form, slug: e.target.value })}
              />
            </Field>
          </div>

          <Field label="Synopsis" hint="One or two sentences. Shown on the show page.">
            <textarea
              rows={3}
              value={form.synopsis}
              onChange={(e) => setForm({ ...form, synopsis: e.target.value })}
            />
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Field
              label="Section"
              hint="Which row this show appears in on the home screen. Required to publish."
              error={saveError?.field === "section" ? saveError.problem : undefined}
            >
              <select
                value={form.section}
                onChange={(e) => setForm({ ...form, section: e.target.value })}
              >
                <option value="">— none —</option>
                {reference.data?.sections.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Row order" hint="Lower numbers appear first inside the section.">
              <input
                type="number"
                value={form.sort_index}
                onChange={(e) => setForm({ ...form, sort_index: Number(e.target.value) })}
              />
            </Field>
          </div>

          <Field label="Categories" hint="What viewers filter by. Pick as many as apply.">
            <div className="row">
              {reference.data?.categories.map((c) => {
                const on = form.categories.includes(c);
                return (
                  <button
                    type="button"
                    key={c}
                    className={on ? "primary" : ""}
                    style={{ padding: "4px 10px", fontSize: 13 }}
                    onClick={() =>
                      setForm({
                        ...form,
                        categories: on
                          ? form.categories.filter((x) => x !== c)
                          : [...form.categories, c],
                      })
                    }
                  >
                    {c}
                  </button>
                );
              })}
            </div>
          </Field>

          <Field
            label="Status"
            hint="A published show needs a section, a poster and a banner before the catalogue will go out."
          >
            <select
              value={form.status}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as "draft" | "published" })
              }
            >
              <option value="draft">Draft — not in the catalogue</option>
              <option value="published">Published — goes out on the next publish</option>
            </select>
          </Field>

          <button className="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : isNew ? "Create show" : "Save changes"}
          </button>
        </form>
      </div>

      {isNew ? (
        <div className="notice info">
          <strong>Artwork and episodes come next.</strong>
          <p className="fix">Create the show first, then its upload slots appear here.</p>
        </div>
      ) : (
        show &&
        specs && (
          <>
            <div className="panel">
              <h2>Show artwork</h2>
              <p className="sub">
                The poster and banner are required before this show can be published.
              </p>
              <div className="slots">
                {(["poster", "banner"] as ArtworkKind[]).map((kind) => (
                  <div key={kind}>
                    <ArtworkSlot
                      kind={kind}
                      spec={specs[kind]}
                      ownerType="show"
                      ownerId={show.id}
                      required
                      current={show.artwork.find((a) => a.kind === kind)}
                    />
                    <p className="small muted" style={{ margin: "6px 2px 0" }}>
                      {ARTWORK_HELP[kind]}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <Seasons show={show} trailerSeason={reference.data?.trailer_season ?? 0} />
          </>
        )
      )}
    </div>
  );
}

function Seasons({ show, trailerSeason }: { show: ShowDetail; trailerSeason: number }) {
  if (show.seasons.length === 0) {
    return (
      <div className="panel">
        <h2>Episodes</h2>
        <Empty title="No seasons yet." hint="Add a season, then add episodes to it." />
      </div>
    );
  }
  return (
    <>
      {show.seasons.map((season) => (
        <SeasonPanel
          key={season.id}
          season={season}
          showId={show.id}
          isTrailers={season.season_number === trailerSeason}
        />
      ))}
    </>
  );
}

function SeasonPanel({
  season,
  showId,
  isTrailers,
}: {
  season: Season;
  showId: string;
  isTrailers: boolean;
}) {
  // Language variants of one episode share a content_group. Grouping them in
  // the table is the only way an editor can see at a glance that the Hindi
  // version exists — which is exactly what the catalogue collapses on.
  const groups = new Map<string, Episode[]>();
  for (const ep of season.episodes) {
    const key = ep.content_group ?? `solo:${ep.id}`;
    groups.set(key, [...(groups.get(key) ?? []), ep]);
  }

  return (
    <div className="panel">
      <div className="spread">
        <h2 style={{ margin: 0 }}>
          {season.title ?? `Season ${season.season_number}`}{" "}
          {isTrailers && <span className="pill plain">trailers — not a season in the app</span>}
        </h2>
        <span className="small muted">{season.episodes.length} rows</span>
      </div>

      <table style={{ marginTop: 12 }}>
        <thead>
          <tr>
            <th style={{ width: 84 }} />
            <th style={{ width: 44 }}>#</th>
            <th>Episode</th>
            <th style={{ width: 130 }}>Languages</th>
            <th style={{ width: 80 }}>Length</th>
            <th style={{ width: 100 }}>Status</th>
            <th style={{ width: 90 }} />
          </tr>
        </thead>
        <tbody>
          {[...groups.values()]
            .sort((a, b) => a[0].episode_number - b[0].episode_number)
            .map((variants) => {
              const primary = variants[0];
              const thumb = variants
                .flatMap((v) => v.artwork)
                .find((a) => a.kind === "thumbnail");
              const blocked = variants.flatMap((v) => v.blocking_issues);
              return (
                <tr key={primary.id}>
                  <td>
                    {thumb ? (
                      <img
                        src={thumb.url}
                        alt=""
                        loading="lazy"
                        style={{ width: 72, height: 40, objectFit: "cover", borderRadius: 4 }}
                      />
                    ) : (
                      <div
                        style={{ width: 72, height: 40, borderRadius: 4, background: "#eceef1" }}
                      />
                    )}
                  </td>
                  <td>{primary.episode_number}</td>
                  <td>
                    <Link to={`/shows/${showId}/episodes/${primary.id}`} style={{ fontWeight: 600 }}>
                      {primary.title}
                    </Link>
                    {primary.content_group && (
                      <div className="small muted mono">{primary.content_group}</div>
                    )}
                    {blocked.length > 0 && (
                      <div style={{ marginTop: 4 }}>
                        {[...new Set(blocked)].map((b) => (
                          <span key={b} className="pill blocked" style={{ marginRight: 4 }}>
                            {b}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td>
                    {variants.map((v) => (
                      <span key={v.id} className="pill plain" style={{ marginRight: 4 }}>
                        {v.language}
                      </span>
                    ))}
                  </td>
                  <td>{formatDuration(primary.duration_seconds)}</td>
                  <td>
                    <StatusPill status={primary.status} />
                  </td>
                  <td className="right">
                    <Link to={`/shows/${showId}/episodes/${primary.id}`}>
                      <button style={{ padding: "4px 10px", fontSize: 13 }}>Edit</button>
                    </Link>
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
