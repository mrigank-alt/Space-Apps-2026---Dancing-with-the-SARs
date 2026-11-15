import type {
  ApiErrorBody,
  BoundaryFeature,
  SelectionCreateDetails,
  SelectionResponse,
} from "../types";
import { API_BASE_URL } from "./config";

export async function createSelection(
  feature: BoundaryFeature,
  details: SelectionCreateDetails,
  signal?: AbortSignal,
): Promise<SelectionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ geometry: feature.geometry, source: "drawn", ...details }),
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
