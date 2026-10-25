/**
 * Deduplicate concurrent readiness requests across GenerationWorkflowPanel
 * and GenerationReadinessPanel. Keeps at most one in-flight request per URL
 * and caches results briefly to prevent duplicate execution.
 */

export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'HttpError';
    this.status = status;
  }
}

const inFlightRequests = new Map<string, Promise<any>>();
const recentResponses = new Map<string, { time: number; data: any }>();

export function clearReadinessCache(): void {
  inFlightRequests.clear();
  recentResponses.clear();
}

export async function fetchDedupedReadiness<T>(url: string, options: RequestInit = { method: 'GET' }, ttlMs: number = 3000): Promise<T> {
  const method = (options.method ?? 'GET').toUpperCase();
  if (method !== 'GET') {
    const res = await fetch(url, options);
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new HttpError(res.status, text || String(res.status));
    }
    return res.json() as Promise<T>;
  }

  const cached = recentResponses.get(url);
  if (cached && Date.now() - cached.time < ttlMs) {
    return cached.data as T;
  }

  let inFlight = inFlightRequests.get(url);
  if (inFlight) {
    return inFlight as Promise<T>;
  }

  const promise = (async () => {
    try {
      const res = await fetch(url, options);
      if (!res.ok) {
        const text = await res.text().catch(() => '');
        throw new HttpError(res.status, text || String(res.status));
      }
      const data = await res.json();
      recentResponses.set(url, { time: Date.now(), data });
      return data as T;
    } finally {
      inFlightRequests.delete(url);
    }
  })();

  inFlightRequests.set(url, promise);
  return promise;
}
