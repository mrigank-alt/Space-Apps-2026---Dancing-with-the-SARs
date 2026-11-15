import { describe, expect, it } from "vitest";
import { PRESENTATION_DEMO_ASSESSMENT, PRESENTATION_DEMO_SELECTION } from "./presentationDemo";

describe("presentation demo", () => {
  it("is explicitly simulated and includes green, yellow, and red zones", () => {
    const levels = PRESENTATION_DEMO_ASSESSMENT.concern_zones.features.map(
      (feature) => feature.properties.concern_level,
    );

    expect(new Set(levels)).toEqual(new Set(["green", "yellow", "red"]));
    expect(PRESENTATION_DEMO_ASSESSMENT.provenance.demo).toBe(true);
    expect(PRESENTATION_DEMO_SELECTION.label).toContain("Demo");
  });
});
