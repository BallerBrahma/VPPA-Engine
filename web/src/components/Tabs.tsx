"use client";

import { useState } from "react";
import type {
  BasisResponse,
  ScenariosResponse,
  SettlementResponse,
  StorageResponse,
} from "@/lib/types";
import { mwh, pct, points, usd, usdCompact } from "@/lib/format";
import { DualSeriesChart } from "./Charts";
import { Caption, Note, Table } from "./ui";

const TABS = ["Monthly statement", "Basis", "Scenarios", "Storage"] as const;
type Tab = (typeof TABS)[number];

export function ResultTabs({
  settlement,
  basis,
  scenarios,
  storage,
  basisError,
  storageError,
  settleAtNode,
}: {
  settlement: SettlementResponse;
  basis: BasisResponse | null;
  scenarios: ScenariosResponse | null;
  storage: StorageResponse | null;
  basisError: string | null;
  storageError: string | null;
  settleAtNode: boolean;
}) {
  const [tab, setTab] = useState<Tab>("Monthly statement");

  return (
    <div>
      <div className="mb-5 flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "border-b-2 border-[var(--series-1)] text-[var(--foreground)]"
                : "text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Monthly statement" && (
        <>
          <Table
            columns={[
              "Month",
              "Generation (MWh)",
              "Realized price",
              "Avg market price",
              "Cash to buyer",
            ]}
            rows={settlement.monthly.map((m) => [
              m.month,
              Math.round(m.generation_mwh).toLocaleString("en-US"),
              m.realized_price_usd_mwh === null ? "—" : usd(m.realized_price_usd_mwh),
              usd(m.avg_market_price_usd_mwh),
              usd(m.cash_to_buyer_usd, 0),
            ])}
          />
          <Caption>
            Realized price is generation-weighted; average market price is a plain hourly
            mean. The gap between those two columns is the shape effect.
          </Caption>
          <div className="mt-4">
            <DualSeriesChart
              data={settlement.monthly.map((m) => ({
                month: m.month,
                realized: m.realized_price_usd_mwh,
                market: m.avg_market_price_usd_mwh,
              }))}
              xKey="month"
              yLabel="$/MWh"
              series={[
                { key: "realized", name: "Realized price", color: "var(--series-1)" },
                { key: "market", name: "Avg market price", color: "var(--series-2)" },
              ]}
            />
          </div>
        </>
      )}

      {tab === "Basis" && (
        <>
          {!settleAtNode && (
            <Note>Turn on <strong>Settle at node</strong> above to load nodal prices.</Note>
          )}
          {settleAtNode && basisError && <Note tone="error">{basisError}</Note>}
          {basis && (
            <>
              <div className="mb-5 grid gap-4 sm:grid-cols-3">
                <Stat label="Cost of basis" value={`${usd(basis.cost_of_basis_usd_mwh)}/MWh`} />
                <Stat label="Mean basis" value={`${usd(basis.mean_basis_usd_mwh)}/MWh`} />
                <Stat
                  label="Negative-basis hours"
                  value={basis.negative_basis_hours.toLocaleString("en-US")}
                  sub={`${pct(basis.negative_basis_share, 0)} of hours`}
                />
              </div>
              <DualSeriesChart
                data={basis.monthly.map((m) => ({
                  month: m.month,
                  basis: m.mean_basis_usd_mwh,
                }))}
                xKey="month"
                yLabel="$/MWh"
                zeroLine
                series={[{ key: "basis", name: "Mean basis", color: "var(--series-1)" }]}
              />
              <Caption>
                Cost of basis is generation-weighted; mean basis is not. When the first is
                worse than the second, congestion is landing in the hours the plant is
                actually running.
              </Caption>
            </>
          )}
        </>
      )}

      {tab === "Scenarios" && scenarios && (
        <>
          <Table
            columns={[
              "Scenario",
              "Generation (MWh)",
              "Capture rate",
              "Breakeven strike",
              "Cash to buyer",
            ]}
            rows={scenarios.scenarios.map((s) => [
              s.label,
              Math.round(s.generation_mwh).toLocaleString("en-US"),
              pct(s.capture_rate),
              usd(s.breakeven_strike_usd_mwh),
              usdCompact(s.cash_to_buyer_usd),
            ])}
          />
          <Caption>
            A P90 year can <em>improve</em> the buyer&apos;s position on an underwater deal —
            less production means less volume to pay out on. P90 is a downside case for the
            seller, which is why these are read per counterparty rather than as one
            &ldquo;bad case&rdquo; number.
          </Caption>
        </>
      )}

      {tab === "Storage" && (
        <>
          {storageError && <Note tone="error">{storageError}</Note>}
          {storage && (
            <>
              <div className="mb-5 grid gap-4 sm:grid-cols-3">
                <Stat
                  label="Capture rate with storage"
                  value={pct(storage.capture_rate_with_storage)}
                  sub={`${points(storage.uplift_points)} vs ${pct(storage.capture_rate_base)}`}
                />
                <Stat
                  label="Revenue uplift"
                  value={usdCompact(storage.revenue_uplift_usd)}
                  sub={`${usdCompact(storage.revenue_uplift_daily_usd)} solved a day at a time`}
                />
                <Stat
                  label="Round-trip loss"
                  value={mwh(storage.round_trip_loss_mwh)}
                  sub={`${Math.round(storage.cycles).toLocaleString("en-US")} cycles`}
                />
              </div>

              <div className="mb-5 grid gap-4 sm:grid-cols-3">
                <Stat
                  label="Foresight premium"
                  value={usdCompact(storage.foresight_premium_usd)}
                  sub={`${pct(
                    storage.revenue_uplift_usd
                      ? storage.foresight_premium_usd / storage.revenue_uplift_usd
                      : 0,
                    0,
                  )} of the uplift needs the whole year in advance`}
                />
                <Stat
                  label="Degradation charged"
                  value={usdCompact(-storage.cycling_cost_usd)}
                  sub={
                    storage.cycling_cost_usd
                      ? "amortised wear, per MWh discharged"
                      : "no cycling cost set — wear is free here"
                  }
                />
                <Stat
                  label="Curtailed instead of stored"
                  value={mwh(storage.curtailed_mwh)}
                  sub="energy the battery declined to absorb"
                />
              </div>

              <Note tone="warn">
                Still an upper bound. The headline figure optimises against the whole
                year&apos;s realised prices at once; the day-at-a-time figure beside it is
                closer to what a day-ahead bidder actually knows, and the gap between them
                is foresight nobody has. Neither carries capex.
              </Note>
              <div className="mt-4">
                <DualSeriesChart
                  data={storage.average_day.map((h) => ({
                    hour: `${String(h.hour).padStart(2, "0")}:00`,
                    generation: h.generation_mwh,
                    delivered: h.delivered_mwh,
                  }))}
                  xKey="hour"
                  yLabel="MWh"
                  series={[
                    { key: "generation", name: "Solar generation", color: "var(--series-1)" },
                    { key: "delivered", name: "Delivered with storage", color: "var(--series-2)" },
                  ]}
                />
              </div>
              <Caption>
                Average day, {storage.power_mw.toLocaleString("en-US")} MW /{" "}
                {storage.energy_capacity_mwh.toLocaleString("en-US")} MWh at{" "}
                {pct(storage.round_trip_efficiency, 0)} round-trip: storage moves output out
                of midday into the evening peak.
              </Caption>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-1 text-sm text-[var(--muted)]">{sub}</div>}
    </div>
  );
}
