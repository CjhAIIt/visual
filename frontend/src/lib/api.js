const FALLBACK_API_BASE = "/api";

export function getApiBaseUrl() {
  return (import.meta.env.VITE_API_BASE_URL || FALLBACK_API_BASE).replace(/\/$/, "");
}

function joinUrl(baseUrl, path) {
  const normalizedPath = String(path || "").startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

function parsePayload(text) {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

export async function requestApi(path, { method = "GET", token = "", body, headers = {}, signal } = {}) {
  const finalHeaders = new Headers(headers);
  if (token) {
    finalHeaders.set("X-Auth-Token", token);
  }
  let payloadBody = body;
  if (body && !(body instanceof FormData) && typeof body !== "string" && !(body instanceof Blob)) {
    finalHeaders.set("Content-Type", "application/json");
    payloadBody = JSON.stringify(body);
  }

  const response = await fetch(joinUrl(getApiBaseUrl(), path), {
    method,
    headers: finalHeaders,
    body: payloadBody,
    signal,
  });

  const text = await response.text();
  const payload = parsePayload(text) || {};
  if (!response.ok) {
    const message = payload?.detail || payload?.message || response.statusText || "请求失败";
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return payload;
}

export async function requestBlob(path, { method = "GET", token = "", body, headers = {}, signal } = {}) {
  const finalHeaders = new Headers(headers);
  if (token) {
    finalHeaders.set("X-Auth-Token", token);
  }
  let payloadBody = body;
  if (body && !(body instanceof FormData) && typeof body !== "string" && !(body instanceof Blob)) {
    finalHeaders.set("Content-Type", "application/json");
    payloadBody = JSON.stringify(body);
  }

  const response = await fetch(joinUrl(getApiBaseUrl(), path), {
    method,
    headers: finalHeaders,
    body: payloadBody,
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    const payload = parsePayload(text) || {};
    const message = payload?.detail || payload?.message || response.statusText || "请求失败";
    const error = new Error(message);
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  return response.blob();
}

export function buildApiUrl(path) {
  return joinUrl(getApiBaseUrl(), path);
}

export function getApiBaseLabel() {
  return getApiBaseUrl();
}
