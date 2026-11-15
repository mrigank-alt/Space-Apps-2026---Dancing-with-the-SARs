import type {
  Assessment,
  ApiErrorBody,
  BoundaryFeature,
  ProcessingRun,
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

async function responseError(response: Response): Promise<Error> {
  let body: ApiErrorBody = {};
  try {
    body = (await response.json()) as ApiErrorBody;
  } catch {
    // Use the status fallback when the server did not return JSON.
  }
  return new Error(body.error?.message || body.detail || `Request failed (${response.status}).`);
}

export async function startProcessing(selectionId: string): Promise<ProcessingRun> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections/${selectionId}/processing-runs`, {
    method: "POST",
  });
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as ProcessingRun;
}

export async function getProcessingRun(runId: string): Promise<ProcessingRun> {
  const response = await fetch(`${API_BASE_URL}/api/v1/processing-runs/${runId}`);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as ProcessingRun;
}

export async function listProcessingRuns(selectionId: string): Promise<ProcessingRun[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/selections/${selectionId}/processing-runs`,
  );
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as ProcessingRun[];
}

export async function getSelection(selectionId: string): Promise<SelectionResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections/${selectionId}`);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as SelectionResponse;
}

export async function getGunwAvailability(
  selectionId: string,
): Promise<NonNullable<SelectionResponse["gunw_availability"]>> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/selections/${selectionId}/gunw-availability`,
  );
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as NonNullable<SelectionResponse["gunw_availability"]>;
}

export async function getAssessment(assessmentId: string): Promise<Assessment> {
  const response = await fetch(`${API_BASE_URL}/api/v1/assessments/${assessmentId}`);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as Assessment;
}

export async function getLatestAssessment(selectionId: string): Promise<Assessment | null> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections/${selectionId}/assessments/latest`);
  if (response.status === 404) return null;
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as Assessment;
}

export async function listAssessments(selectionId: string): Promise<Assessment[]> {
  const response = await fetch(`${API_BASE_URL}/api/v1/selections/${selectionId}/assessments`);
  if (!response.ok) throw await responseError(response);
  return (await response.json()) as Assessment[];
}
