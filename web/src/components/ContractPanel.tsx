"use client";

import { useMemo, useState } from "react";
import type {
  AvailabilityResponse,
  Contract,
  ContractSummary,
  OptionAvailability,
} from "@/lib/types";
import { ContractBrowser } from "./ContractBrowser";
import { PlaceSearch } from "./PlaceSearch";
import { Note } from "./ui";

type Source = "built-in" | "upload" | "edit";

const SOURCE_LABEL: Record<Source, string> = {
  "built-in": "Browse contracts",
  upload: "Upload a contract",
  edit: "Edit fields",
};

/** A control the data cannot support, with the reason in place of the control.
 *  Disabling without saying why is the same dead end as the error it replaces,
 *  just quieter. */
function Unavailable({ children }: { children: React.ReactNode }) {
  return <span className="text-xs text-[var(--muted)]">{children}</span>;
}

function speed(option: OptionAvailability | undefined): string {
  if (!option?.available) return "";
  return option.cached ? "cached" : "will fetch";
}

type FieldKind = "text" | "number" | "choice" | "date" | "optional-number";

type Field = {
  path: string;
  label: string;
  kind: FieldKind;
  options?: string[];
  // enum values are wire format, not something to read: a select showing
  // "single_axis_backtracked" is the variable-name problem all over again
  optionLabels?: Record<string, string>;
  step?: number;
};

const GROUPS: { title: string; fields: Field[] }[] = [
  {
    title: "Contract terms",
    fields: [
      { path: "name", label: "Name", kind: "text" },
      {
        path: "counterparty_view",
        label: "Counterparty view",
        kind: "choice",
        options: ["buyer", "seller"],
        optionLabels: { buyer: "Buyer (offtaker)", seller: "Seller (generator)" },
      },
      { path: "strike_usd_mwh", label: "Strike ($/MWh)", kind: "number", step: 0.25 },
      { path: "contract_mw", label: "Contract capacity (MW)", kind: "number", step: 1 },
      { path: "term.start", label: "Term start", kind: "date" },
      { path: "term.end", label: "Term end", kind: "date" },
      {
        path: "settlement_index",
        label: "Settles against",
        kind: "choice",
        options: ["hub", "node"],
        optionLabels: { hub: "Trading hub", node: "Project node" },
      },
      { path: "hub", label: "Hub", kind: "text" },
      { path: "node", label: "Node", kind: "text" },
      {
        path: "negative_price_floor",
        label: "Negative price floor ($/MWh)",
        kind: "optional-number",
        step: 1,
      },
      {
        path: "escalation_pct_yr",
        label: "Escalation (%/yr)",
        kind: "number",
        step: 0.25,
      },
    ],
  },
  {
    title: "Project",
    fields: [
      { path: "project.lat", label: "Latitude", kind: "number", step: 0.001 },
      { path: "project.lon", label: "Longitude", kind: "number", step: 0.001 },
      { path: "project.dc_capacity_mw", label: "DC capacity (MW)", kind: "number", step: 1 },
      { path: "project.tilt_deg", label: "Tilt (degrees)", kind: "number", step: 1 },
      { path: "project.azimuth_deg", label: "Azimuth (degrees)", kind: "number", step: 1 },
      { path: "project.losses_pct", label: "Losses (%)", kind: "number", step: 0.5 },
      {
        path: "project.tracking",
        label: "Mounting",
        kind: "choice",
        options: ["fixed", "single_axis", "single_axis_backtracked"],
        optionLabels: {
          fixed: "Fixed tilt, open rack",
          single_axis: "Single-axis tracking",
          single_axis_backtracked: "Single-axis tracking, backtracked",
        },
      },
    ],
  },
];

const STORAGE_FIELDS: Field[] = [
  { path: "storage.power_mw", label: "Battery power (MW)", kind: "number", step: 1 },
  { path: "storage.duration_hours", label: "Duration (hours)", kind: "number", step: 0.5 },
  {
    path: "storage.round_trip_efficiency",
    label: "Round-trip efficiency",
    kind: "number",
    step: 0.01,
  },
];

const STORAGE_DEFAULT = {
  power_mw: 50,
  duration_hours: 4,
  round_trip_efficiency: 0.85,
};

type Json = Record<string, unknown>;

function get(obj: Json, path: string): unknown {
  return path.split(".").reduce<unknown>((node, key) => {
    if (node && typeof node === "object") return (node as Json)[key];
    return undefined;
  }, obj);
}

function set(obj: Json, path: string, value: unknown): Json {
  const keys = path.split(".");
  const clone = structuredClone(obj);
  let node = clone;
  for (const key of keys.slice(0, -1)) {
    node[key] = { ...(node[key] as Json) };
    node = node[key] as Json;
  }
  node[keys[keys.length - 1]] = value;
  return clone;
}

function show(value: unknown, field?: Field): string {
  if (value === null || value === undefined) return "none";
  return field?.optionLabels?.[String(value)] ?? String(value);
}

