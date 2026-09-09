import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import { Empty, ErrorNotice, Loading, formatWhen } from "../components";
import type { IssueGroup, PublishRun, ValidationReport } from "../types";

interface PublishResult {
  run_id: string;
  unchanged: boolean;
  counts: Record<string, number | boolean>;
  exclusions: { type: string; title?: string; reason: string }[];
}

interface DryRun {
  can_publish: boolean;
  counts: Record<string, number>;
  diff: {
    shows_added: string[];
    shows_removed: string[];
    shows_changed: string[];
    episodes_added: number;
    episodes_removed: number;
    episodes_changed: number;
    is_first_publish: boolean;
  };
}

/** "1 episode" / "2 episodes" — an editor reads this, not a log parser. */
function plural(n: number, noun: string): string {
  return `${n} ${noun}${n === 1 ? "" : "s"}`;
}

export function Publish() {
  const { canPublish, user } = useAuth();
  const qc = useQueryClient();
  const [force, setForce] = useState(false);
  const [reason, setReason] = useState("");

  const report = useQuery({
    queryKey: ["validation"],
    queryFn: () => api<ValidationReport>("/admin/validation-report"),
  });

  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<{ runs: PublishRun[] }>("/admin/catalog/runs?limit=15"),
  });

  const dryRun = useMutation({
    mutationFn: () => api<DryRun>("/admin/catalog/publish/dry-run", { method: "POST" }),
  });

  const publish = useMutation({
    mutationFn: () =>
      api<PublishResult>("/admin/catalog/publish", {
        method: "POST",
        body: { force, force_reason: force ? reason : null },
      }),
    onSuccess: () => {
      setForce(false);
      setReason("");
      qc.invalidateQueries({ queryKey: ["runs"] });
      qc.invalidateQueries({ queryKey: ["validation"] });
    },
  });

  const rollback = useMutation({
    mutationFn: (runId: string) =>
      api(`/admin/catalog/rollback/${runId}`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });

  const blocked = report.data ? !report.data.can_publish : true;
  const publishError = publish.error instanceof ApiError ? publish.error : null;
  const disabledReason = !canPublish
    ? `You're signed in as ${user?.email} (editor). Only an admin can publish.`
    : report.isPending
      ? "Checking the content…"
      : blocked && !force
        ? report.data?.blocking_count === 1
          ? "1 thing still needs fixing."
          : `${report.data?.blocking_count} things still need fixing.`
        : force && !reason.trim()
          ? "Add a reason for publishing past the blockers."
          : null;

  return (
    <div className="page">
      <h1>Publish</h1>
      <p className="sub">
        Publishing builds the catalogue file the viewer app reads. Nothing reaches viewers until
        you press this button.
      </p>

      {publish.isSuccess && (
        <div className="notice ok">
          <strong>
            {publish.data.unchanged
              ? "Nothing had changed — the live catalogue was left exactly as it was."
              : `Published. ${publish.data.counts.shows} shows, ${publish.data.counts.episodes} episodes.`}
          </strong>
          {publish.data.exclusions.length > 0 && (
            <p className="fix">
              Left out of this catalogue:{" "}
              {publish.data.exclusions.map((e) => e.title ?? e.type).join(", ")}.
            </p>
          )}
        </div>
      )}

      {publishError && (
        <div className="notice error">
          <strong>{publishError.problem}</strong>
          {publishError.fix && <p className="fix">{publishError.fix}</p>}
        </div>
      )}

      <div className="panel">
        <div className="spread">
          <div>
            <h2 style={{ margin: 0 }}>
              {report.data
                ? report.data.can_publish
                  ? "Everything checks out."
                  : `${report.data.blocking_count} blocking, ${report.data.warning_count} to look at`
                : "Checking…"}
            </h2>
            <p className="small muted" style={{ margin: "4px 0 0" }}>
              {disabledReason ?? "Ready to publish."}
            </p>
          </div>
          <div className="row">
            <button onClick={() => dryRun.mutate()} disabled={dryRun.isPending}>
              {dryRun.isPending ? "Checking…" : "Preview changes"}
            </button>
            <button
              className="primary"
              disabled={Boolean(disabledReason) || publish.isPending}
              title={disabledReason ?? undefined}
              onClick={() => publish.mutate()}
            >
              {publish.isPending ? "Publishing…" : "Publish catalogue"}
            </button>
          </div>
        </div>

        {canPublish && blocked && (
          <div className="notice warn" style={{ marginTop: 14, marginBottom: 0 }}>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={force}
                onChange={(e) => setForce(e.target.checked)}
              />
              <span>
                <strong>Publish anyway, leaving the blocked items out.</strong>
                <br />
                <span className="small">
                  Everything that validates goes live; the items above stay off the catalogue until
                  they're fixed. The reason is kept in the run history.
                </span>
              </span>
            </label>
            {force && (
              <input
                type="text"
                style={{ marginTop: 8 }}
                placeholder="Why are you publishing now? e.g. “Launch at 6pm, artwork lands tomorrow”"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            )}
          </div>
        )}

        {dryRun.data && (
          <div className="notice info" style={{ marginTop: 14, marginBottom: 0 }}>
            <strong>
              {dryRun.data.diff.is_first_publish
                ? "This would be the first publish."
                : "What would change"}
            </strong>
            <p className="fix">
              {plural(dryRun.data.diff.shows_added.length, "show")} added,{" "}
              {dryRun.data.diff.shows_removed.length} removed,{" "}
              {dryRun.data.diff.shows_changed.length} changed ·{" "}
              {plural(dryRun.data.diff.episodes_added, "episode")} added,{" "}
              {dryRun.data.diff.episodes_removed} removed,{" "}
              {dryRun.data.diff.episodes_changed} changed.
              <br />
              Result: {dryRun.data.counts.shows} shows, {dryRun.data.counts.episodes} episodes,{" "}
              {dryRun.data.counts.language_variants_collapsed} language variants collapsed.
            </p>
          </div>
        )}
      </div>

      <div className="panel">
        <h2>What needs attention</h2>
        {report.isPending ? (
          <Loading rows={4} label="Loading validation report" />
        ) : report.isError ? (
          <ErrorNotice error={report.error} onRetry={() => report.refetch()} />
        ) : report.data.groups.length === 0 ? (
          <Empty
            title="Nothing to fix."
            hint="Every published show and episode has what it needs."
          />
        ) : (
          report.data.groups.map((group) => <IssueCard key={group.key} group={group} />)
        )}
      </div>

      <div className="panel">
        <h2>Publish history</h2>
        {runs.isPending ? (
          <Loading rows={3} label="Loading run history" />
        ) : runs.isError ? (
          <ErrorNotice error={runs.error} onRetry={() => runs.refetch()} />
        ) : runs.data.runs.length === 0 ? (
          <Empty title="Nothing published yet." />
        ) : (
          <table>
            <thead>
              <tr>
                <th style={{ width: 170 }}>When</th>
                <th style={{ width: 180 }}>Who</th>
                <th style={{ width: 100 }}>Result</th>
                <th>Contents</th>
                <th style={{ width: 110 }} />
              </tr>
            </thead>
            <tbody>
              {runs.data.runs.map((run) => (
                <tr key={run.id}>
                  <td className="small">{formatWhen(run.started_at)}</td>
                  <td className="small">{run.actor_email ?? "—"}</td>
                  <td>
                    <span
                      className={`pill ${
                        run.status === "success"
                          ? "published"
                          : run.status === "failed"
                            ? "blocked"
                            : "warn"
                      }`}
                    >
                      {run.status}
                    </span>
                    {run.is_current && (
                      <div>
                        <span className="pill plain" style={{ marginTop: 4 }}>
                          live
                        </span>
                      </div>
                    )}
                  </td>
                  <td className="small">
                    {run.counts ? (
                      <>
                        {run.counts.shows as number} shows · {run.counts.episodes as number}{" "}
                        episodes
                        {run.counts.unchanged ? " · no change" : ""}
                        {run.counts.forced ? " · forced" : ""}
                        {run.duration_ms != null && (
                          <span className="muted"> · {run.duration_ms} ms</span>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                    {run.error && (
                      <div className="small muted" style={{ marginTop: 4 }}>
                        {run.error}
                      </div>
                    )}
                  </td>
                  <td className="right">
                    {canPublish && run.status === "success" && !run.is_current && run.catalog_key && (
                      <button
                        style={{ padding: "4px 10px", fontSize: 13 }}
                        disabled={rollback.isPending}
                        onClick={() => rollback.mutate(run.id)}
                      >
                        Roll back
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function IssueCard({ group }: { group: IssueGroup }) {
  const href =
    group.kind === "show"
      ? `/shows/${group.id}`
      : group.kind === "episode"
        ? `/shows/${group.issues[0]?.location.show_id}/episodes/${group.id}`
        : null;

  return (
    <div className={`notice ${group.blocking ? "error" : "warn"}`}>
      <div className="spread">
        <strong>{group.title}</strong>
        {href && (
          <Link to={href} className="small">
            Open →
          </Link>
        )}
      </div>
      {group.issues.map((issue, i) => (
        <div key={i} style={{ marginTop: 8 }}>
          <div>{issue.message}</div>
          <p className="fix">{issue.fix}</p>
        </div>
      ))}
    </div>
  );
}
