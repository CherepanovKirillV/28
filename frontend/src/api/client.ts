import { API_ENDPOINTS } from "./endpoints";
import type { RunRequest, RunResponse, ServiceStatus } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API request failed with status ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });

  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, body);
  }

  return body as T;
}

export const getRoot = (): Promise<ServiceStatus> => request(API_ENDPOINTS.root);

export const getHealth = (): Promise<ServiceStatus> => request(API_ENDPOINTS.health);

export const runCase = (payload: RunRequest, authorization?: string): Promise<RunResponse> =>
  request(API_ENDPOINTS.run, {
    method: "POST",
    headers: {
      ...(authorization ? { Authorization: authorization } : {}),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

