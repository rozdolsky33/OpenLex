import { request } from "./client";
import type { HealthResponse } from "./types";

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/healthz", { auth: false });
}
