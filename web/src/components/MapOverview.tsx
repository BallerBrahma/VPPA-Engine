"use client";

import { useEffect, useRef } from "react";
import type { CircleMarker, Map as LeafletMap, TileLayer } from "leaflet";
import "leaflet/dist/leaflet.css";
import type { ContractSummary } from "@/lib/types";

// CARTO's raster basemaps, which render OpenStreetMap data in a light and a
// dark style. A single OSM standard layer would strand the app's dark theme on
// a bright basemap; these are the same underlying data, differently painted.
const TILES = {
  light: "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
  dark: "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
} as const;

const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ' +
  '&copy; <a href="https://carto.com/attributions">CARTO</a>';

const ZONE_LABEL: Record<string, string> = {
  LZ_WEST: "West Texas",
  LZ_NORTH: "North Texas",
  LZ_SOUTH: "South Texas",
  LZ_HOUSTON: "Houston",
};

/** Radius in pixels for a project's capacity.
 *
 *  Area scales with MW, not radius — a 350 MW plant reads as 3.5x a 100 MW one
 *  only if the circle's area carries the number. Sizing by radius would make it
 *  look twelve times bigger. */
function radiusFor(mw: number): number {
  const MIN = 6;
  const PER_MW = 0.9;
  return MIN + Math.sqrt(mw) * PER_MW;
}

/** Palette read from the app's own tokens, so the map cannot drift from the
 *  charts. Read at call time rather than module scope: the tokens change with
 *  the colour scheme. */
function palette() {
  const styles = getComputedStyle(document.documentElement);
  const token = (name: string, fallback: string) =>
    styles.getPropertyValue(name).trim() || fallback;
  return {
    base: token("--series-1", "#2a78d6"),
    active: token("--series-2", "#eb6834"),
    // the ring is the page surface, which is what makes a mark read as
    // separate from both the basemap and its overlapping neighbours
    ring: token("--surface", "#ffffff"),
  };
}

function styleFor(selected: boolean) {
  const { base, active, ring } = palette();
  return {
    color: ring,
    fillColor: selected ? active : base,
    weight: 2,
    opacity: 1,
    fillOpacity: 0.85,
  };
}

function prefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function popupHtml(c: ContractSummary): string {
  const rows: [string, string][] = [
    ["Capacity", `${c.contract_mw.toLocaleString()} MW`],
    ["Strike", `$${c.contract.strike_usd_mwh.toFixed(2)}/MWh`],
    ["Settles at", `${c.settlement_point} (${c.settles_at})`],
  ];
  if (c.has_storage) rows.push(["Battery", `${c.storage_mw} MW`]);

  const detail = rows
    .map(
      ([k, v]) =>
        `<div style="display:flex;justify-content:space-between;gap:12px">
           <span style="opacity:.65">${k}</span><span>${v}</span>
         </div>`,
    )
    .join("");

  return `<div style="min-width:180px;font:13px/1.45 system-ui,sans-serif">
    <div style="font-weight:600;margin-bottom:2px">${c.label}</div>
    <div style="opacity:.65;margin-bottom:6px">
      ${c.location ?? "Location not recorded"}${c.zone ? ` · ${ZONE_LABEL[c.zone] ?? c.zone}` : ""}
    </div>
    ${detail}
  </div>`;
}

export function MapOverview({
  contracts,
  selected,
  onSelect,
}: {
  contracts: ContractSummary[];
  selected: string;
  onSelect: (file: string) => void;
}) {
  const container = useRef<HTMLDivElement | null>(null);
  const map = useRef<LeafletMap | null>(null);
  const tiles = useRef<TileLayer | null>(null);
  const markers = useRef<Map<string, CircleMarker>>(new Map());
  // Read inside the async marker build, which must not list `selected` as a
  // dependency or every click would rebuild the markers. Mirrored in an effect
  // rather than assigned during render.
  const selectedRef = useRef(selected);
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);

  // Leaflet touches `window` at import, so it is loaded inside the effect
  // rather than at module scope; this component is also only ever rendered
  // client-side (see the dynamic import in page.tsx).
  useEffect(() => {
    let cancelled = false;
    let cleanup = () => {};

    import("leaflet").then((L) => {
      if (cancelled || !container.current || map.current) return;

      const instance = L.map(container.current, {
        scrollWheelZoom: false, // a page-scroll that eats the wheel is hostile
        attributionControl: true,
      });
      map.current = instance;

      tiles.current = L.tileLayer(prefersDark() ? TILES.dark : TILES.light, {
        attribution: ATTRIBUTION,
        maxZoom: 18,
      }).addTo(instance);

      const scheme = window.matchMedia("(prefers-color-scheme: dark)");
      const repaint = () => tiles.current?.setUrl(prefersDark() ? TILES.dark : TILES.light);
      scheme.addEventListener("change", repaint);

      cleanup = () => {
        scheme.removeEventListener("change", repaint);
        instance.remove();
        map.current = null;
        markers.current.clear();
      };
    });

    return () => {
      cancelled = true;
      cleanup();
    };
  }, []);

  // Markers are rebuilt when the contract list changes, then only restyled on
  // selection — recreating them on every select would close the open popup.
  useEffect(() => {
    if (!map.current || contracts.length === 0) return;
    let cancelled = false;

    import("leaflet").then((L) => {
      const instance = map.current;
      if (cancelled || !instance) return;

      markers.current.forEach((m) => m.remove());
      markers.current.clear();

      contracts.forEach((c) => {
        // styled at creation, not left to the selection effect below: markers
        // are added asynchronously, so that effect can run before they exist
        // and the first paint would show Leaflet's default blue
        const marker = L.circleMarker([c.contract.project.lat, c.contract.project.lon], {
          radius: radiusFor(c.contract_mw),
          ...styleFor(c.file === selectedRef.current),
        })
          .addTo(instance)
          .bindPopup(popupHtml(c))
          .bindTooltip(`${c.label} — ${c.contract_mw.toLocaleString()} MW`)
          .on("click", () => onSelect(c.file));
        markers.current.set(c.file, marker);
      });

      const bounds = L.latLngBounds(
        contracts.map((c) => [c.contract.project.lat, c.contract.project.lon]),
      );
      instance.fitBounds(bounds, { padding: [36, 36], maxZoom: 7 });
    });

    return () => {
      cancelled = true;
    };
  }, [contracts, onSelect]);

  // Selection is a restyle, not a rebuild -- rebuilding would close an open
  // popup on every click.
  useEffect(() => {
    markers.current.forEach((marker, file) => {
      const on = file === selected;
      marker.setStyle(styleFor(on));
      if (on) marker.bringToFront();
    });
  }, [selected, contracts]);

  return (
    <div>
      <div
        ref={container}
        role="region"
        aria-label="Map of contracted solar projects"
        className="h-[380px] w-full rounded-lg border border-[var(--border)] bg-[var(--surface)]"
      />
      <p className="mt-2 text-sm text-[var(--muted)]">
        Circle area is contracted capacity; the selected project is highlighted. Click a
        project to load it. Coordinates come from EIA-860, not from geocoding.
      </p>
    </div>
  );
}
