export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const RETRYABLE_STATUSES = new Set([502, 503, 504]);
const RETRY_DELAYS_MS = [350, 900];

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildRequestOptions(options: RequestInit): RequestInit {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return {
    ...options,
    headers,
    credentials: "same-origin",
  };
}

async function fetchWithRetry(path: string, options: RequestInit): Promise<Response> {
  let lastNetworkError: unknown = null;

  for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
    try {
      const response = await fetch(path, buildRequestOptions(options));
      if (!RETRYABLE_STATUSES.has(response.status) || attempt === RETRY_DELAYS_MS.length) {
        return response;
      }
    } catch (error) {
      lastNetworkError = error;
      if (attempt === RETRY_DELAYS_MS.length) {
        throw new ApiError("Connection interrupted. Please refresh in a few seconds.", 0);
      }
    }

    await sleep(RETRY_DELAYS_MS[attempt]);
  }

  throw lastNetworkError instanceof Error
    ? lastNetworkError
    : new ApiError("Connection interrupted. Please refresh in a few seconds.", 0);
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetchWithRetry(path, options);

  if (response.status === 401) {
    window.location.replace("/login");
    throw new ApiError("Authentication required.", response.status);
  }

  if (!response.ok) {
    let message = `Request failed with ${response.status}.`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        message = Array.isArray(payload.detail) ? payload.detail.map(String).join(", ") : String(payload.detail);
      }
    } catch {
      message = response.statusText || message;
    }
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}
