export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });

  if (response.status === 401) {
    window.location.href = "/login";
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
