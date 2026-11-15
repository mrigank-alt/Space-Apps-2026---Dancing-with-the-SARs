import type { Feature, MultiPolygon, Point, Polygon } from "geojson";

export type BoundaryGeometry = Polygon | MultiPolygon;
export type BoundaryFeature = Feature<BoundaryGeometry>;
export type DrawingTool = "idle" | "polygon" | "freehand" | "edit";

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

export type WaterSource =
  | "groundwater_well"
  | "surface_water"
  | "rainfed"
  | "municipal"
  | "mixed"
  | "other"
  | "unknown";

export type MonitoringGoal =
  | "groundwater_risk"
  | "land_subsidence"
  | "irrigation_planning"
  | "general_monitoring";

export interface FarmerProfile {
  operator_name: string;
  contact_email: string;
  contact_phone?: string;
}

export interface FarmProfile {
  primary_crop_or_land_use: string;
  water_source: WaterSource;
  monitoring_goal: MonitoringGoal;
  location_label?: string;
  location_context?: string;
}

export interface SelectionCreateDetails {
  label: string;
  farmer: FarmerProfile;
  farm_profile: FarmProfile;
  data_processing_consent: true;
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
  farmer: FarmerProfile | null;
  farm_profile: FarmProfile | null;
  data_processing_consent: boolean;
  consent_recorded_at: string | null;
  gunw_availability: {
    status: "available" | "partial" | "source_available" | "not_available" | "check_failed" | "not_checked";
    provider: string;
    collection: string;
    collections_checked: string[];
    checked_at: string | null;
    matched_product_count: number;
    archived_gunw_product_count: number;
    sentinel1_source_scene_count: number;
    on_demand_processing_may_be_possible: boolean;
    message: string;
    earthdata_login_required_for_download: boolean;
    plot_results: Array<{
      plot_id: string;
      status: "available" | "source_available" | "not_available" | "check_failed" | "not_checked";
      matched_product_count: number;
      archived_gunw_product_count: number;
      source_scene_count: number;
      results_truncated: boolean;
      message: string;
      products: Array<{
        product_id: string;
        collection: string | null;
        file_name: string | null;
        start_time: string | null;
        stop_time: string | null;
        flight_direction: string | null;
        frame_number: number | null;
        platform: string | null;
        download_url: string | null;
      }>;
      datasets: Array<{
        dataset_id: string;
        label: string;
        category: "gunw" | "source";
        status: "available" | "not_available" | "check_failed" | "not_checked";
        matched_product_count: number;
        results_truncated: boolean;
        message: string;
      }>;
    }>;
  } | null;
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
