/** Fixed vocabularies from the research contract (contract/schema.py::TOPOLOGY_TYPES). */
export const TOPOLOGY_TYPES = [
  "FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER", "CYCLE", "RANDOM", "BIPARTITE", "STACK",
];

export const RING_STATUSES = ["open", "confirmed", "rejected", "partial"];

/** A date picked in the UI as the API's UTC day bounds (start of day, end of day), as text. */
export function dayStartUtc(day: string): string {
  return `${day}T00:00:00+00:00`;
}

export function dayEndUtc(day: string): string {
  return `${day}T23:59:59.999999+00:00`;
}

/** The YYYY-MM-DD part of a stored bound, to seed a date input. */
export function dayOf(bound: string | null): string {
  return bound ? bound.slice(0, 10) : "";
}
