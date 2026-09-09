import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api";
import { ArtworkSlot } from "../ArtworkSlot";
import { ErrorNotice, Field, Loading, StatusPill } from "../components";
import { useReference } from "../useReference";
import type { Episode, ShowDetail } from "../types";

interface GroupInfo {
  content_group: string | null;
  variants: { id: string; language: string; title: string; status: string; is_self: boolean }[];
}

export function EpisodeEdit() {
  const { showId, episodeId } = useParams();
  const qc = useQueryClient();
  const reference = useReference();

  const show = useQuery({
    queryKey: ["show", showId],
    queryFn: () => api<ShowDetail>(`/admin/shows/${showId}`),
  });

  const episode: Episode | undefined = show.data?.seasons
    .flatMap((s) => s.episodes)
    .find((e) => e.id === episodeId);

  const group = useQuery({
    queryKey: ["episode-group", episodeId],
    queryFn: () => api<GroupInfo>(`/admin/episodes/${episodeId}/group`),
    enabled: Boolean(episodeId),
  });

  const [form, setForm] = useState({
    title: "",
    synopsis: "",
    minutes: 0,
    seconds: 0,
    language: "en",
    content_group: "",
    status: "draft" as "draft" | "published",
  });

  useEffect(() => {
    if (episode) {
      setForm({
        title: episode.title,
        synopsis: episode.synopsis ?? "",
        minutes: Math.floor((episode.duration_seconds ?? 0) / 60),
        seconds: (episode.duration_seconds ?? 0) % 60,
        language: episode.language,
        content_group: episode.content_group ?? "",
        status: episode.status,
      });
    }
  }, [episode]);

  const save = useMutation({
    mutationFn: async () =>
      api<{ id: string }>(`/admin/episodes/${episodeId}`, {
        method: "PATCH",
        body: {
          title: form.title,
          synopsis: form.synopsis || null,
          duration_seconds: form.minutes * 60 + form.seconds || null,
          language: form.language,
          content_group: form.content_group || null,
          status: form.status,
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["show", showId] });
      qc.invalidateQueries({ queryKey: ["episode-group", episodeId] });
      qc.invalidateQueries({ queryKey: ["validation"] });
    },
  });

  if (show.isPending) {
    return (
      <div className="page">
        <Loading rows={6} label="Loading episode" />
      </div>
    );
  }
  if (show.isError) {
    return (
      <div className="page">
        <ErrorNotice error={show.error} onRetry={() => show.refetch()} />
      </div>
    );
  }
  if (!episode) {
    return (
      <div className="page">
        <div className="notice error">
          <strong>That episode isn't part of this show any more.</strong>
          <p className="fix">It may have been deleted or moved.</p>
        </div>
        <Link to={`/shows/${showId}`}>Back to the show</Link>
      </div>
    );
  }

  const err = save.error instanceof ApiError ? save.error : null;
  const spec = reference.data?.artwork_specs.thumbnail;
  const siblings = group.data?.variants.filter((v) => !v.is_self) ?? [];

  return (
    <div className="page">
      <p className="small">
        <Link to={`/shows/${showId}`}>← {show.data.title}</Link>
      </p>
      <div className="spread">
        <div>
          <h1>{form.title || episode.title}</h1>
          <p className="sub">
            Episode {episode.episode_number} · {episode.language}
          </p>
        </div>
        <StatusPill status={episode.status} />
      </div>

      {episode.blocking_issues.length > 0 && (
        <div className="notice error">
          <strong>
            This episode is published but won't reach viewers: {episode.blocking_issues.join(", ").toLowerCase()}.
          </strong>
          <p className="fix">Fix it below, or set the episode back to draft.</p>
        </div>
      )}
      {err && (
        <div className="notice error">
          <strong>{err.problem}</strong>
          {err.fix && <p className="fix">{err.fix}</p>}
        </div>
      )}
      {save.isSuccess && !save.isPending && (
        <div className="notice ok">
          <strong>Saved.</strong>
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
          <Field label="Title">
            <input
              type="text"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
            />
          </Field>

          <Field label="Synopsis">
            <textarea
              rows={2}
              value={form.synopsis}
              onChange={(e) => setForm({ ...form, synopsis: e.target.value })}
            />
          </Field>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Field label="Run time" hint="Required before this episode can be published.">
              <div className="row" style={{ flexWrap: "nowrap" }}>
                <input
                  type="number"
                  min={0}
                  value={form.minutes}
                  onChange={(e) => setForm({ ...form, minutes: Number(e.target.value) })}
                />
                <span className="small muted">min</span>
                <input
                  type="number"
                  min={0}
                  max={59}
                  value={form.seconds}
                  onChange={(e) => setForm({ ...form, seconds: Number(e.target.value) })}
                />
                <span className="small muted">sec</span>
              </div>
            </Field>

            <Field label="Language">
              <select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
              >
                {reference.data?.languages.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field
            label="Content group"
            hint="Episodes sharing a content group are the same episode in different languages. Viewers see one entry with a language switch."
            error={err?.field === "content_group" ? err.problem : undefined}
          >
            <input
              type="text"
              className="mono"
              value={form.content_group}
              onChange={(e) => setForm({ ...form, content_group: e.target.value })}
            />
          </Field>

          {siblings.length > 0 && (
            <div className="notice info" style={{ marginTop: -6 }}>
              <strong>
                This episode is grouped with {siblings.length} other version
                {siblings.length === 1 ? "" : "s"}:
              </strong>
              <p className="fix">
                {siblings.map((v) => (
                  <span key={v.id} style={{ marginRight: 10 }}>
                    <Link to={`/shows/${showId}/episodes/${v.id}`}>
                      {v.language} — {v.title}
                    </Link>{" "}
                    <span className="small">({v.status})</span>
                  </span>
                ))}
              </p>
            </div>
          )}

          <Field label="Status">
            <select
              value={form.status}
              onChange={(e) =>
                setForm({ ...form, status: e.target.value as "draft" | "published" })
              }
            >
              <option value="draft">Draft</option>
              <option value="published">Published</option>
            </select>
          </Field>

          <button className="primary" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save changes"}
          </button>
        </form>
      </div>

      {spec && (
        <div className="panel">
          <h2>Episode thumbnail</h2>
          <p className="sub">Required before this episode can be published.</p>
          <div className="slots">
            <ArtworkSlot
              kind="thumbnail"
              spec={spec}
              ownerType="episode"
              ownerId={episode.id}
              required
              current={episode.artwork.find((a) => a.kind === "thumbnail")}
            />
          </div>
        </div>
      )}
    </div>
  );
}
