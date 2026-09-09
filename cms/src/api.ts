/**
 * One place that talks to the API.
 *
 * The server answers errors as { error, problem, fix } — a sentence about what
 * went wrong and a sentence about what to do — so this layer keeps that shape
 * intact instead of flattening everything to `err.message`. Every screen can
 * then show the editor the same words the server chose.
 */

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const TOKEN_KEY = "peblo.cms.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private window; the session just won't survive a reload */
  }
}

export class ApiError extends Error {
  status: number;
  problem: string;
  fix?: string;
  field?: string;
  code?: string;
  payload: Record<string, unknown>;

  constructor(status: number, body: unknown) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    const d = (typeof detail === "object" && detail !== null ? detail : {}) as Record<
      string,
      unknown
    >;

    const problem =
      (typeof d.problem === "string" && d.problem) ||
      (typeof detail === "string" && detail) ||
      pydanticMessage(detail) ||
      "Something went wrong.";

    super(problem);
    this.status = status;
    this.problem = problem;
    this.fix = typeof d.fix === "string" ? d.fix : undefined;
    this.field = typeof d.field === "string" ? d.field : undefined;
    this.code = typeof d.error === "string" ? d.error : undefined;
    this.payload = d;
  }
}

/** FastAPI's 422 body is a list of {loc, msg}. Show the message, not the shape. */
function pydanticMessage(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const first = detail[0] as { msg?: string; loc?: unknown[] };
  if (typeof first.msg !== "string") return null;
  return first.msg.replace(/^Value error,\s*/, "");
}

type Options = Omit<RequestInit, "body"> & { body?: unknown };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { body, headers, ...rest } = options;
  const token = getToken();

  const isForm = body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      ...(isForm ? {} : body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const parsed = text ? safeJson(text) : null;

  if (!res.ok) {
    if (res.status === 401) setToken(null);
    throw new ApiError(res.status, parsed ?? text);
  }
  return parsed as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
