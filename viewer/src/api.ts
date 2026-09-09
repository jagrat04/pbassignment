/**
 * The viewer's entire surface area.
 *
 * Three public endpoints, no token, no admin routes. Anything that needed an
 * /admin call would be a bug: this app is only ever allowed to see what has
 * actually been published.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ViewerError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    let message = "We couldn't load that just now.";
    if (res.status === 503) message = "Peblo TV is being set up. Check back in a moment.";
    if (res.status === 404) message = "We couldn't find that.";
    throw new ViewerError(res.status, message);
  }
  return (await res.json()) as T;
}
