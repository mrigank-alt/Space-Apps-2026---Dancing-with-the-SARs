import type { Feature, Polygon } from "geojson";
import type { Assessment, ConcernLevel, ConcernZoneProperties, SearchResult, SelectionResponse } from "../types";

type Coordinate = [number, number];

const farmRing: Coordinate[] = [
  [-120.236, 36.617],
  [-120.223, 36.624],
  [-120.208, 36.622],
  [-120.199, 36.613],
  [-120.204, 36.600],
  [-120.222, 36.596],
  [-120.237, 36.605],
  [-120.236, 36.617],
];

const farmGeometry: Polygon = {
  type: "Polygon",
  coordinates: [farmRing],
};

function clipEdge(
  points: Coordinate[],
  inside: (point: Coordinate) => boolean,
  intersection: (start: Coordinate, end: Coordinate) => Coordinate,
): Coordinate[] {
  if (!points.length) return [];
  const result: Coordinate[] = [];
  let start = points[points.length - 1];
  for (const end of points) {
    const startInside = inside(start);
    const endInside = inside(end);
    if (endInside) {
      if (!startInside) result.push(intersection(start, end));
      result.push(end);
    } else if (startInside) {
      result.push(intersection(start, end));
    }
    start = end;
  }
  return result;
}

function verticalIntersection(x: number, start: Coordinate, end: Coordinate): Coordinate {
  const span = end[0] - start[0];
  const ratio = span === 0 ? 0 : (x - start[0]) / span;
  return [x, start[1] + ratio * (end[1] - start[1])];
}

function horizontalIntersection(y: number, start: Coordinate, end: Coordinate): Coordinate {
  const span = end[1] - start[1];
  const ratio = span === 0 ? 0 : (y - start[1]) / span;
  return [start[0] + ratio * (end[0] - start[0]), y];
}

function clipFarmToCell(west: number, south: number, east: number, north: number): Coordinate[] {
  let points = farmRing.slice(0, -1);
  points = clipEdge(points, ([x]) => x >= west, (a, b) => verticalIntersection(west, a, b));
  points = clipEdge(points, ([x]) => x <= east, (a, b) => verticalIntersection(east, a, b));
  points = clipEdge(points, ([, y]) => y >= south, (a, b) => horizontalIntersection(south, a, b));
  points = clipEdge(points, ([, y]) => y <= north, (a, b) => horizontalIntersection(north, a, b));
  return points.length >= 3 ? [...points, points[0]] : [];
}

const redCells = new Set(["3:2", "4:2", "4:3"]);
const yellowCells = new Set(["2:1", "3:1", "4:1", "2:2", "5:2", "2:3", "3:3", "5:3", "3:4", "4:4"]);

function cellLevel(column: number, row: number): ConcernLevel {
  const key = `${column}:${row}`;
  if (redCells.has(key)) return "red";
  if (yellowCells.has(key)) return "yellow";
  return "green";
}

const levelDetails: Record<Exclude<ConcernLevel, "grey">, {
  label: string;
  explanation: string;
  velocity: number;
  change: number;
}> = {
  green: {
    label: "Looks steady",
    explanation: "This area stayed close to the farm baseline during the sample period.",
    velocity: -0.3,
    change: -0.2,
  },
  yellow: {
    label: "Needs a closer look",
    explanation: "This sample area shows persistent movement worth checking in the field.",
    velocity: -2.1,
    change: -1.4,
  },
  red: {
    label: "Needs prompt attention",
    explanation: "This sample area shows stronger persistent movement and should be inspected promptly.",
    velocity: -4.8,
    change: -3.2,
  },
};

function buildConcernGrid(): Array<Feature<Polygon, ConcernZoneProperties>> {
  const west = -120.237;
  const south = 36.596;
  const east = -120.199;
  const north = 36.624;
  const columns = 6;
  const rows = 5;
  const width = (east - west) / columns;
  const height = (north - south) / rows;
  const features: Array<Feature<Polygon, ConcernZoneProperties>> = [];

  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const cellWest = west + column * width;
      const cellEast = cellWest + width;
      const cellSouth = south + row * height;
      const cellNorth = cellSouth + height;
      const ring = clipFarmToCell(cellWest, cellSouth, cellEast, cellNorth);
      if (!ring.length) continue;
      const concernLevel = cellLevel(column, row) as Exclude<ConcernLevel, "grey">;
      const details = levelDetails[concernLevel];
      features.push({
        type: "Feature",
        geometry: { type: "Polygon", coordinates: [ring] },
        properties: {
          zone_id: `demo_cell_${row}_${column}`,
          plot_id: "demo_plot_001",
          plot_index: 1,
          concern_level: concernLevel,
          label: details.label,
          explanation: details.explanation,
          los_velocity_cm_year: details.velocity - row * 0.03,
          observed_los_change_cm: details.change - column * 0.02,
          persistence_fraction: concernLevel === "green" ? 0.62 : 0.82,
          coherence: 0.76,
          uncertainty_available: true,
          measurement_start: "2026-04-01",
          measurement_end: "2026-10-01",
        },
      });
    }
  }
  return features;
}

const concernGrid = buildConcernGrid();

export const PRESENTATION_DEMO_LOCATION: SearchResult = {
  id: "presentation-demo",
  label: "San Joaquin Valley Farm, California",
  context: "San Joaquin Valley, California · simulated results",
  center: [-120.218, 36.610],
  bbox: [-120.237, 36.596, -120.199, 36.624],
  kind: "demo",
};

export const PRESENTATION_DEMO_SELECTION: SelectionResponse = {
  selection_id: "demo_presentation_farm",
  label: "San Joaquin Valley Farm",
  geometry: farmGeometry,
  bbox: [-120.237, 36.596, -120.199, 36.624],
  centroid: { type: "Feature", geometry: { type: "Point", coordinates: [-120.218, 36.610] }, properties: {} },
  reference_point: { type: "Feature", geometry: { type: "Point", coordinates: [-120.218, 36.610] }, properties: {} },
  area: { square_meters: 6_680_000, hectares: 668, acres: 1_650.7 },
  plot_count: 1,
  plots: [{
    plot_id: "demo_plot_001",
    plot_index: 1,
    geometry: farmGeometry,
    bbox: [-120.237, 36.596, -120.199, 36.624],
    centroid: { type: "Feature", geometry: { type: "Point", coordinates: [-120.218, 36.610] }, properties: {} },
    reference_point: { type: "Feature", geometry: { type: "Point", coordinates: [-120.218, 36.610] }, properties: {} },
    area: { square_meters: 6_680_000, hectares: 668, acres: 1_650.7 },
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
    message: "Sample imagery is ready for the San Joaquin Valley farm sample.",
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
    features: concernGrid,
  },
  plot_summaries: [{
    plot_id: "demo_plot_001",
    plot_index: 1,
    overall_concern: "red",
    pixel_counts: { green: 17, yellow: 10, red: 3, grey: 0 },
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
    trend_summary: "Sample well levels declined during the illustrated period.",
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
    model_version: "presentation-sample",
    calibration_id: "simulated-sample",
    threshold_source: "simulated presentation scenario",
    limitations: ["This deadline is simulated for presentation purposes."],
  },
  limitations: [
    "San Joaquin Valley sample only: all movement, groundwater, and deadline values are simulated.",
    "Do not use this example to make pumping, irrigation, or safety decisions.",
  ],
  provenance: { demo: true, data_source: "simulated presentation data" },
};
