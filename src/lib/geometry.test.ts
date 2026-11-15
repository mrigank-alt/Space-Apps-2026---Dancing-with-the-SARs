import type { Feature, Geometry } from "geojson";
import { describe, expect, it } from "vitest";
import { boundaryArea, boundaryFromSnapshot, parseCoordinateQuery } from "./geometry";

const drawnFeature: Feature<Geometry> = {
  type: "Feature",
  id: "farm-1",
  properties: { mode: "polygon" },
  geometry: {
    type: "Polygon",
    coordinates: [[
      [-112.15, 49.79],
      [-112.14, 49.79],
      [-112.14, 49.78],
      [-112.15, 49.78],
      [-112.15, 49.79],
    ]],
  },
};

describe("drawn boundary helpers", () => {
  it("extracts a Terra Draw polygon and calculates plausible farm area", () => {
    const boundary = boundaryFromSnapshot([drawnFeature]);
    expect(boundary).not.toBeNull();
    const summary = boundaryArea(boundary!);
    expect(summary.hectares).toBeGreaterThan(70);
    expect(summary.hectares).toBeLessThan(90);
    expect(summary.acres).toBeGreaterThan(170);
  });

  it("ignores Terra Draw coordinate handles", () => {
    const handle: Feature<Geometry> = {
      type: "Feature",
      properties: { mode: "polygon", parentId: "farm-1" },
      geometry: { type: "Point", coordinates: [-112.15, 49.79] },
    };
    expect(boundaryFromSnapshot([drawnFeature, handle])?.id).toBe("farm-1");
  });

  it("accepts a closed freehand trace as the farm boundary", () => {
    const tracedFeature: Feature<Geometry> = {
      ...drawnFeature,
      id: "farm-trace",
      properties: { mode: "freehand" },
    };
    expect(boundaryFromSnapshot([tracedFeature])?.id).toBe("farm-trace");
  });
});

describe("coordinate search", () => {
  it("accepts farmer-friendly latitude, longitude order", () => {
    expect(parseCoordinateQuery("49.788, -112.149")).toEqual([-112.149, 49.788]);
  });

  it("accepts unambiguous longitude, latitude order", () => {
    expect(parseCoordinateQuery("-112.149 49.788")).toEqual([-112.149, 49.788]);
  });

  it("rejects coordinates outside EPSG:4326", () => {
    expect(parseCoordinateQuery("191, 95")).toBeNull();
  });
});
