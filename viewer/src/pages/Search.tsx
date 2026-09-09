import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { fetchJson } from "../api";
import { EmptyState, ResultCard } from "../components";
import type { Catalog, SearchResponse } from "../types";

export function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const language = params.get("language") ?? "";

  // Only for the filter dropdowns — the catalogue already carries its own
  // vocabulary, so there is no second source of truth to drift.
  const catalog = useQuery({
    queryKey: ["catalog"],
    queryFn: () => fetchJson<Catalog>("/catalog"),
    staleTime: 60_000,
  });

  const results = useQuery({
    queryKey: ["search", q, category, language],
    // Searching on the server, over the published catalogue only. The
    // alternative — pulling the whole catalogue into the browser and filtering
    // it there — works fine at eight shows and falls over the moment there are
    // a few thousand; see the README.
    queryFn: () =>
      fetchJson<SearchResponse>(
        `/catalog/search?${new URLSearchParams({
          ...(q ? { q } : {}),
          ...(category ? { category } : {}),
          ...(language ? { language } : {}),
          limit: "60",
        })}`,
      ),
    enabled: Boolean(q || category || language),
    placeholderData: keepPreviousData,
  });

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  }

  const hasQuery = Boolean(q || category || language);

  return (
    <main>
      <div className="pillbar">
        <select value={category} onChange={(e) => set("category", e.target.value)}>
          <option value="">All categories</option>
          {catalog.data?.reference.categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={language} onChange={(e) => set("language", e.target.value)}>
          <option value="">Any language</option>
          {catalog.data?.reference.languages.map((l) => (
            <option key={l} value={l}>
              {l.toUpperCase()}
            </option>
          ))}
        </select>
        {hasQuery && (
          <button className="btn ghost" onClick={() => setParams(new URLSearchParams())}>
            Clear
          </button>
        )}
      </div>

      <div className="page">
        {!hasQuery ? (
          <EmptyState
            title="What are you looking for?"
            hint="Search for a show, an episode, or pick a category above."
          />
        ) : results.isPending ? (
          <div className="grid">
            {Array.from({ length: 10 }).map((_, i) => (
              <div className="art poster" key={i} />
            ))}
          </div>
        ) : results.isError ? (
          <EmptyState title="Search isn't working right now." hint="Try again in a moment." />
        ) : results.data.results.length === 0 ? (
          <EmptyState
            title={q ? `Nothing matches “${q}”.` : "Nothing matches those filters."}
            hint="Try a different word, or clear the filters to see everything."
          />
        ) : (
          <>
            <p className="muted small" style={{ paddingTop: 16 }}>
              {results.data.total} result{results.data.total === 1 ? "" : "s"}
            </p>
            <div className="grid">
              {results.data.results.map((r, i) => (
                <ResultCard key={`${r.kind}-${r.slug}-${i}`} result={r} />
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}
