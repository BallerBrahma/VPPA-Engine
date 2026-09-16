"use client";

import type { ReactNode } from "react";

export function Card({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5 ${className}`}
    >
      {title && (
        <h2 className="mb-4 text-sm font-semibold tracking-wide uppercase text-[var(--muted)]">
          {title}
        </h2>
      )}
      {children}
    </section>
  );
}

export function Metric({
  label,
  value,
  delta,
  tone = "neutral",
}: {
  label: string;
  value: string;
  delta?: string;
  tone?: "neutral" | "positive" | "negative";
}) {
  const deltaColor =
    tone === "positive"
      ? "text-[var(--positive)]"
      : tone === "negative"
        ? "text-[var(--negative)]"
        : "text-[var(--muted)]";
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--muted)]">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {delta && <div className={`mt-1 text-sm tabular-nums ${deltaColor}`}>{delta}</div>}
    </div>
  );
}

export function Note({
  children,
  tone = "info",
}: {
  children: ReactNode;
  tone?: "info" | "warn" | "error";
}) {
  const styles = {
    info: "border-[var(--border)] text-[var(--muted)]",
    warn: "border-[var(--series-2)] text-[var(--foreground)]",
    error: "border-[var(--negative)] text-[var(--negative)]",
  }[tone];
  return (
    <div className={`rounded-md border-l-4 bg-[var(--surface)] px-4 py-3 text-sm ${styles}`}>
      {children}
    </div>
  );
}

export function Caption({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-sm leading-relaxed text-[var(--muted)]">{children}</p>;
}

export function Table({
  columns,
  rows,
}: {
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <div className="table-scroll">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((c, i) => (
              <th
                key={c}
                className={`px-3 py-2 font-medium text-[var(--muted)] ${
                  i === 0 ? "text-left" : "text-right"
                }`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b border-[var(--border)] last:border-0">
              {row.map((cell, i) => (
                <td
                  key={i}
                  className={`px-3 py-2 tabular-nums ${
                    i === 0 ? "text-left font-medium" : "text-right"
                  }`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-10 text-sm text-[var(--muted)]">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--series-1)]" />
      {label}
    </div>
  );
}
