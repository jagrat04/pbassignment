import type { ReactNode } from "react";
import { ApiError } from "./api";

/** Loading / empty / error / permission-denied, in one place so every screen
 *  handles all four the same way and none of them can forget one. */

export function Loading({ rows = 4, label = "Loading…" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-live="polite" aria-label={label}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton" style={{ height: 44, marginBottom: 8 }} />
      ))}
    </div>
  );
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <p style={{ fontWeight: 600, color: "var(--ink)", margin: "0 0 6px" }}>{title}</p>
      {hint && <p style={{ margin: "0 0 14px" }}>{hint}</p>}
      {action}
    </div>
  );
}

/**
 * Renders whatever the server said. A 403 gets its own wording because
 * "something went wrong" is the wrong answer to "you are not an admin".
 */
export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;

  if (api?.status === 403) {
    return (
      <div className="notice warn">
        <strong>{api.problem}</strong>
        {api.fix && <p className="fix">{api.fix}</p>}
      </div>
    );
  }
  if (api?.status === 401) {
    return (
      <div className="notice warn">
        <strong>Your session has ended.</strong>
        <p className="fix">Sign in again to carry on.</p>
      </div>
    );
  }

  const problem = api?.problem ?? (error instanceof Error ? error.message : "Something went wrong.");
  const fix =
    api?.fix ??
    (api === null
      ? "The API may be down. Check that it's running on " +
        (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000") +
        "."
      : undefined);

  return (
    <div className="notice error">
      <strong>{problem}</strong>
      {fix && <p className="fix">{fix}</p>}
      {onRetry && (
        <p style={{ margin: "10px 0 0" }}>
          <button onClick={onRetry}>Try again</button>
        </p>
      )}
    </div>
  );
}

export function StatusPill({ status }: { status: "draft" | "published" }) {
  return <span className={`pill ${status}`}>{status === "published" ? "Published" : "Draft"}</span>;
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <label className={`field${error ? " invalid" : ""}`}>
      <span className="label">{label}</span>
      {hint && <span className="hint">{hint}</span>}
      {children}
      {error && (
        <span className="small" style={{ color: "var(--danger)", display: "block", marginTop: 4 }}>
          {error}
        </span>
      )}
    </label>
  );
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatWhen(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
