import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Reference } from "./types";

/**
 * The server's rulebook: sections, categories, languages, artwork specs.
 *
 * Fetched rather than duplicated in the frontend so a change to reference.json
 * reaches the dropdowns and the upload hints without a redeploy, and so the CMS
 * can never offer a section the API would reject.
 */
export function useReference() {
  return useQuery({
    queryKey: ["reference"],
    queryFn: () => api<Reference>("/reference"),
    staleTime: Infinity,
  });
}
