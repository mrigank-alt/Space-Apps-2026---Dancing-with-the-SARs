import type { Feature, MultiPolygon, Point, Polygon } from "geojson";

export type BoundaryGeometry = Polygon | MultiPolygon;
export type BoundaryFeature = Feature<BoundaryGeometry>;
export type DrawingTool = "idle" | "polygon" | "freehand" | "rectangle" | "edit";

export interface SearchResult {
  id: string;
  label: string;
  context: string;
  center: [number, number];
  bbox?: [number, number, number, number];
  targetZoom?: number;
  kind: "geocoder" | "coordinates" | "demo" | "geolocation";
}

export interface AreaSummary {
  squareMeters: number;
  hectares: number;
  acres: number;
}

export interface SelectionResponse {
  selection_id: string;
  label: string;
  geometry: BoundaryGeometry;
  bbox: [number, number, number, number];
  centroid: Feature<Point>;
  reference_point: Feature<Point>;
  area: {
    square_meters: number;
    hectares: number;
    acres: number;
  };
  plot_count: number;
  plots: Array<{
    plot_id: string;
    plot_index: number;
    geometry: Polygon;
    bbox: [number, number, number, number];
    centroid: Feature<Point>;
    reference_point: Feature<Point>;
    area: {
      square_meters: number;
      hectares: number;
      acres: number;
    };
  }>;
  crs: "EPSG:4326";
  coordinate_order: "longitude, latitude";
  created_at: string;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    hint?: string;
  };
  detail?: string;
}
