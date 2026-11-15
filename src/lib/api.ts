import type { BoundaryFeature, SelectionResponse, ApiErrorBody } from "../types";
import { API_BASE_URL } from "./config";

export async function createSelection(
  feature: BoundaryFeature,
  label: string,
  signal?: AbortSignal,
): Promise<SelectionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ geometry: feature.geometry, source: "drawn", label }),
    signal,
  });

  if (!response.ok) {
    let body: ApiErrorBody = {};
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // The status fallback below is more useful than a JSON parse error.
    }
    const message = body.error?.message || body.detail || `Validation failed (${response.status}).`;
    const hint = body.error?.hint ? ` ${body.error.hint}` : "";
    throw new Error(`${message}${hint}`);
  }

  return (await response.json()) as SelectionResponse;
}

export function selectionRecordUrl(selectionId: string): string {
  return `${API_BASE_URL}/api/v1/selections/${encodeURIComponent(selectionId)}`;
}
