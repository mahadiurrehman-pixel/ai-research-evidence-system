import type { Investigation } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function startInvestigation(
  question: string,
  maxRounds: number = 3
): Promise<{ investigation_id: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, max_rounds: maxRounds }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function getInvestigation(
  id: string
): Promise<Investigation> {
  const res = await fetch(`${API_BASE}/api/research/${id}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

export async function getHistory(): Promise<Investigation[]> {
  const res = await fetch(`${API_BASE}/api/research/history`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `API error: ${res.status}`);
  }
  return res.json();
}

/**
 * Poll investigation until complete or timeout.
 * Calls onProgress callback with each status update.
 */
export async function pollInvestigation(
  investigationId: string,
  onProgress?: (status: string) => void,
  timeoutMs: number = 120000,
  pollIntervalMs: number = 2000
): Promise<Investigation> {
  const startTime = Date.now();

  while (Date.now() - startTime < timeoutMs) {
    const result = await getInvestigation(investigationId);
    onProgress?.(result.status);

    if (
      result.status === "COMPLETED" ||
      result.status === "FAILED" ||
      result.status === "INCONCLUSIVE"
    ) {
      return result;
    }

    await new Promise((r) => setTimeout(r, pollIntervalMs));
  }

  throw new Error("Investigation timed out");
}