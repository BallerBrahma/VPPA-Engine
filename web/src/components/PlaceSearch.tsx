"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { PlaceResult } from "@/lib/types";

/** Move a project to a named place.
 *
 *  Only reachable from the editor, and deliberately so: every shipped contract
 *  already carries a surveyed coordinate from EIA-860, and replacing one with
 *  the centroid of a county would be a downgrade. This is for a deal being
 *  written against a site that has no EIA row yet. */
export function PlaceSearch({
  onPick,
}: {
  onPick: (place: PlaceResult) => void;
}) {
  const [query, setQuery] = useState("");
  const [places, setPlaces] = useState<PlaceResult[]>([]);
  const [status, setStatus] = useState<"idle" | "searching" | "empty" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setStatus("searching");
    setError(null);
    try {
      const { places: found } = await api.geocode(query);
      setPlaces(found);
      setStatus(found.length ? "idle" : "empty");
    } catch (err) {
      setPlaces([]);
      setStatus("error");
      setError(err instanceof ApiError ? err.message : "Place lookup failed");
    }
  };

  return (
    <div className="mt-3 rounded-md border border-[var(--border)] p-3">
      <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
        <label className="flex-1 text-sm">
          <span className="mb-1 block text-[var(--muted)]">
            Move this project to a place
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. Pecos County, Texas"
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
          />
        </label>
        <button
          type="submit"
          disabled={status === "searching" || !query.trim()}
          className="mt-5 rounded border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-40"
        >
          {status === "searching" ? "Searching…" : "Search"}
        </button>
      </form>

      {status === "empty" && (
        <p className="mt-2 text-sm text-[var(--muted)]">No place matched that name.</p>
      )}
      {status === "error" && (
        <p className="mt-2 text-sm text-[var(--negative)]">{error}</p>
      )}

      {places.length > 0 && (
        <ul className="mt-2 space-y-1">
          {places.map((place) => (
            <li key={`${place.lat},${place.lon}`}>
              <button
                type="button"
                onClick={() => {
                  onPick(place);
                  setPlaces([]);
                  setQuery("");
                }}
                className="w-full rounded px-2 py-1.5 text-left text-sm hover:bg-[var(--background)]"
              >
                <span className="block">{place.display_name}</span>
                <span className="block text-xs tabular-nums text-[var(--muted)]">
                  {place.lat.toFixed(4)}, {place.lon.toFixed(4)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-2 text-xs text-[var(--muted)]">
        Searches OpenStreetMap via Nominatim. A place centroid is far coarser than a
        surveyed plant location, so this changes the modelled weather site — expect the
        generation profile to move with it.
      </p>
    </div>
  );
}
