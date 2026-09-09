import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "./api";
import type { Artwork, ArtworkKind, ArtworkSpec } from "./types";

/**
 * One labelled upload slot.
 *
 * Shows the required dimensions before the editor picks a file, a live preview
 * of what they picked, and — when the server refuses it — the server's own
 * words about why and what to do.
 *
 * The local size/type check below is a courtesy, not a gate: it saves a
 * pointless round trip for an obviously wrong file. Aspect ratio, real
 * dimensions and the byte ceiling are decided by the API on the bytes it
 * actually received, and this component shows whatever it says.
 */
export function ArtworkSlot({
  kind,
  spec,
  ownerType,
  ownerId,
  current,
  required,
  onChanged,
}: {
  kind: ArtworkKind;
  spec: ArtworkSpec;
  ownerType: "show" | "episode";
  ownerId: string;
  current?: Artwork;
  required?: boolean;
  onChanged?: () => void;
}) {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Artwork>(`/admin/artwork/${ownerType}/${ownerId}/${kind}`, {
        method: "POST",
        body: form,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["show"] });
      qc.invalidateQueries({ queryKey: ["shows"] });
      qc.invalidateQueries({ queryKey: ["validation"] });
      onChanged?.();
    },
  });

  const remove = useMutation({
    mutationFn: async () =>
      api<void>(`/admin/artwork/${ownerType}/${ownerId}/${kind}`, { method: "DELETE" }),
    onSuccess: () => {
      setPreview(null);
      qc.invalidateQueries({ queryKey: ["show"] });
      qc.invalidateQueries({ queryKey: ["shows"] });
      qc.invalidateQueries({ queryKey: ["validation"] });
      onChanged?.();
    },
  });

  function choose(file: File | undefined) {
    if (!file) return;
    setLocalError(null);
    upload.reset();

    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
      setLocalError(`${file.name} isn't a JPG, PNG or WebP. Export the artwork and try again.`);
      return;
    }
    setPreview(URL.createObjectURL(file));
    upload.mutate(file);
  }

  const rejection = upload.error instanceof ApiError ? upload.error : null;
  const shownUrl = preview ?? current?.url ?? null;
  const [w, h] = spec.target_px;

  return (
    <div
      className={`slot${current ? " filled" : ""}${rejection || localError ? " rejected" : ""}`}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        choose(e.dataTransfer.files?.[0]);
      }}
    >
      <div className="spread" style={{ marginBottom: 8 }}>
        <h3 style={{ margin: 0, textTransform: "capitalize" }}>
          {kind}
          {required && !current && <span style={{ color: "var(--danger)" }}> *</span>}
        </h3>
        {current && <span className="pill published">Uploaded</span>}
      </div>

      {shownUrl ? (
        <img className={`preview ${kind}`} src={shownUrl} alt={`${kind} preview`} />
      ) : (
        <div className={`preview ${kind}`} aria-hidden="true" />
      )}

      <p className="specs">
        {spec.aspect} · {w}×{h}px · under {spec.max_kb} KB
        {current && (
          <>
            <br />
            Now: {current.width}×{current.height}, {Math.round(current.bytes / 1024)} KB
          </>
        )}
      </p>

      {upload.isPending && (
        <p className="small muted" role="status">
          Uploading and checking…
        </p>
      )}

      {localError && (
        <div className="notice error" style={{ marginBottom: 8 }}>
          <strong>{localError}</strong>
        </div>
      )}

      {rejection && (
        <div className="notice error" style={{ marginBottom: 8 }}>
          <strong>{rejection.problem}</strong>
          {rejection.fix && <p className="fix">{rejection.fix}</p>}
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style={{ display: "none" }}
        onChange={(e) => {
          choose(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <div className="row">
        <button onClick={() => inputRef.current?.click()} disabled={upload.isPending}>
          {current ? "Replace" : "Choose file"}
        </button>
        {current && (
          <button className="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Remove
          </button>
        )}
      </div>
      <p className="small muted" style={{ margin: "8px 0 0" }}>
        or drop an image here
      </p>
    </div>
  );
}
