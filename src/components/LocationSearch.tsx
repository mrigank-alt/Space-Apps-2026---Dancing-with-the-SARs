import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { SearchResult } from "../types";
import { parseCoordinateQuery } from "../lib/geometry";
import { mergeSearchResults, searchResultZoom } from "../lib/geocoding";

interface LocationSearchProps {
  mapTilerKey?: string;
  autocompleteGeocoderUrl: string;
  fallbackGeocoderUrl: string;
  onSelect: (result: SearchResult) => void;
  onUseMyLocation: () => void;
  locating: boolean;
  locationError?: string;
}

interface MapTilerFeature {
  id?: string;
  text?: string;
  place_name?: string;
  center?: [number, number];
  bbox?: [number, number, number, number];
  place_type?: string[];
}

interface NominatimFeature {
  id?: string;
  bbox?: [number, number, number, number];
  geometry?: { type?: string; coordinates?: [number, number] };
  properties?: {
    place_id?: number;
    display_name?: string;
    category?: string;
    type?: string;
  };
}

interface PhotonFeature {
  geometry?: { type?: string; coordinates?: [number, number] };
  properties?: {
    osm_id?: number;
    osm_value?: string;
    type?: string;
    name?: string;
    housenumber?: string;
    street?: string;
    city?: string;
    county?: string;
    state?: string;
    country?: string;
    postcode?: string;
    extent?: [number, number, number, number];
  };
}

const demoLocations: SearchResult[] = [
  {
    id: "demo-taber",
    label: "Demo: rural quarter near Taber",
    context: "Alberta, Canada · approximate location",
    center: [-112.149, 49.788],
    targetZoom: 15,
    kind: "demo",
  },
  {
    id: "demo-corcoran",
    label: "Demo: farm area near Corcoran",
    context: "California, United States · approximate location",
    center: [-119.56, 36.098],
    targetZoom: 15,
    kind: "demo",
  },
  {
    id: "demo-murray-bridge",
    label: "Demo: farm area near Murray Bridge",
    context: "South Australia · approximate location",
    center: [139.274, -35.12],
    targetZoom: 15,
    kind: "demo",
  },
];

