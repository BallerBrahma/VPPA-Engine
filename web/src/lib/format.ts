export const usd = (v: number, digits = 2) =>
  v.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });

export const usdCompact = (v: number) => {
  const millions = v / 1e6;
  return `${millions < 0 ? "-" : ""}$${Math.abs(millions).toFixed(2)}M`;
};

export const mwh = (v: number) =>
  `${Math.round(v).toLocaleString("en-US")} MWh`;

export const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;

export const points = (v: number) =>
  `${v >= 0 ? "+" : ""}${v.toFixed(1)} pts`;
