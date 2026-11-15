import { describe, expect, it } from "vitest";
import type { SearchResult } from "../types";
import { mergeSearchResults, searchResultZoom } from "./geocoding";

function result(id: string, label: string, center: [number, number]): SearchResult {
  return { id, label, center, context: "test", kind: "geocoder" };
}

describe("geocoder result merging", () => {
  it("ranks an exact named POI above a generic city result", () => {
    const merged = mergeSearchResults("Calgary Farmyard", [
      [result("city", "Calgary, Alberta, Canada", [-114.0719, 51.0447])],
      [result("farmyard", "Calgary Farmyard, Rocky View County, Alberta", [-113.8391, 50.8947])],
    ]);
    expect(merged[0].id).toBe("farmyard");
  });

  it("removes the same place returned by two providers", () => {
    const merged = mergeSearchResults("Calgary Farmyard", [
      [result("photon", "Calgary Farmyard", [-113.8390617, 50.894739])],
      [result("other", "Calgary Farmyard", [-113.83906, 50.89474])],
    ]);
    expect(merged).toHaveLength(1);
  });
});

describe("search result zoom", () => {
  it("opens farms and addresses close enough to inspect field detail", () => {
    expect(searchResultZoom("house", "attraction")).toBe(18);
    expect(searchResultZoom("address")).toBe(18);
  });

  it("keeps cities and regions in geographic context", () => {
    expect(searchResultZoom("city")).toBe(13);
    expect(searchResultZoom("region")).toBe(8);
  });
});
