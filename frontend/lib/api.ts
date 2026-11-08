import type { Dashboard, Investigation, TrendPoint } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, cache: "no-store" });
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* Proxy may return a non-JSON response when the backend is offline. */
    }
    throw new Error(detail);
  }
  return response.json();
}

function query(dataset: string, at?: number | null) {
  const params = new URLSearchParams({ dataset });
  if (at != null) params.set("at", String(at));
  return params;
}
export const api = {
  datasets: (signal?: AbortSignal) =>
    request<string[]>("/api/datasets", { signal }),
  dashboard: (dataset: string, at?: number | null, signal?: AbortSignal) =>
    request<Dashboard>(`/api/dashboard?${query(dataset, at)}`, { signal }),
  trend: (
    dataset: string,
    asset: string,
    metric: string,
    at: number,
    signal?: AbortSignal,
  ) => {
    const params = query(dataset, at);
    params.set("asset", asset);
    params.set("metric", metric);
    return request<TrendPoint[]>(`/api/trend?${params}`, { signal });
  },
  investigate: (
    dataset: string,
    facility_id: string,
    at: number,
    signal?: AbortSignal,
  ) =>
    request<Investigation>("/api/investigate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal,
      body: JSON.stringify({ dataset, facility_id, at }),
    }),
  eventsUrl: (dataset: string, at: number) =>
    `/api/events?${query(dataset, at)}`,
};
