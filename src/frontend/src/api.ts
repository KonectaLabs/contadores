export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const RETRYABLE_STATUSES = new Set([429, 502, 503, 504]);
const RETRY_DELAYS_MS = [350, 900];
const MAX_RETRY_AFTER_MS = 5_000;
const REQUEST_TIMEOUT_MS = 30_000;

type ApiFetchOptions = RequestInit & {
  timeoutMs?: number;
};

type TimedRequest = {
  options: RequestInit;
  cleanup: () => void;
  didTimeout: () => boolean;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function parseRetryAfterMs(value: string | null): number | null {
  if (!value) {
    return null;
  }

  const seconds = Number(value);
  if (Number.isFinite(seconds)) {
    return Math.max(0, seconds * 1000);
  }

  const retryAt = new Date(value).getTime();
  if (Number.isNaN(retryAt)) {
    return null;
  }
  return Math.max(0, retryAt - Date.now());
}

function retryDelayMs(response: Response, attempt: number): number {
  const retryAfterMs = parseRetryAfterMs(response.headers.get("Retry-After"));
  if (retryAfterMs !== null) {
    return Math.min(retryAfterMs, MAX_RETRY_AFTER_MS);
  }
  return RETRY_DELAYS_MS[attempt];
}

function buildRequestOptions(options: ApiFetchOptions): RequestInit {
  const { timeoutMs: _timeoutMs, ...requestOptions } = options;
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return {
    ...requestOptions,
    headers,
    credentials: "same-origin",
  };
}

function buildTimedRequestOptions(options: ApiFetchOptions): TimedRequest {
  const controller = new AbortController();
  const baseOptions = buildRequestOptions(options);
  let timedOut = false;

  const abortFromCaller = () => controller.abort();
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", abortFromCaller, { once: true });
    }
  }

  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? REQUEST_TIMEOUT_MS);

  return {
    options: {
      ...baseOptions,
      signal: controller.signal,
    },
    cleanup: () => {
      window.clearTimeout(timeoutId);
      options.signal?.removeEventListener("abort", abortFromCaller);
    },
    didTimeout: () => timedOut,
  };
}

async function fetchWithRetry(path: string, options: ApiFetchOptions): Promise<Response> {
  let lastNetworkError: unknown = null;

  for (let attempt = 0; attempt <= RETRY_DELAYS_MS.length; attempt += 1) {
    let delayMs = RETRY_DELAYS_MS[attempt];
    const request = buildTimedRequestOptions(options);
    try {
      const response = await fetch(path, request.options);
      if (!RETRYABLE_STATUSES.has(response.status) || attempt === RETRY_DELAYS_MS.length) {
        return response;
      }
      delayMs = retryDelayMs(response, attempt);
    } catch (error) {
      if (request.didTimeout()) {
        throw new ApiError("Request timed out. Please refresh in a few seconds.", 0);
      }
      lastNetworkError = error;
      if (attempt === RETRY_DELAYS_MS.length) {
        throw new ApiError("Connection interrupted. Please refresh in a few seconds.", 0);
      }
    } finally {
      request.cleanup();
    }

    await sleep(delayMs);
  }

  throw lastNetworkError instanceof Error
    ? lastNetworkError
    : new ApiError("Connection interrupted. Please refresh in a few seconds.", 0);
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text.trim()) {
    return undefined as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError("Server returned an unreadable response. Please refresh and try again.", response.status);
  }
}

export async function apiFetch<T>(path: string, options: ApiFetchOptions = {}): Promise<T> {
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

  return readJsonResponse<T>(response);
}
