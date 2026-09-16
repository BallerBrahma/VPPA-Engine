"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const AXIS = { stroke: "var(--muted)", fontSize: 12 };

/** Two series sharing one axis. Never a second y-scale: a dual axis invites
 *  reading a crossing point that means nothing. */
export function DualSeriesChart({
  data,
  xKey,
  series,
  yLabel,
  zeroLine = false,
}: {
  data: Record<string, unknown>[];
  xKey: string;
  series: { key: string; name: string; color: string }[];
  yLabel: string;
  zeroLine?: boolean;
}) {
  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={xKey} tick={AXIS} tickLine={false} stroke="var(--grid)" />
          <YAxis
            tick={AXIS}
            tickLine={false}
            stroke="var(--grid)"
            label={{
              value: yLabel,
              angle: -90,
              position: "insideLeft",
              style: { fill: "var(--muted)", fontSize: 12 },
            }}
          />
          <Tooltip
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--foreground)",
              fontSize: 13,
            }}
          />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 13 }} />}
          {zeroLine && <ReferenceLine y={0} stroke="var(--muted)" strokeDasharray="4 4" />}
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.name}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
