import type {
  AnalysisRequest,
  AvailabilityResponse,
  BasisResponse,
  Contract,
  ContractSummary,
  GeocodeResponse,
  ScenariosResponse,
  SettlementResponse,
  StorageResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Error carrying the API's own message, so the UI can show why a request
 *  failed (a missing key, an unknown node) rather than a generic failure. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function unwrap(response: Response) {
  if (response.ok) return response.json();

  let detail = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      // FastAPI validation errors: surface the offending field, not a blob.
      // pydantic prefixes custom validators with "Value error, ", which is
      // noise in a form that already names the field.
      detail = body.detail
        .map((e: { loc?: (string | number)[]; msg?: string }) => {
          const field = (e.loc ?? []).filter((p) => p !== "body").join(".");
          const msg = (e.msg ?? "").replace(/^Value error,\s*/, "");
          return field ? `${field}: ${msg}` : msg;
        })
        .join("; ");
    }
  } catch {
    /* response had no JSON body; keep the status-based message */
  }
  throw new ApiError(detail, response.status);
}

function post(path: string, body: unknown) {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(unwrap);
}

export const api = {
  contracts: (): Promise<ContractSummary[]> =>
    fetch(`${BASE}/api/contracts`).then(unwrap),
  settlement: (r: AnalysisRequest): Promise<SettlementResponse> =>
    post("/api/settlement", r),
  basis: (r: AnalysisRequest): Promise<BasisResponse> => post("/api/basis", r),
  scenarios: (r: AnalysisRequest): Promise<ScenariosResponse> =>
    post("/api/scenarios", r),
  storage: (r: AnalysisRequest): Promise<StorageResponse> =>
    post("/api/storage", r),
  availability: (contract: Contract): Promise<AvailabilityResponse> =>
    post("/api/availability", { contract }),
  validate: (contract: Contract): Promise<Contract> =>
    post("/api/contracts/validate", contract),
  geocode: (query: string): Promise<GeocodeResponse> =>
    fetch(`${BASE}/api/geocode?q=${encodeURIComponent(query)}`).then(unwrap),
};
