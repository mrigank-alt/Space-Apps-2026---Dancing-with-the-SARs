import type { Polygon } from "geojson";
import type { Assessment, ConcernLevel, ConcernZoneProperties, SearchResult, SelectionResponse } from "../types";

const farmGeometry: Polygon = {
  type: "Polygon",
  coordinates: [[
    [-120.220, 36.620],
    [-120.190, 36.620],
    [-120.190, 36.600],
    [-120.220, 36.600],
    [-120.220, 36.620],
  ]],
};

const levels: Array<{
  level: ConcernLevel;
  west: number;
  east: number;
  label: string;
  explanation: string;
  velocity: number;
  change: number;
}> = [
  {
    level: "green",
    west: -120.220,
    east: -120.210,
    label: "Looks steady",
    explanation: "This area stayed close to the farm baseline during the sample period.",
    velocity: -0.3,
    change: -0.2,
  },
  {
    level: "yellow",
    west: -120.210,
    east: -120.200,
    label: "Needs a closer look",
    explanation: "This sample area shows persistent movement worth checking in the field.",
    velocity: -2.1,
    change: -1.4,
  },
  {
    level: "red",
    west: -120.200,
    east: -120.190,
    label: "Needs prompt attention",
    explanation: "This sample area shows stronger persistent movement and should be inspected promptly.",
    velocity: -4.8,
    change: -3.2,
  },
];

export const PRESENTATION_DEMO_LOCATION: SearchResult = {
  id: "presentation-demo",
  label: "Sample farm near San Joaquin, California",
  context: "Presentation demo · simulated results",
  center: [-120.205, 36.610],
  bbox: [-120.220, 36.600, -120.190, 36.620],
  kind: "demo",
};

export const PRESENTATION_DEMO_SELECTION: SelectionResponse = {
  selection_id: "demo_presentation_farm",
  label: "Sample Valley Farm — Demo",
  geometry: farmGeometry,
  bbox: [-120.220, 36.600, -120.190, 36.620],
  centroid: { type: "Feature", geometry: { type: "Point", coordinates: [-120.205, 36.610] }, properties: {} },
  reference_point: { type: "Feature", geometry: { type: "Point", coordinates: [-120.205, 36.610] }, properties: {} },
  area: { square_meters: 5_930_000, hectares: 593, acres: 1_465.3 },
  plot_count: 1,
  plots: [{
    plot_id: "demo_plot_001",
    plot_index: 1,
    geometry: farmGeometry,
    bbox: [-120.220, 36.600, -120.190, 36.620],
    centroid: { type: "Feature", geometry: { type: "Point", coordinates: [-120.205, 36.610] }, properties: {} },
    reference_point: { type: "Feature", geometry: { type: "Point", coordinates: [-120.205, 36.610] }, properties: {} },
    area: { square_meters: 5_930_000, hectares: 593, acres: 1_465.3 },
  }],
  farmer: { operator_name: "Sample Farmer", contact_email: "demo@example.com" },
  farm_profile: {
    primary_crop_or_land_use: "Mixed crops",
    water_source: "groundwater_well",
    monitoring_goal: "groundwater_risk",
    location_label: "San Joaquin Valley, California",
  },
  data_processing_consent: true,
  consent_recorded_at: "2026-11-15T12:00:00Z",
  gunw_availability: {
    status: "available",
    provider: "Presentation sample",
    collection: "Simulated demonstration data",
    collections_checked: [],
    checked_at: "2026-11-15T12:00:00Z",
    matched_product_count: 9,
    archived_gunw_product_count: 9,
    sentinel1_source_scene_count: 0,
    on_demand_processing_may_be_possible: false,
    message: "Sample imagery is ready for this presentation demo.",
    earthdata_login_required_for_download: false,
    plot_results: [{
      plot_id: "demo_plot_001",
      status: "available",
      matched_product_count: 9,
      archived_gunw_product_count: 9,
      source_scene_count: 0,
      results_truncated: false,
      message: "Sample imagery is ready.",
      products: [],
      datasets: [],
    }],
  },
  crs: "EPSG:4326",
  coordinate_order: "longitude, latitude",
  created_at: "2026-11-15T12:00:00Z",
};

export const PRESENTATION_DEMO_ASSESSMENT: Assessment = {
  assessment_id: "demo_assessment",
  selection_id: PRESENTATION_DEMO_SELECTION.selection_id,
  processing_run_id: "demo_run",
  status: "completed",
  assessment_type: "movement_only",
  methodology: "exploratory_relative_concern",
  created_at: "2026-11-15T12:00:00Z",
  observation_start: "2026-04-01",
  observation_end: "2026-10-01",
  summary: "Sample results show steady, watch, and prompt-attention areas across the farm.",
  overall_concern: "red",
  evidence_quality: "moderate",
  concern_zones: {
    type: "FeatureCollection",
    features: levels.map((item, index) => ({
      type: "Feature",
      geometry: {
        type: "Polygon",
        coordinates: [[
          [item.west, 36.620],
          [item.east, 36.620],
          [item.east, 36.600],
          [item.west, 36.600],
          [item.west, 36.620],
        ]],
      },
      properties: {
        zone_id: `demo_zone_${index + 1}`,
        plot_id: "demo_plot_001",
        plot_index: 1,
        concern_level: item.level,
        label: item.label,
        explanation: item.explanation,
        los_velocity_cm_year: item.velocity,
        observed_los_change_cm: item.change,
        persistence_fraction: 0.82,
        coherence: 0.76,
        uncertainty_available: true,
        measurement_start: "2026-04-01",
        measurement_end: "2026-10-01",
      } satisfies ConcernZoneProperties,
    })),
  },
  plot_summaries: [{
    plot_id: "demo_plot_001",
    plot_index: 1,
    overall_concern: "red",
    pixel_counts: { green: 120, yellow: 95, red: 55, grey: 0 },
  }],
  recommendations: [
    { priority: "prompt_review", title: "Walk the red area", detail: "Check for cracks, sinking, ponding, or damaged irrigation lines.", scope: "Red sample zone" },
    { priority: "review", title: "Review pumping records", detail: "Compare recent pump hours with the period shown.", scope: "Whole sample farm" },
  ],
  groundwater: {
    status: "available",
    provider: "Simulated presentation record",
    checked_at: "2026-11-15T12:00:00Z",
    observation_count: 12,
    monitoring_site_count: 2,
    relationship_eligible: true,
    relationship_assessment: "supports",
    trend_summary: "Sample well levels declined during the demonstration period.",
    summary: "Simulated nearby well records support taking a closer look at the highlighted areas.",
    limitations: ["Presentation values are simulated and must not be used for farm decisions."],
  },
  forecast: {
    status: "available",
    title: "Review pumping within 14 days",
    urgency: "prompt_review",
    summary: "In this simulated example, arrange a qualified review before continuing the same pumping pattern.",
    threshold_crossing_days_range: [28, 45],
    action_deadline_days: 14,
    pumping_target: null,
    pumping_target_units: null,
    missing_inputs: [],
    model_version: "presentation-demo",
    calibration_id: "simulated-demo",
    threshold_source: "simulated presentation scenario",
    limitations: ["This deadline is simulated for presentation purposes."],
  },
  limitations: [
    "Presentation demo only: all movement, groundwater, and deadline values are simulated.",
    "Do not use this example to make pumping, irrigation, or safety decisions.",
  ],
  provenance: { demo: true, data_source: "simulated presentation data" },
};
