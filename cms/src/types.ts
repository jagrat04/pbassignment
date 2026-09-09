export type Role = "editor" | "admin";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
}

export interface ArtworkSpec {
  aspect: string;
  target_px: [number, number];
  max_kb: number;
  min_px: [number, number];
}

export interface Reference {
  sections: string[];
  categories: string[];
  languages: string[];
  trailer_season: number;
  artwork_specs: Record<"poster" | "banner" | "thumbnail", ArtworkSpec>;
  conventions: Record<string, string>;
}

export type ArtworkKind = "poster" | "banner" | "thumbnail";

export interface Artwork {
  kind: ArtworkKind;
  url: string;
  width: number;
  height: number;
  bytes: number;
  original_filename: string | null;
}

export interface Episode {
  id: string;
  season_id: string;
  episode_number: number;
  title: string;
  synopsis: string | null;
  duration_seconds: number | null;
  language: string;
  content_group: string | null;
  status: "draft" | "published";
  video_url: string | null;
  artwork: Artwork[];
  blocking_issues: string[];
}

export interface Season {
  id: string;
  season_number: number;
  title: string | null;
  is_trailer_season: boolean;
  episodes: Episode[];
}

export interface ShowSummary {
  id: string;
  slug: string;
  title: string;
  synopsis: string | null;
  section: string | null;
  categories: string[];
  default_language: string | null;
  status: "draft" | "published";
  sort_index: number;
  updated_at: string;
  episode_count: number;
  languages: string[];
  artwork: Artwork[];
  blocking_issues: string[];
}

export interface ShowDetail extends ShowSummary {
  seasons: Season[];
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface Issue {
  severity: "blocking" | "warning";
  code: string;
  message: string;
  fix: string;
  location: { type?: string; id?: string; show_id?: string; label?: string };
}

export interface IssueGroup {
  key: string;
  title: string;
  kind: "show" | "episode" | "import";
  id: string | null;
  blocking: boolean;
  issues: Issue[];
}

export interface ValidationReport {
  can_publish: boolean;
  blocking_count: number;
  warning_count: number;
  groups: IssueGroup[];
}

export interface PublishRun {
  id: string;
  actor_email: string | null;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  counts: Record<string, number | boolean> | null;
  error: string | null;
  catalog_key: string | null;
  catalog_checksum: string | null;
  is_current: boolean;
}
