import type { components } from "./schema";

export type { components } from "./schema";

const refreshKey = "tk-checker.refresh";
let accessToken: string | undefined;
let refreshing: Promise<boolean> | undefined;

type TokenPair = components["schemas"]["TokenPair"];

function storeTokens(tokens: TokenPair) {
  accessToken = tokens.access_token;
  localStorage.setItem(refreshKey, tokens.refresh_token);
}

async function refreshSession() {
  const token = localStorage.getItem(refreshKey);
  if (!token) return false;
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  });
  if (localStorage.getItem(refreshKey) !== token) return false;
  if (!response.ok) {
    if (response.status === 401) {
      accessToken = undefined;
      localStorage.removeItem(refreshKey);
    }
    return false;
  }
  const tokens = await response.json();
  if (localStorage.getItem(refreshKey) !== token) return false;
  storeTokens(tokens);
  return true;
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public details?: unknown) {
    super(message);
  }
}

async function request(path: string, options: RequestInit = {}, retry = true) {
  const previousToken = accessToken;
  const headers = new Headers(options.headers);
  if (previousToken) headers.set("Authorization", `Bearer ${previousToken}`);
  const response = await fetch(`/api/v1${path}`, { ...options, headers }).catch(error => {
    if (options.signal?.aborted) throw error;
    throw new ApiError(0, "Не удалось связаться с сервисом.", "network_error");
  });
  if (response.status === 401 && retry) {
    if (accessToken && accessToken !== previousToken) return request(path, options, false);
    refreshing ??= refreshSession().finally(() => { refreshing = undefined; });
    if (await refreshing) return request(path, options, false);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const problem = body?.error;
    throw new ApiError(response.status, problem?.message || `Ошибка запроса (${response.status})`,
      problem?.code, problem?.details);
  }
  return response;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  return (await request(path, options)).json();
}

export async function send(path: string, options?: RequestInit) {
  await request(path, options);
}

export function json(body: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function login(email: string, password: string) {
  const response = await request("/auth/token", json({ email, password }), false);
  storeTokens(await response.json());
}

export async function logout() {
  const token = localStorage.getItem(refreshKey);
  if (token) await request("/auth/logout", json({ refresh_token: token }), false);
  accessToken = undefined;
  localStorage.removeItem(refreshKey);
}

export async function downloadReport(id: string, format: "pdf" | "docx") {
  const response = await request(`/analyses/${id}/report?format=${format}`);
  const filename = response.headers.get("Content-Disposition")?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename ? decodeURIComponent(filename) : `report.${format}`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
