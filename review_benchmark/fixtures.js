// Synthetic, non-executed reviewer benchmark fixtures. NEVER MERGE.

// Defect cases ---------------------------------------------------------------

export function scannerReportIsUsable(report) {
  return report !== null && typeof report === "object" && Array.isArray(report.results);
}

export function invocationUnderTest(captured) {
  return captured.at(-1);
}

export function displayPosture(posture) {
  return posture.preset ?? "strict";
}

// Benign controls ------------------------------------------------------------

export function decodeFixedObject(payload) {
  const value = JSON.parse(payload);
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new TypeError("object required");
  }
  return value;
}

export function buildFixedRequest(baseUrl) {
  const url = new URL("/health", baseUrl);
  return { method: "GET", url: url.toString(), headers: { Accept: "application/json" } };
}
