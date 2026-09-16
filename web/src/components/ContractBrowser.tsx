"use client";

import { useMemo, useState } from "react";
import type { ContractSummary } from "@/lib/types";

const ZONE_LABEL: Record<string, string> = {
  LZ_WEST: "West Texas",
  LZ_NORTH: "North Texas",
  LZ_SOUTH: "South Texas",
  LZ_HOUSTON: "Houston",
};

const TRACKING_LABEL: Record<string, string> = {
  fixed: "Fixed tilt",
  single_axis: "Single-axis tracking",
  single_axis_backtracked: "Single-axis tracking",
};

const year = (iso: string) => iso.slice(0, 4);

function monthYear(iso: string | null): string | null {
  if (!iso) return null;
  const [y, m] = iso.split("-");
  const months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
  return `${months[Number(m) - 1]} ${y}`;
}

/** One fact on a card. Label above value, so a card scans as a small table
 *  rather than a paragraph of run-together numbers. */
function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-[var(--muted)]">
        {label}
      </div>
      <div className="mt-0.5 text-sm tabular-nums">{value}</div>
    </div>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
      {children}
    </span>
  );
}

export function ContractBrowser({
  contracts,
  selected,
  onSelect,
}: {
  contracts: ContractSummary[];
  selected: string;
  onSelect: (file: string) => void;
}) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matches = !q
      ? contracts
      : contracts.filter((c) =>
          [c.label, c.location, c.zone ? ZONE_LABEL[c.zone] : null, c.settlement_point]
            .filter(Boolean)
            .some((field) => String(field).toLowerCase().includes(q)),
        );
    // real assets first, largest first; the schema demo sorts last because it
    // is the one contract whose node does not exist
    return [...matches].sort((a, b) => {
      const real = (c: ContractSummary) => (c.contract.project.eia_plant_id ? 0 : 1);
      return real(a) - real(b) || b.contract_mw - a.contract_mw;
    });
  }, [contracts, query]);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name, county or region"
          className="w-64 rounded border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-sm"
        />
        <span className="text-sm text-[var(--muted)]">
          {visible.length} of {contracts.length} contracts
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {visible.map((c) => {
          const active = c.file === selected;
          return (
            <button
              key={c.file}
              type="button"
              onClick={() => onSelect(c.file)}
              aria-pressed={active}
              className={`rounded-lg border p-4 text-left transition-colors ${
                active
                  ? "border-[var(--series-1)] bg-[var(--surface)] ring-1 ring-[var(--series-1)]"
                  : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--muted)]"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-semibold leading-snug">{c.label}</span>
                {active && (
                  <span className="shrink-0 text-[11px] font-medium text-[var(--series-1)]">
                    Selected
                  </span>
                )}
              </div>

              <div className="mt-1 text-xs text-[var(--muted)]">
                {c.location ?? "Location not recorded"}
                {c.zone ? ` · ${ZONE_LABEL[c.zone] ?? c.zone}` : ""}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2">
                <Fact label="Capacity" value={`${c.contract_mw.toLocaleString()} MW`} />
                <Fact
                  label="Term"
                  value={`${year(c.term_start)}–${year(c.term_end)}`}
                />
                <Fact
                  label="Strike"
                  value={`$${c.contract.strike_usd_mwh.toFixed(2)}/MWh`}
                />
                <Fact
                  label="Settles at"
                  value={
                    c.settles_at === "hub"
                      ? `${c.settlement_point} (hub)`
                      : `${c.settlement_point} (node)`
                  }
                />
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge>{TRACKING_LABEL[c.tracking] ?? c.tracking}</Badge>
                {c.has_storage && <Badge>{c.storage_mw} MW battery</Badge>}
                {c.commercial_operation && (
                  <Badge>Online {monthYear(c.commercial_operation)}</Badge>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {visible.length === 0 && (
        <p className="py-6 text-sm text-[var(--muted)]">
          No contract matches “{query}”.
        </p>
      )}
    </div>
  );
}
