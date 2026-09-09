import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { fetchJson } from "../api";
import { Art, EmptyState, duration } from "../components";
import type { CatalogEpisode, CatalogShow } from "../types";

export function ShowDetail() {
  const { slug } = useParams();
  const [seasonIndex, setSeasonIndex] = useState(0);

  const show = useQuery({
    queryKey: ["show", slug],
    queryFn: () => fetchJson<CatalogShow>(`/catalog/shows/${slug}`),
    staleTime: 60_000,
  });

  if (show.isPending) {
    return (
      <div className="page">
        <div className="detail-head">
          <div className="art poster" />
          <div>
            <div className="art" style={{ height: 34, width: 260, borderRadius: 8 }} />
          </div>
        </div>
      </div>
    );
  }

  if (show.isError) {
    return (
      <div className="page">
        <EmptyState
          title="We couldn't find that show."
          hint="It may have been taken down. Have a look at what's on instead."
        />
        <p style={{ textAlign: "center" }}>
          <Link to="/">
            <button className="btn">Back to Peblo TV</button>
          </Link>
        </p>
      </div>
    );
  }

  const data = show.data;
  // Trailers arrive on their own field, never inside `seasons`, so "Season 0"
  // cannot appear in this tab bar even if the data changes shape later.
  const season = data.seasons[seasonIndex];

  return (
    <div className="page">
      <div className="detail-head">
        <Art src={data.artwork.poster?.url} alt={data.title} shape="poster" eager />
        <div>
          <h1>{data.title}</h1>
          <p className="muted">
            {data.episode_count} episode{data.episode_count === 1 ? "" : "s"}
            {data.seasons.length > 1 && ` · ${data.seasons.length} seasons`}
          </p>
          {data.synopsis && <p style={{ maxWidth: 620 }}>{data.synopsis}</p>}
          <div className="chips">
            {data.categories.map((c) => (
              <span className="chip" key={c}>
                {c}
              </span>
            ))}
            {data.languages.map((l) => (
              <span className="chip lang" key={l}>
                {l}
              </span>
            ))}
          </div>

          {data.trailers.length > 0 && (
            <div style={{ marginTop: 14 }}>
              {data.trailers.map((t) => (
                <button className="btn ghost" key={t.id} style={{ marginRight: 8 }}>
                  ▶ {t.title}
                  {t.duration_seconds ? ` · ${duration(t.duration_seconds)}` : ""}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {data.seasons.length === 0 ? (
        <EmptyState title="No episodes are available yet." />
      ) : (
        <>
          {data.seasons.length > 1 && (
            <div className="tabs" role="tablist">
              {data.seasons.map((s, i) => (
                <button
                  key={s.season_number}
                  role="tab"
                  aria-selected={i === seasonIndex}
                  onClick={() => setSeasonIndex(i)}
                >
                  {s.title}
                </button>
              ))}
            </div>
          )}

          <div>
            {season?.episodes.map((ep) => (
              <EpisodeRow key={ep.id} episode={ep} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function EpisodeRow({ episode }: { episode: CatalogEpisode }) {
  const [language, setLanguage] = useState(episode.languages[0]);
  const variant = episode.variants.find((v) => v.language === language) ?? episode.variants[0];

  return (
    <div className="episode">
      {/* Episode lists use the 16:9 thumbnail. */}
      <Art src={episode.artwork.thumbnail?.url} alt={episode.title} shape="thumb" />
      <div>
        <h3>
          {episode.episode_number}. {variant?.title ?? episode.title}
        </h3>
        <p className="small muted" style={{ marginBottom: 6 }}>
          {duration(variant?.duration_seconds ?? episode.duration_seconds)}
        </p>
        {episode.synopsis && <p>{episode.synopsis}</p>}

        {episode.languages.length > 1 ? (
          <div className="chips" style={{ marginTop: 10, alignItems: "center" }}>
            <span className="small muted">Watch in:</span>
            {episode.languages.map((l) => (
              <button
                key={l}
                className="chip lang"
                aria-pressed={l === language}
                style={{
                  cursor: "pointer",
                  background: l === language ? "var(--brand)" : undefined,
                  color: l === language ? "var(--brand-ink)" : undefined,
                }}
                onClick={() => setLanguage(l)}
              >
                {l}
              </button>
            ))}
          </div>
        ) : (
          <div className="chips" style={{ marginTop: 10 }}>
            <span className="chip lang">{episode.languages[0]}</span>
          </div>
        )}
      </div>
    </div>
  );
}
