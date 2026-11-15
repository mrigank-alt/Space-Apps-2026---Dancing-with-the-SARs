import area from "@turf/area";
import type { Feature, Geometry, Polygon } from "geojson";
import type { AreaSummary, BoundaryFeature } from "../types";

const SQUARE_METERS_PER_ACRE = 4046.8564224;
const SQUARE_METERS_PER_HECTARE = 10_000;

export function boundaryArea(feature: BoundaryFeature): AreaSummary {
  const squareMeters = area(feature);
  return {
    squareMeters,
    hectares: squareMeters / SQUARE_METERS_PER_HECTARE,
    acres: squareMeters / SQUARE_METERS_PER_ACRE,
  };
}

export function boundaryFromSnapshot(
  features: Array<Feature<Geometry>>,
): BoundaryFeature | null {
  const parent = [...features].reverse().find((feature) => {
    if (feature.geometry.type !== "Polygon") return false;
    const mode = feature.properties?.mode;
    return mode === "polygon" || mode === "freehand" || mode === "rectangle";
  });

  if (!parent || parent.geometry.type !== "Polygon") return null;

  return {
    type: "Feature",
    id: parent.id,
    properties: {},
    geometry: parent.geometry as Polygon,
  };
}

export function formatArea(value: number): string {
  if (value >= 10_000) return Math.round(value).toLocaleString();
  if (value >= 100) return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function parseCoordinateQuery(query: string): [number, number] | null {
  const match = query
    .trim()
    .match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/);
  if (!match) return null;

  const first = Number(match[1]);
  const second = Number(match[2]);
  if (!Number.isFinite(first) || !Number.isFinite(second)) return null;

  // People commonly type latitude first. If the first value cannot be a
  // latitude, accept explicit longitude-latitude order instead.
  if (Math.abs(first) <= 90 && Math.abs(second) <= 180) return [second, first];
  if (Math.abs(first) <= 180 && Math.abs(second) <= 90) return [first, second];
  return null;
}
