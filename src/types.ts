import type { Feature, FeatureCollection, MultiPolygon, Point, Polygon } from "geojson";

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
    status: "available" | "partial" | "source_available" | "not_available" | "check_failed" | "not_checked" | "checking";
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
      status: "available" | "source_available" | "not_available" | "check_failed" | "not_checked" | "checking";
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

export interface ProcessingRun {
  run_id: string;
  selection_id: string;
  status: "queued" | "running" | "completed" | "no_data" | "credentials_required" | "failed";
  message: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  output_directory: string | null;
  result_summary: {
    run_id?: string | null;
    pair_count?: number | null;
    epoch_count?: number | null;
    reliable_pixel_fraction?: number | null;
    median_los_displacement_change_cm?: number | null;
    median_velocity_los_cm_year?: number | null;
    measurement_interval?: {
      start?: string | null;
      end?: string | null;
      elapsed_days?: number | null;
      delta_definition?: string | null;
    } | null;
    phase_processing?: string | null;
  } | null;
  progress_percent: number;
  stage: string;
  assessment_id: string | null;
}

export type ConcernLevel = "green" | "yellow" | "red" | "grey";

export interface ConcernZoneProperties {
  zone_id: string;
  plot_id: string;
  plot_index: number;
  concern_level: ConcernLevel;
  label: string;
  explanation: string;
  los_velocity_cm_year: number | null;
  observed_los_change_cm: number | null;
  persistence_fraction: number | null;
  coherence: number | null;
  uncertainty_available: boolean;
  measurement_start: string | null;
  measurement_end: string | null;
}

export interface Assessment {
  assessment_id: string;
  selection_id: string;
  processing_run_id: string;
  status: "completed";
  assessment_type: "movement_only" | "groundwater_related";
  methodology: "exploratory_relative_concern";
  created_at: string;
  observation_start: string | null;
  observation_end: string | null;
  summary: string;
  overall_concern: ConcernLevel;
  evidence_quality: "limited" | "moderate" | "strong";
  concern_zones: FeatureCollection<Polygon | MultiPolygon, ConcernZoneProperties>;
  plot_summaries: Array<{
    plot_id: string;
    plot_index: number;
    overall_concern: ConcernLevel;
    pixel_counts: Record<ConcernLevel, number>;
  }>;
  recommendations: Array<{
    priority: "routine" | "review" | "prompt_review";
    title: string;
    detail: string;
    scope: string;
  }>;
  groundwater: {
    status: "available" | "not_available" | "outside_coverage" | "check_failed";
    provider: string | null;
    checked_at: string;
    observation_count: number;
    monitoring_site_count: number;
    relationship_eligible: boolean;
    relationship_assessment: "supports" | "contradicts" | "insufficient";
    trend_summary: string | null;
    summary: string;
    limitations: string[];
  };
  forecast: {
    status: "available" | "not_available";
    title: string;
    urgency: "routine_monitoring" | "monitor_and_investigate" | "planned_action" | "prompt_review";
    summary: string;
    threshold_crossing_days_range: [number, number] | null;
    action_deadline_days: number | null;
    pumping_target: number | null;
    pumping_target_units: string | null;
    missing_inputs: string[];
    model_version: string | null;
    calibration_id: string | null;
    threshold_source: string | null;
    limitations: string[];
  };
  limitations: string[];
  provenance: Record<string, unknown>;
}

export interface ApiErrorBody {
  error?: {
    code?: string;
    message?: string;
    hint?: string;
  };
  detail?: string;
}
