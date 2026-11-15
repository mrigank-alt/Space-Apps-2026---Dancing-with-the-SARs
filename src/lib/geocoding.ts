import type { SearchResult } from "../types";

export function searchResultZoom(...types: Array<string | undefined>) {
  const values = types.filter(Boolean).map((value) => value!.toLocaleLowerCase());
  if (values.some((value) => value === "country")) return 5;
  if (values.some((value) => ["region", "state", "province"].includes(value))) return 8;
  if (values.some((value) => ["county", "district"].includes(value))) return 10;
  if (values.some((value) => ["city", "municipality", "town"].includes(value))) return 13;
  if (values.some((value) => ["village", "hamlet", "locality"].includes(value))) return 15;
  return 18;
}

function normalized(value: string) {
  return value
    .toLocaleLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function relevance(result: SearchResult, query: string) {
  const label = normalized(result.label);
  const search = normalized(query);
  if (label === search) return 300;
  if (label.startsWith(`${search} `)) return 200;
  if (label.includes(search)) return 100;
  return 0;
}

/** Merge provider results while keeping the most relevant named place first. */
export function mergeSearchResults(
  query: string,
  groups: SearchResult[][],
  limit = 8,
) {
  const seenLabels = new Set<string>();
  const seenLocations: [number, number][] = [];
  const unique = groups.flat().filter((result) => {
    const label = normalized(result.label);
    const sameLocation = seenLocations.some(
      ([longitude, latitude]) =>
        Math.abs(longitude - result.center[0]) < 0.00005 &&
        Math.abs(latitude - result.center[1]) < 0.00005,
    );
    if (seenLabels.has(label) || sameLocation) return false;
    seenLabels.add(label);
    seenLocations.push(result.center);
    return true;
  });

  return unique
    .map((result, index) => ({ result, index, score: relevance(result, query) }))
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .slice(0, limit)
    .map(({ result }) => result);
}
