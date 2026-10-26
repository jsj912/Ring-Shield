/** Bounded polling (platform/dashboard/regeneration_flow.py): give up after 120 s of clock time. */
export const POLL_SECONDS = 120;

export function newPollDeadline(now: number = Date.now()): number {
  return now + POLL_SECONDS * 1000;
}

export function deadlineExpired(deadline: number | null | undefined, now: number = Date.now()): boolean {
  return deadline === null || deadline === undefined || now >= deadline;
}