function Row({
  field,
  original,
  current,
  onChange,
}: {
  field: Field;
  original: Json;
  current: Json;
  onChange: (path: string, value: unknown) => void;
}) {
  const was = get(original, field.path);
  const now = get(current, field.path);
  const changed = JSON.stringify(was) !== JSON.stringify(now);

  const input = () => {
    switch (field.kind) {
      case "choice":
        return (
          <select
            value={String(now ?? "")}
            onChange={(e) => onChange(field.path, e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1"
          >
            {field.options!.map((o) => (
              <option key={o} value={o}>
                {field.optionLabels?.[o] ?? o}
              </option>
            ))}
          </select>
        );
      case "date":
        return (
          <input
            type="date"
            value={String(now ?? "")}
            onChange={(e) => onChange(field.path, e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1"
          />
        );
      case "optional-number":
        return (
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={now !== null && now !== undefined}
              onChange={(e) => onChange(field.path, e.target.checked ? 0 : null)}
              aria-label={`Apply ${field.label}`}
            />
            <input
              type="number"
              step={field.step}
              disabled={now === null || now === undefined}
              value={now === null || now === undefined ? "" : Number(now)}
              onChange={(e) => onChange(field.path, Number(e.target.value))}
              className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 disabled:opacity-40"
            />
          </div>
        );
      case "number":
        return (
          <input
            type="number"
            step={field.step}
            value={Number(now ?? 0)}
            onChange={(e) => onChange(field.path, Number(e.target.value))}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1"
          />
        );
      default:
        return (
          <input
            type="text"
            value={String(now ?? "")}
            onChange={(e) => onChange(field.path, e.target.value)}
            className="w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1"
          />
        );
    }
  };

  return (
    <div className="grid grid-cols-[1.6fr_1fr_1.4fr] items-center gap-3 border-b border-[var(--border)] py-2 last:border-0">
      <div className="text-sm font-medium">{field.label}</div>
      <div
        className={`text-sm tabular-nums ${changed ? "text-[var(--series-2)] line-through" : "text-[var(--muted)]"}`}
      >
        {show(was, field)}
      </div>
      <div className="text-sm">{input()}</div>
    </div>
  );
}

export function ContractPanel({
  contracts,
  contract,
  onContract,
  year,
  onYear,
  settleAtNode,
  onSettleAtNode,
  weather,
  onWeather,
  availability,
  selectedFile,
  onSelectFile,
}: {
  contracts: ContractSummary[];
  contract: Contract | null;
  onContract: (c: Contract) => void;
  year: number;
  onYear: (y: number) => void;
  settleAtNode: boolean;
  onSettleAtNode: (v: boolean) => void;
  weather: "tmy" | "actual";
  onWeather: (w: "tmy" | "actual") => void;
  availability: AvailabilityResponse | null;
  selectedFile: string;
  onSelectFile: (file: string) => void;
}) {
  const OPEN: OptionAvailability = { available: true, cached: false, reason: null };

  // until availability lands, nothing is claimed unavailable -- a control that
  // flickers to disabled is worse than one that briefly allows a retry
  const years = availability?.years ?? [];
  const current = years.find((row) => row.year === year);
  const actualWeather = current?.actual_weather ?? OPEN;
  const nodeSettlement = current?.node_settlement ?? OPEN;
  const storage = availability?.storage ?? OPEN;

  const [source, setSource] = useState<Source>("built-in");
  // selection lives in the page so the map and the card grid stay in step
  const [uploadError, setUploadError] = useState<string | null>(null);

  const original = useMemo(
    () => contracts.find((c) => c.file === selectedFile)?.contract ?? null,
    [contracts, selectedFile],
  );

  const changedFields = useMemo(() => {
    if (!original || !contract) return [];
    const all = [...GROUPS.flatMap((g) => g.fields), ...STORAGE_FIELDS];
    return all
      .filter(
        (f) =>
          JSON.stringify(get(original as unknown as Json, f.path)) !==
          JSON.stringify(get(contract as unknown as Json, f.path)),
      )
      .map((f) => f.label);
  }, [original, contract]);



  const update = (path: string, value: unknown) => {
    if (!contract) return;
    onContract(set(contract as unknown as Json, path, value) as unknown as Contract);
  };

  // one update, not four: applying a place as separate field edits would send
  // four contracts through validation and leave the county disagreeing with
  // the coordinate in between
  const applyPlace = (place: {
    lat: number;
    lon: number;
    county: string | null;
    state: string | null;
  }) => {
    if (!contract) return;
    onContract({
      ...contract,
      project: {
        ...contract.project,
        lat: Number(place.lat.toFixed(4)),
        lon: Number(place.lon.toFixed(4)),
        county: place.county,
        state: place.state,
      },
    });
  };

  const toggleStorage = (on: boolean) => {
    if (!contract) return;
    onContract({ ...contract, storage: on ? { ...STORAGE_DEFAULT } : null });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 border-b border-[var(--border)]">
        {(Object.keys(SOURCE_LABEL) as Source[]).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setSource(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
              source === key
                ? "border-[var(--series-1)] font-medium"
                : "border-transparent text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {SOURCE_LABEL[key]}
          </button>
        ))}
      </div>

      {(source === "built-in" || source === "edit") && (
        <ContractBrowser
          contracts={contracts}
          selected={selectedFile}
          onSelect={onSelectFile}
        />
      )}

      {source === "upload" && (
        <label className="block text-sm">
          <span className="mb-1 block text-[var(--muted)]">
            Contract JSON — the same shape the API validates
          </span>
          <input
            type="file"
            accept=".json,application/json"
            className="text-sm"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              try {
                onContract(JSON.parse(await file.text()));
                setUploadError(null);
              } catch (err) {
                setUploadError(
                  err instanceof Error ? err.message : "Could not read that file",
                );
              }
            }}
          />
        </label>
      )}

      {uploadError && <Note tone="error">{uploadError}</Note>}

      <div className="flex flex-wrap items-start gap-6 rounded-lg border border-[var(--border)] p-4">
        <label className="text-sm">
          <span className="mb-1 block text-[var(--muted)]">Settlement year</span>
          <select
            value={year}
            onChange={(e) => onYear(Number(e.target.value))}
            className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
          >
            {years.map((row) => (
              <option key={row.year} value={row.year} disabled={!row.analysis.available}>
                {row.year}
                {row.analysis.available
                  ? row.in_term
                    ? ""
                    : " — outside term"
                  : ` — ${row.analysis.reason}`}
              </option>
            ))}
          </select>
        </label>

        <label className="text-sm">
          <span className="mb-1 block text-[var(--muted)]">Weather</span>
          <select
            value={weather}
            onChange={(e) => onWeather(e.target.value as "tmy" | "actual")}
            className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
          >
            <option value="tmy">Typical year (TMY)</option>
            <option value="actual" disabled={!actualWeather.available}>
              Actual weather
              {actualWeather.available ? "" : " — unavailable"}
            </option>
          </select>
          <span className="mt-1 block">
            {actualWeather.available ? (
              <Unavailable>
                Actual {year} weather — {speed(actualWeather)}
              </Unavailable>
            ) : (
              <Unavailable>{actualWeather.reason}</Unavailable>
            )}
          </span>
        </label>

        <div className="text-sm">
          <span className="mb-1 block text-[var(--muted)]">Settlement point</span>
          <label
            className={`flex items-center gap-2 ${
              nodeSettlement.available ? "" : "opacity-50"
            }`}
          >
            <input
              type="checkbox"
              checked={settleAtNode && nodeSettlement.available}
              disabled={!nodeSettlement.available}
              onChange={(e) => onSettleAtNode(e.target.checked)}
            />
            Settle at the project node
          </label>
          <span className="mt-1 block">
            <Unavailable>
              {nodeSettlement.reason ??
                (nodeSettlement.available
                  ? `Nodal prices — ${speed(nodeSettlement)}`
                  : "")}
            </Unavailable>
          </span>
        </div>

        {!storage.available && (
          <div className="text-sm">
            <span className="mb-1 block text-[var(--muted)]">Battery</span>
            <span className="opacity-50">Storage tab off</span>
            <span className="mt-1 block">
              <Unavailable>{storage.reason}</Unavailable>
            </span>
          </div>
        )}
      </div>

      {source === "edit" && contract && original && (
        <div className="rounded-lg border border-[var(--border)] p-4">
          <div className="grid grid-cols-[1.6fr_1fr_1.4fr] gap-3 pb-2 text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
            <div>Field</div>
            <div>Original value</div>
            <div>New value</div>
          </div>

          {GROUPS.map((group) => (
            <div key={group.title} className="mt-4 first:mt-0">
              <h3 className="mb-1 text-sm font-semibold">{group.title}</h3>
              {group.fields.map((f) => (
                <Row
                  key={f.path}
                  field={f}
                  original={original as unknown as Json}
                  current={contract as unknown as Json}
                  onChange={update}
                />
              ))}
              {group.title === "Project" && <PlaceSearch onPick={applyPlace} />}
            </div>
          ))}

          <div className="mt-4">
            <h3 className="mb-1 text-sm font-semibold">Storage overlay</h3>
            <label className="flex items-center gap-2 py-2 text-sm">
              <input
                type="checkbox"
                checked={contract.storage !== null}
                onChange={(e) => toggleStorage(e.target.checked)}
              />
              Pair this project with a battery
            </label>
            {contract.storage &&
              STORAGE_FIELDS.map((f) => (
                <Row
                  key={f.path}
                  field={f}
                  original={original as unknown as Json}
                  current={contract as unknown as Json}
                  onChange={update}
                />
              ))}
          </div>

          <div className="mt-4 text-sm text-[var(--muted)]">
            {changedFields.length
              ? `Changed: ${changedFields.join(", ")}`
              : "No changes yet — values match the contract on disk."}
          </div>
        </div>
      )}
    </div>
  );
}
