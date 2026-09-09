import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchJson } from "../api";
import { Art, EmptyState, RailSkeleton, ShowCard } from "../components";
import type { Catalog } from "../types";

export function Home() {
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: () => fetchJson<Catalog>("/catalog"),
    staleTime: 60_000,
  });

  if (catalog.isPending) {
    return (
      <main>
        <div className="hero">
          <div className="art banner" />
          <div className="scrim" />
        </div>
        <div className="section">
          <h2 className="muted">Loading…</h2>
          <RailSkeleton />
        </div>
      </main>
    );
  }

  if (catalog.isError) {
    return (
      <main>
        <EmptyState
          title="Peblo TV isn't available right now."
          hint="Nothing has been published yet, or the service is starting up. Try again in a moment."
        />
      </main>
    );
  }

  const bySlug = new Map(catalog.data.shows.map((s) => [s.slug, s]));
  const hero = catalog.data.hero;

  if (catalog.data.shows.length === 0) {
    return (
      <main>
        <EmptyState title="Nothing to watch yet." hint="New stories are on their way." />
      </main>
    );
  }

  return (
    <main>
      {hero && (
        <section className="hero">
          {/* The hero is the 16:9 banner surface — never the poster. */}
          <Art src={hero.banner.url} alt={hero.title} shape="banner" eager />
          <div className="scrim" />
          <div className="copy">
            <h1>{hero.title}</h1>
            {hero.synopsis && <p>{hero.synopsis}</p>}
            <div className="chips" style={{ marginBottom: 18 }}>
              {hero.categories.map((c) => (
                <span className="chip" key={c}>
                  {c}
                </span>
              ))}
              {hero.languages.map((l) => (
                <span className="chip lang" key={l}>
                  {l}
                </span>
              ))}
            </div>
            <Link to={`/shows/${hero.slug}`}>
              <button className="btn">Watch now</button>
            </Link>
          </div>
        </section>
      )}

      {catalog.data.sections.map((section) => (
        <section className="section" key={section.key}>
          <h2>{section.title}</h2>
          <div className="rail">
            {section.show_slugs.map((slug) => {
              const show = bySlug.get(slug);
              return show ? <ShowCard key={slug} show={show} /> : null;
            })}
          </div>
        </section>
      ))}
    </main>
  );
}