export function LocationSearch({
  mapTilerKey,
  autocompleteGeocoderUrl,
  fallbackGeocoderUrl,
  onSelect,
  onUseMyLocation,
  locating,
  locationError,
}: LocationSearchProps) {
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string>();
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const requestRef = useRef<AbortController | undefined>(undefined);
  const fallbackCacheRef = useRef(new Map<string, SearchResult[]>());
  const autocompleteCacheRef = useRef(new Map<string, SearchResult[]>());
  const lastFallbackRequestRef = useRef(0);

  const coordinateResult = useMemo(() => {
    const center = parseCoordinateQuery(query);
    if (!center) return null;
    return {
      id: `coordinates-${center.join("-")}`,
      label: `${center[1].toFixed(6)}, ${center[0].toFixed(6)}`,
      context: "Coordinates · latitude, longitude input",
      center,
      targetZoom: 18,
      kind: "coordinates" as const,
    };
  }, [query]);

  useEffect(() => {
    requestRef.current?.abort();

    const trimmed = query.trim();
    const minimumLength = mapTilerKey ? 2 : 3;
    if (coordinateResult || trimmed.length < minimumLength) return;

    const controller = new AbortController();
    requestRef.current = controller;
    const timeout = window.setTimeout(async () => {
      setSearching(true);
      setSearchError(undefined);
      try {
        const cacheKey = trimmed.toLocaleLowerCase();
        const cached = autocompleteCacheRef.current.get(cacheKey);
        if (cached) {
          setResults(cached);
          return;
        }

        const searchPhoton = async () => {
          const params = new URLSearchParams({
            q: trimmed,
            limit: "8",
            lang: (navigator.language || "en").split("-")[0],
          });
          const endpoint = autocompleteGeocoderUrl.replace(/\/$/, "");
          const response = await fetch(`${endpoint}/api/?${params}`, {
            signal: controller.signal,
            headers: { Accept: "application/geo+json, application/json" },
          });
          if (!response.ok) throw new Error(`Autocomplete failed (${response.status}).`);
          const data = (await response.json()) as { features?: PhotonFeature[] };
          return (data.features ?? [])
            .filter((feature) =>
              feature.geometry?.type === "Point" &&
              Array.isArray(feature.geometry.coordinates) &&
              feature.geometry.coordinates.length === 2,
            )
            .map((feature, index): SearchResult => {
              const properties = feature.properties ?? {};
              const primary =
                properties.name ||
                [properties.housenumber, properties.street].filter(Boolean).join(" ") ||
                properties.city ||
                "Unnamed location";
              const secondary = [...new Set([
                properties.name
                  ? [properties.housenumber, properties.street].filter(Boolean).join(" ")
                  : undefined,
                properties.city,
                properties.county,
                properties.state,
                properties.postcode,
                properties.country,
              ].filter((value): value is string => Boolean(value) && value !== primary))];
              const extent = properties.extent;
              return {
                id: `photon-${properties.osm_id ?? index}`,
                label: secondary.length ? `${primary}, ${secondary.join(", ")}` : primary,
                context: `${properties.osm_value ?? properties.type ?? "place"} · OpenStreetMap suggestion`,
                center: feature.geometry!.coordinates!,
                bbox: extent ? [extent[0], extent[3], extent[2], extent[1]] : undefined,
                targetZoom: searchResultZoom(properties.type, properties.osm_value),
                kind: "geocoder",
              };
            });
        };

        const searchMapTiler = async () => {
          if (!mapTilerKey) return [];
          const params = new URLSearchParams({
            key: mapTilerKey,
            autocomplete: "true",
            fuzzyMatch: "true",
            limit: "8",
            language: (navigator.language || "en").split("-")[0],
          });
          const response = await fetch(
            `https://api.maptiler.com/geocoding/${encodeURIComponent(trimmed)}.json?${params}`,
            { signal: controller.signal },
          );
          if (!response.ok) throw new Error(`MapTiler search failed (${response.status}).`);
          const data = (await response.json()) as { features?: MapTilerFeature[] };
          return (data.features ?? [])
            .filter((feature): feature is MapTilerFeature & { center: [number, number] } =>
              Array.isArray(feature.center) && feature.center.length === 2,
            )
            .map((feature, index): SearchResult => ({
              id: feature.id ?? `result-${index}`,
              label: feature.place_name ?? feature.text ?? "Unnamed location",
              context: `${feature.place_type?.[0] ?? "place"} · MapTiler result`,
              center: feature.center,
              bbox: feature.bbox,
              targetZoom: searchResultZoom(...(feature.place_type ?? [])),
              kind: "geocoder",
            }));
        };

        const searches = mapTilerKey
          ? await Promise.allSettled([searchPhoton(), searchMapTiler()])
          : await Promise.allSettled([searchPhoton()]);
        const successful = searches
          .filter((result): result is PromiseFulfilledResult<SearchResult[]> => result.status === "fulfilled")
          .map((result) => result.value);
        if (!successful.length) throw new Error("All location providers failed.");
        const mapped = mergeSearchResults(trimmed, successful);
        autocompleteCacheRef.current.set(cacheKey, mapped);
        setResults(mapped);
        if (mapped.length === 0) setSearchError("No places found. Try a nearby town or enter coordinates.");
      } catch (error) {
        if ((error as Error).name !== "AbortError") {
          setSearchError("Location search is unavailable. Try coordinates or a demo location.");
        }
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, mapTilerKey ? 300 : 450);

    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [autocompleteGeocoderUrl, coordinateResult, mapTilerKey, query]);

  const visibleResults = coordinateResult
    ? [coordinateResult]
    : query.trim().length < 2
      ? []
      : results;
  const visibleSearchError = searchError;

  function choose(result: SearchResult) {
    setQuery(result.label);
    setOpen(false);
    setResults([]);
    setSearchError(undefined);
    setHighlightedIndex(-1);
    onSelect(result);
  }

  async function searchOpenStreetMap() {
    const trimmed = query.trim();
    if (trimmed.length < 2 || coordinateResult || mapTilerKey) return;

    const cacheKey = trimmed.toLocaleLowerCase();
    const cached = fallbackCacheRef.current.get(cacheKey);
    if (cached) {
      setResults(cached);
      setSearchError(cached.length ? undefined : "No places found. Try a nearby town or coordinates.");
      setOpen(true);
      return;
    }

    const now = Date.now();
    if (now - lastFallbackRequestRef.current < 1_000) {
      setSearchError("Please wait a moment before searching again.");
      setOpen(true);
      return;
    }
    lastFallbackRequestRef.current = now;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSearching(true);
    setSearchError(undefined);
    setOpen(true);

    try {
      const params = new URLSearchParams({
        q: trimmed,
        format: "geojson",
        addressdetails: "1",
        limit: "6",
        "accept-language": navigator.language || "en",
      });
      const endpoint = fallbackGeocoderUrl.replace(/\/$/, "");
      const response = await fetch(`${endpoint}/search?${params}`, {
        signal: controller.signal,
        headers: { Accept: "application/geo+json, application/json" },
      });
      if (!response.ok) throw new Error(`OpenStreetMap search failed (${response.status}).`);
      const data = (await response.json()) as { features?: NominatimFeature[] };
      const mapped = (data.features ?? [])
        .filter((feature) =>
          feature.geometry?.type === "Point" &&
          Array.isArray(feature.geometry.coordinates) &&
          feature.geometry.coordinates.length === 2,
        )
        .map((feature, index): SearchResult => ({
          id: feature.id ?? `osm-${feature.properties?.place_id ?? index}`,
          label: feature.properties?.display_name ?? "Unnamed location",
          context: `${feature.properties?.type ?? feature.properties?.category ?? "place"} · OpenStreetMap result`,
          center: feature.geometry!.coordinates!,
          bbox: feature.bbox,
          targetZoom: searchResultZoom(
            feature.properties?.type,
            feature.properties?.category,
          ),
          kind: "geocoder",
        }));
      fallbackCacheRef.current.set(cacheKey, mapped);
      setResults(mapped);
      if (!mapped.length) setSearchError("No places found. Try a nearby town or coordinates.");
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        setSearchError("Place search is temporarily unavailable. Try coordinates or a demo location.");
      }
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }

  const showDemoLocations = open && query.trim().length < 2;
  const fallbackPrompt =
    !coordinateResult && query.trim().length === 2 && !searching && !visibleSearchError;
  const showResults = Boolean(
    open && (visibleResults.length > 0 || showDemoLocations || visibleSearchError || fallbackPrompt),
  );

  return (
    <div className="location-search">
      <form
        className="search-shell"
        onSubmit={(event) => {
          event.preventDefault();
          if (coordinateResult) choose(coordinateResult);
          else if (visibleResults[0]) choose(visibleResults[0]);
          else void searchOpenStreetMap();
        }}
      >
        <button type="submit" className="search-symbol" aria-label="Search location">⌕</button>
        <input
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
            setResults([]);
            setSearchError(undefined);
            setSearching(false);
            setHighlightedIndex(-1);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
            if (event.key === "ArrowDown" && visibleResults.length) {
              event.preventDefault();
              setOpen(true);
              setHighlightedIndex((current) => Math.min(current + 1, visibleResults.length - 1));
            }
            if (event.key === "ArrowUp" && visibleResults.length) {
              event.preventDefault();
              setHighlightedIndex((current) => Math.max(current - 1, 0));
            }
            if (event.key === "Enter" && highlightedIndex >= 0 && visibleResults[highlightedIndex]) {
              event.preventDefault();
              choose(visibleResults[highlightedIndex]);
            }
          }}
          role="combobox"
          aria-expanded={showResults}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={
            highlightedIndex >= 0 ? `${listboxId}-option-${highlightedIndex}` : undefined
          }
          placeholder="Search address, town, place, or 49.788, -112.149"
        />
        {searching && <span className="searching" aria-label="Searching" />}
        {query && !searching && (
          <button
            type="button"
            className="clear-query"
            aria-label="Clear search"
            onClick={() => {
              setQuery("");
              setResults([]);
              setOpen(true);
            }}
          >
            ×
          </button>
        )}
        <button
          type="button"
          className="locate-button"
          onClick={onUseMyLocation}
          disabled={locating}
          aria-label="Use my current location"
        >
          <span aria-hidden="true">◎</span>
          {locating ? "Locating…" : "My location"}
        </button>
      </form>

      {showResults && (
        <div className="search-results" id={listboxId} role="listbox">
          {showDemoLocations && (
            <>
              <div className="result-heading">Try an explicitly labeled demo location</div>
              {demoLocations.map((result) => (
                <ResultButton key={result.id} result={result} onChoose={choose} />
              ))}
            </>
          )}
          {visibleResults.map((result, index) => (
            <ResultButton
              key={result.id}
              id={`${listboxId}-option-${index}`}
              result={result}
              highlighted={index === highlightedIndex}
              onHighlight={() => setHighlightedIndex(index)}
              onChoose={choose}
            />
          ))}
          {visibleSearchError && <p className="search-message">{visibleSearchError}</p>}
          {fallbackPrompt && visibleResults.length === 0 && (
            <p className="search-message search-prompt">Keep typing for location suggestions.</p>
          )}
          {query.trim().length >= 2 && (
            <div className="geocoder-credit">
              {mapTilerKey ? (
                <>Results © MapTiler · suggestions by <a href="https://photon.komoot.io" target="_blank" rel="noreferrer">Photon</a> · data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></>
              ) : (
                <>Suggestions by <a href="https://photon.komoot.io" target="_blank" rel="noreferrer">Photon</a> · data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a></>
              )}
            </div>
          )}
        </div>
      )}
      {locationError && <div className="location-error" role="status">{locationError}</div>}
    </div>
  );
}

function ResultButton({
  id,
  result,
  highlighted = false,
  onHighlight,
  onChoose,
}: {
  id?: string;
  result: SearchResult;
  highlighted?: boolean;
  onHighlight?: () => void;
  onChoose: (result: SearchResult) => void;
}) {
  return (
    <button
      id={id}
      type="button"
      className={highlighted ? "search-result highlighted" : "search-result"}
      role="option"
      aria-selected={highlighted}
      onMouseDown={(event) => event.preventDefault()}
      onMouseEnter={onHighlight}
      onClick={() => onChoose(result)}
    >
      <span className="result-pin" aria-hidden="true">●</span>
      <span>
        <strong>{result.label}</strong>
        <small>{result.context}</small>
      </span>
      <b aria-hidden="true">→</b>
    </button>
  );
}
