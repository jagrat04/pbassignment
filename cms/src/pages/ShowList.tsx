import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Empty, ErrorNotice, Loading, StatusPill, formatWhen } from "../components";
import { useReference } from "../useReference";
import type { Paged, ShowSummary } from "../types";

export function ShowList() {
  const [params, setParams] = useSearchParams();
  const reference = useReference();

  const q = params.get("q") ?? "";
  const section = params.get("section") ?? "";
  const status = params.get("status") ?? "";
  const language = params.get("language") ?? "";
  const page = Number(params.get("page") ?? 1);

  // Typing shouldn't fire a request per keystroke.
  const [draftQ, setDraftQ] = useState(q);

  function set(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }

  const query = useQuery({
    queryKey: ["shows", { q, section, status, language, page }],
    // Filters compose on the server; the URL is the single source of truth so a
    // filtered list is a link an editor can send to a colleague.
    queryFn: () =>
      api<Paged<ShowSummary>>(
        `/admin/shows?${new URLSearchParams({
          ...(q ? { q } : {}),
          ...(section ? { section } : {}),
          ...(status ? { status } : {}),
          ...(language ? { language } : {}),
          page: String(page),
          page_size: "20",
        })}`,
      ),
    placeholderData: keepPreviousData,
  });

  const hasFilters = Boolean(q || section || status || language);

  return (
    <div className="page">
      <div className="spread">
        <div>
          <h1>Shows</h1>
          <p className="sub">
            {query.data ? `${query.data.total} show${query.data.total === 1 ? "" : "s"}` : " "}
          </p>
        </div>
        <Link to="/shows/new">
          <button className="primary">New show</button>
        </Link>
      </div>

      <div className="panel">
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            set("q", draftQ);
          }}
        >
          <input
            type="search"
            className="grow"
            style={{ minWidth: 220 }}
            placeholder="Search show or episode title…"
            value={draftQ}
            onChange={(e) => setDraftQ(e.target.value)}
          />
          <select value={section} onChange={(e) => set("section", e.target.value)} style={{ width: 160 }}>
            <option value="">Any section</option>
            {reference.data?.sections.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select value={status} onChange={(e) => set("status", e.target.value)} style={{ width: 140 }}>
            <option value="">Any status</option>
            <option value="published">Published</option>
            <option value="draft">Draft</option>
          </select>
          <select value={language} onChange={(e) => set("language", e.target.value)} style={{ width: 140 }}>
            <option value="">Any language</option>
            {reference.data?.languages.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
          <button type="submit">Search</button>
          {hasFilters && (
            <button type="button" onClick={() => setParams(new URLSearchParams())}>
              Clear
            </button>
          )}
        </form>
      </div>

      <div className="panel">
        {query.isPending ? (
          <Loading rows={6} label="Loading shows" />
        ) : query.isError ? (
          <ErrorNotice error={query.error} onRetry={() => query.refetch()} />
        ) : query.data.items.length === 0 ? (
          <Empty
            title={hasFilters ? "No shows match those filters." : "No shows yet."}
            hint={
              hasFilters
                ? "Try a broader search, or clear the filters."
                : "Create the first show to get started."
            }
            action={
              hasFilters ? (
                <button onClick={() => setParams(new URLSearchParams())}>Clear filters</button>
              ) : (
                <Link to="/shows/new">
                  <button className="primary">New show</button>
                </Link>
              )
            }
          />
        ) : (
          <>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 54 }} />
                  <th>Show</th>
                  <th style={{ width: 110 }}>Section</th>
                  <th style={{ width: 90 }}>Episodes</th>
                  <th style={{ width: 110 }}>Languages</th>
                  <th style={{ width: 110 }}>Status</th>
                  <th style={{ width: 160 }}>Updated</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((show) => {
                  const poster = show.artwork.find((a) => a.kind === "poster");
                  return (
                    <tr key={show.id}>
                      <td>
                        {poster ? (
                          <img
                            src={poster.url}
                            alt=""
                            loading="lazy"
                            style={{ width: 34, height: 51, objectFit: "cover", borderRadius: 4 }}
                          />
                        ) : (
                          <div
                            style={{
                              width: 34,
                              height: 51,
                              borderRadius: 4,
                              background: "#eceef1",
                            }}
                          />
                        )}
                      </td>
                      <td>
                        <Link to={`/shows/${show.id}`} style={{ fontWeight: 600 }}>
                          {show.title}
                        </Link>
                        <div className="small muted mono">{show.slug}</div>
                        {show.blocking_issues.length > 0 && (
                          <div style={{ marginTop: 4 }}>
                            {show.blocking_issues.map((i) => (
                              <span key={i} className="pill blocked" style={{ marginRight: 4 }}>
                                {i}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td>
                        {show.section ? (
                          <span className="pill plain">{show.section}</span>
                        ) : (
                          <span className="pill warn">none</span>
                        )}
                      </td>
                      <td>{show.episode_count}</td>
                      <td>{show.languages.join(", ") || "—"}</td>
                      <td>
                        <StatusPill status={show.status} />
                      </td>
                      <td className="small muted">{formatWhen(show.updated_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {query.data.pages > 1 && (
              <div className="row" style={{ marginTop: 14, justifyContent: "flex-end" }}>
                <button disabled={page <= 1} onClick={() => set("page", String(page - 1))}>
                  Previous
                </button>
                <span className="small muted">
                  Page {query.data.page} of {query.data.pages}
                </span>
                <button
                  disabled={page >= query.data.pages}
                  onClick={() => set("page", String(page + 1))}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
