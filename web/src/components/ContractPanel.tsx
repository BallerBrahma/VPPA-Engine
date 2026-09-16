"use client";

import { useMemo, useState } from "react";
import type { Contract, ContractSummary } from "@/lib/types";
import { Note } from "./ui";

type Source = "built-in" | "upload" | "edit";

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
}) {
  const [source, setSource] = useState<Source>("built-in");
  const [baseFile, setBaseFile] = useState<string>("");
  const [uploadError, setUploadError] = useState<string | null>(null);

  const original = useMemo(
    () => contracts.find((c) => c.file === baseFile)?.contract ?? null,
    [contracts, baseFile],
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

  const pick = (file: string) => {
    setBaseFile(file);
    const found = contracts.find((c) => c.file === file);
    if (found) onContract(found.contract);
  };

  const update = (path: string, value: unknown) => {
    if (!contract) return;
    onContract(set(contract as unknown as Json, path, value) as unknown as Contract);
  };

  const toggleStorage = (on: boolean) => {
    if (!contract) return;
    onContract({ ...contract, storage: on ? { ...STORAGE_DEFAULT } : null });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <label className="text-sm">
          <span className="mb-1 block text-[var(--muted)]">Contract source</span>
          <select
            value={source}
            onChange={(e) => setSource(e.target.value as Source)}
            className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
          >
            <option value="built-in">Built-in</option>
            <option value="upload">Upload JSON</option>
            <option value="edit">Edit fields</option>
          </select>
        </label>

        {(source === "built-in" || source === "edit") && (
          <label className="text-sm">
            <span className="mb-1 block text-[var(--muted)]">
              {source === "edit" ? "Start from" : "Contract"}
            </span>
            <select
              value={baseFile}
              onChange={(e) => pick(e.target.value)}
              className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
            >
              {contracts.map((c) => (
                <option key={c.file} value={c.file}>
                  {c.contract.name}
                </option>
              ))}
            </select>
          </label>
        )}

        {source === "upload" && (
          <label className="text-sm">
            <span className="mb-1 block text-[var(--muted)]">Contract JSON</span>
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

        <label className="text-sm">
          <span className="mb-1 block text-[var(--muted)]">Year</span>
          <select
            value={year}
            onChange={(e) => onYear(Number(e.target.value))}
            className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1.5"
          >
            {[2025, 2024, 2023].map((y) => (
              <option key={y} value={y}>
                {y}
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
            <option value="actual">Actual weather</option>
          </select>
        </label>

        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input
            type="checkbox"
            checked={settleAtNode}
            onChange={(e) => onSettleAtNode(e.target.checked)}
          />
          Settle at node
        </label>
      </div>

      {uploadError && <Note tone="error">{uploadError}</Note>}

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
