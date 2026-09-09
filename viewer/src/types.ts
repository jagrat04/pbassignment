export interface ArtworkRef {
  url: string;
  width: number;
  height: number;
}

export interface Variant {
  episode_id: string;
  language: string;
  title: string;
  duration_seconds: number | null;
  video_url: string | null;
}

export interface CatalogEpisode {
  id: string;
  content_group: string | null;
  episode_number: number;
  title: string;
  synopsis: string | null;
  duration_seconds: number | null;
  is_trailer: boolean;
  artwork: { thumbnail: ArtworkRef | null };
  languages: string[];
  variants: Variant[];
}

export interface CatalogSeason {
  season_number: number;
  title: string;
  episodes: CatalogEpisode[];
}

export interface CatalogShow {
  id: string;
  slug: string;
  title: string;
  synopsis: string | null;
  section: string;
  categories: string[];
  languages: string[];
  artwork: { poster: ArtworkRef | null; banner: ArtworkRef | null };
  episode_count: number;
  seasons: CatalogSeason[];
  /** Season 0. Kept off `seasons` so it can never render as a normal season. */
  trailers: CatalogEpisode[];
  sort_index: number;
}

export interface Catalog {
  schema_version: number;
  run_id: string;
  generated_at: string;
  reference: { sections: string[]; categories: string[]; languages: string[] };
  hero: {
    slug: string;
    title: string;
    synopsis: string | null;
    banner: ArtworkRef;
    categories: string[];
    languages: string[];
  } | null;
  sections: { key: string; title: string; show_slugs: string[] }[];
  shows: CatalogShow[];
}

export interface SearchResult {
  kind: "show" | "episode";
  slug: string;
  title: string;
  show_title?: string;
  synopsis: string | null;
  categories: string[];
  languages: string[];
  poster?: ArtworkRef | null;
  thumbnail?: ArtworkRef | null;
  episode_count?: number;
  season_number?: number;
  episode_number?: number;
  duration_seconds?: number | null;
  is_trailer?: boolean;
}

export interface SearchResponse {
  query: string | null;
  total: number;
  limit: number;
  offset: number;
  results: SearchResult[];
}
