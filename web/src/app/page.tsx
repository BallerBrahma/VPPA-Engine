"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { ContractPanel } from "@/components/ContractPanel";
import { ResultTabs } from "@/components/Tabs";
import { Card, Metric, Note, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

// Leaflet reaches for `window` as it loads, so the map never server-renders.
const MapOverview = dynamic(
  () => import("@/components/MapOverview").then((m) => m.MapOverview),
  {
    ssr: false,
    loading: () => (
      <div className="h-[380px] w-full animate-pulse rounded-lg border border-[var(--border)] bg-[var(--surface)]" />
    ),
  },
);
import { mwh, pct, usd, usdCompact } from "@/lib/format";
import type {
  AnalysisRequest,
  AvailabilityResponse,
  BasisResponse,
  Contract,
  ContractSummary,
  ScenariosResponse,
  SettlementResponse,
  StorageResponse,
} from "@/lib/types";

const message = (e: unknown) =>
  e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e);

export default function Home() {
  const [contracts, setContracts] = useState<ContractSummary[]>([]);
  const [contract, setContract] = useState<Contract | null>(null);
  const [selectedFile, setSelectedFile] = useState("");
  const [year, setYear] = useState(2025);
  const [settleAtNode, setSettleAtNode] = useState(false);
  const [weather, setWeather] = useState<"tmy" | "actual">("tmy");
  const [availability, setAvailability] = useState<AvailabilityResponse | null>(null);

  const [settlement, setSettlement] = useState<SettlementResponse | null>(null);
  const [basis, setBasis] = useState<BasisResponse | null>(null);
  const [scenarios, setScenarios] = useState<ScenariosResponse | null>(null);
  const [storage, setStorage] = useState<StorageResponse | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [basisError, setBasisError] = useState<string | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);

  useEffect(() => {
    api
      .contracts()
      .then((list) => {
        setContracts(list);
        if (list.length) {
          setContract(list[0].contract);
          setSelectedFile(list[0].file);
        }
      })
      .catch((e) =>
        setError(
          `${message(e)} — is the API running? Start it with: uv run uvicorn vppa.api.main:app --port 8000`,
        ),
      );
  }, []);

  // Ask what this contract supports before offering it. Controls the data
  // cannot back are disabled with a reason rather than failing a run, so the
  // request that goes out is always one the server can answer.
  useEffect(() => {
    if (!contract) return;
    let stale = false;
    api
      .availability(contract)
      .then((next) => {
        if (stale) return;
        setAvailability(next);

        const row = next.years.find((y) => y.year === year);
        if (!row?.analysis.available && next.default_year) setYear(next.default_year);
        if (row && !row.actual_weather.available) setWeather("tmy");
        if (row && !row.node_settlement.available) setSettleAtNode(false);
      })
      .catch(() => {
        // availability is an optimisation, not a gate: if it fails, leave every
        // control enabled and let the analysis report its own errors
        if (!stale) setAvailability(null);
      });
    return () => {
      stale = true;
    };
    // `year` is deliberately excluded: this re-checks when the contract or the
    // offered years change, and clamping year here would fight the user's own
    // selection on every render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contract]);

  const selectContract = useCallback(
    (file: string) => {
      const found = contracts.find((c) => c.file === file);
      if (!found) return;
      setSelectedFile(file);
      setContract(found.contract);
    },
    [contracts],
  );

  const totalMw = useMemo(
    () => contracts.reduce((sum, c) => sum + c.contract_mw, 0),
    [contracts],
  );

  const run = useCallback(async () => {
    if (!contract) return;
    const request: AnalysisRequest = { contract, year, settle_at_node: settleAtNode, weather };

    setLoading(true);
    setError(null);
    setBasisError(null);
    setStorageError(null);
    setBasis(null);
    setStorage(null);

    try {
      // settlement and scenarios always apply; basis needs nodal prices and
      // storage needs a battery, so their absence is reported per-tab rather
      // than failing the whole run
      const [settled, scen] = await Promise.all([
        api.settlement(request),
        api.scenarios(request),
      ]);
      setSettlement(settled);
      setScenarios(scen);

      if (settleAtNode) {
        await api.basis(request).then(setBasis).catch((e) => setBasisError(message(e)));
      }
      if (contract.storage) {
        await api.storage(request).then(setStorage).catch((e) => setStorageError(message(e)));
      } else {
        setStorageError("This contract has no battery. Add one under Edit fields.");
      }
    } catch (e) {
      setError(message(e));
      setSettlement(null);
    } finally {
      setLoading(false);
    }
  }, [contract, year, settleAtNode, weather]);

  const underwater =
    settlement && settlement.breakeven_strike_usd_mwh < settlement.strike_usd_mwh;

  return (
    <main className="mx-auto max-w-6xl px-6 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Solar VPPA Settlement &amp; Basis</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Settles virtual PPAs for utility-scale solar and quantifies the basis and shape
          risk buried in them.
        </p>
      </header>

      {contracts.length > 0 && (
        <Card title="Contracted projects" className="mb-6">
          <p className="mb-3 text-sm text-[var(--muted)]">
            {contracts.length} deals across {totalMw.toLocaleString()} MW of ERCOT
            solar. West Texas sits in the state&apos;s densest solar cluster, which is
            where capture rates are worst — the map is the geography behind that result.
          </p>
          <MapOverview
            contracts={contracts}
            selected={selectedFile}
            onSelect={selectContract}
          />
        </Card>
      )}

      <Card title="Contract" className="mb-6">
        <ContractPanel
          contracts={contracts}
          contract={contract}
          onContract={setContract}
          year={year}
          onYear={setYear}
          settleAtNode={settleAtNode}
          onSettleAtNode={setSettleAtNode}
          weather={weather}
          onWeather={setWeather}
          availability={availability}
          selectedFile={selectedFile}
          onSelectFile={selectContract}
        />
        <div className="mt-5 flex items-center gap-4">
          <button
            onClick={run}
            disabled={!contract || loading}
            className="rounded-md bg-[var(--series-1)] px-5 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {loading ? "Running…" : "Run analysis"}
          </button>
          <span className="text-sm text-[var(--muted)]">
            A cold contract-year runs a PVWatts simulation and a year of prices; results
            are cached after the first run.
          </span>
        </div>
      </Card>

      {error && (
        <div className="mb-6">
          <Note tone="error">{error}</Note>
        </div>
      )}

      {loading && <Spinner label="Fetching generation and prices…" />}

      {settlement && !loading && (
        <>
          <h2 className="mb-4 text-lg font-medium">
            {contract?.display_name ?? settlement.contract_name} — {settlement.year},
            settled at {settlement.settlement_point}
          </h2>

          <div className="mb-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Capture rate" value={pct(settlement.capture_rate)} />
            <Metric
              label="Breakeven strike"
              value={`${usd(settlement.breakeven_strike_usd_mwh)}/MWh`}
              delta={`${usd(
                settlement.breakeven_strike_usd_mwh - settlement.strike_usd_mwh,
              )} vs contract strike`}
              tone={underwater ? "negative" : "positive"}
            />
            <Metric label="Generation" value={mwh(settlement.generation_mwh)} />
            <Metric
              label={`Net cash to ${settlement.counterparty}`}
              value={usdCompact(settlement.cash_to_counterparty_usd)}
              tone={settlement.cash_to_counterparty_usd < 0 ? "negative" : "positive"}
            />
          </div>

          <div className="mb-6 space-y-3">
            {!settlement.in_term && (
              <Note>
                {settlement.year} falls outside this contract&apos;s term; shown as a
                counterfactual.
              </Note>
            )}
            {settlement.strike_usd_mwh !== settlement.base_strike_usd_mwh && (
              <Note>
                Strike escalated from {usd(settlement.base_strike_usd_mwh)} to{" "}
                {usd(settlement.strike_usd_mwh)}/MWh.
              </Note>
            )}
            {underwater && (
              <Note tone="warn">
                The contract strike ({usd(settlement.strike_usd_mwh)}/MWh) is above the
                breakeven strike ({usd(settlement.breakeven_strike_usd_mwh)}/MWh): on this
                production shape the deal is underwater for the buyer.
              </Note>
            )}
            {settlement.notes.map((n) => (
              <Note key={n}>{n}</Note>
            ))}
          </div>

          <Card>
            <ResultTabs
              settlement={settlement}
              basis={basis}
              scenarios={scenarios}
              storage={storage}
              basisError={basisError}
              storageError={storageError}
              settleAtNode={settleAtNode}
            />
          </Card>
        </>
      )}
    </main>
  );
}
