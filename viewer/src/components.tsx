import { useState } from "react";
import { Link } from "react-router-dom";
import type { CatalogShow, SearchResult } from "./types";

/**
 * Artwork that behaves when the network doesn't.
 *
 * The wrapper reserves the exact aspect ratio for the surface it is on, so the
 * layout is final before any bytes arrive — no reflow when a row of posters
 * loads one by one. Until then it shows a shimmer; if the image never arrives
 * it settles into the title on a flat tile rather than a broken-image icon.
 */
export function Art({
  src,
  alt,
  shape,
  eager,
}: {
  src: string | null | undefined;
  alt: string;
  shape: "poster" | "banner" | "thumb";
  eager?: boolean;
}) {
  const [state, setState] = useState<"loading" | "loaded" | "failed">(
    src ? "loading" : "failed",
  );

  return (
    <div className={`art ${shape}${state === "loading" ? "" : " loaded"}`}>
      {src && state !== "failed" && (
        <img
          src={src}
          alt={alt}
          className={state === "loaded" ? "shown" : ""}
          loading={eager ? "eager" : "lazy"}
          decoding="async"
          // The hero is the one image worth blocking a little for.
          fetchPriority={eager ? "high" : "auto"}
          onLoad={() => setState("loaded")}
          onError={() => setState("failed")}
        />
      )}
      {state === "failed" && <span className="fallback">{alt}</span>}
    </div>
  );
}

export function ShowCard({ show }: { show: CatalogShow }) {
  return (
    <Link className="card" to={`/shows/${show.slug}`}>
      {/* Posters in the rows — the 2:3 surface. */}
      <Art src={show.artwork.poster?.url} alt={show.title} shape="poster" />
      <div className="title">{show.title}</div>
      <div className="meta">
        {show.episode_count} episode{show.episode_count === 1 ? "" : "s"}
        {show.languages.length > 1 && ` · ${show.languages.join("/").toUpperCase()}`}
      </div>
    </Link>
  );
}

export function ResultCard({ result }: { result: SearchResult }) {
  const isShow = result.kind === "show";
  return (
    <Link className="card" style={{ width: "auto" }} to={`/shows/${result.slug}`}>
      <Art
        src={isShow ? result.poster?.url : result.thumbnail?.url}
        alt={result.title}
        shape={isShow ? "poster" : "thumb"}
      />
      <div className="title">{result.title}</div>
      <div className="meta">
        {isShow
          ? `${result.episode_count ?? 0} episodes`
          : result.is_trailer
            ? `Trailer · ${result.show_title}`
            : `S${result.season_number}E${result.episode_number} · ${result.show_title}`}
      </div>
    </Link>
  );
}

export function duration(seconds: number | null | undefined): string {
  if (!seconds) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {hint && <p>{hint}</p>}
    </div>
  );
}

export function RailSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="rail" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div className="card" key={i}>
          <div className="art poster" />
        </div>
      ))}
    </div>
  );
}
