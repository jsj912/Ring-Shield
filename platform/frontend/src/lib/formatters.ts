/**
 * Display formatting for API values (FR-D101), ported from platform/dashboard/formatters.py.
 * Formatting only: no sums, ratios or re-ranking (FR-D102). Rounding is half-even, as Python's
 * format() rounds, so a value prints the same here as in the Streamlit dashboard.
 *
 * Amounts: thousands separators and two decimals, the currency exactly as the API names it and
 * the partial flag shown, never converted. Percentages: one decimal. Weights: two decimals.
 * Times: the viewer's local zone, with the UTC instant kept for hover.
 */

export const MISSING = "—";

type Num = number | null | undefined;

/**
 * Python's f"{value:,.{digits}f}" (and "%" with shift 2), done on text so no arithmetic touches the
 * value. Python rounds the float's exact binary value, half to even; Intl and toFixed do not quite
 * (Intl rounds the shortest decimal text, so 0.2395 -> 0.240 where Python prints 0.239). toFixed
 * with 25 spare digits gives the binary value's own expansion, which is then rounded here.
 */
export function pyFixed(value: number, digits: number, grouping: boolean, shift = 0): string {
  if (!Number.isFinite(value)) return String(value);
  const expansion = Math.abs(value).toFixed(Math.min(100, digits + shift + 25));
  const [whole, fraction = ""] = expansion.split(".");
  const integer = (whole + fraction.slice(0, shift)).replace(/^0+(?=\d)/, "");    // move the point (percent)
  const decimals = fraction.slice(shift);
  let kept = integer + decimals.slice(0, digits);
  const rest = decimals.slice(digits);
  const up = rest[0] > "5" || (rest[0] === "5" && (/[1-9]/.test(rest.slice(1)) || Number(kept.at(-1)) % 2 === 1));
  if (up) kept = (BigInt(kept) + 1n).toString().padStart(kept.length, "0");
  let head = kept.slice(0, kept.length - digits) || "0";
  if (grouping) head = head.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const sign = value < 0 || Object.is(value, -0) ? "-" : "";
  return digits ? `${sign}${head}.${kept.slice(kept.length - digits)}` : `${sign}${head}`;
}

function format(value: number, digits: number, grouping: boolean, style: "decimal" | "percent" = "decimal"): string {
  // Python's "%" multiplies the float by 100 (rounding to a double) before formatting; doing the same
  // here is formatting, as it is there, and keeps the last digit identical.
  return style === "percent" ? `${pyFixed(value * 100, digits, grouping)}%` : pyFixed(value, digits, grouping);
}

export function fmtAmount(value: Num, currency?: string | null, partial?: boolean | null): string {
  if (value === null || value === undefined) return MISSING;
  let text = format(Number(value), 2, true);
  if (currency) text = `${text} ${currency}`;
  if (partial) text = `${text} (partial)`;
  return text;
}

/** A fraction in [0, 1] shown as a percentage with one decimal (formatting, not arithmetic). */
export function fmtPercent(fraction: Num): string {
  return fraction === null || fraction === undefined ? MISSING : format(Number(fraction), 1, false, "percent");
}

export function fmtWeight(value: Num): string {
  return value === null || value === undefined ? MISSING : format(Number(value), 2, false);
}

/** A recall in [0, 1] with three decimals, as the R10 tables report it. */
export function fmtRecall(value: Num): string {
  return value === null || value === undefined ? MISSING : format(Number(value), 3, false);
}

/** A value with its 95 % interval, e.g. "0.088 [0.031, 0.161]". */
export function fmtInterval(value: Num, low: Num, high: Num): string {
  return `${fmtRecall(value)} [${fmtRecall(low)}, ${fmtRecall(high)}]`;
}

/** A number shown exactly as the API sent it (change 3: topology_prob). */
export function fmtAsReceived(value: Num | string): string {
  return value === null || value === undefined ? MISSING : String(value);
}

/** Conservation closure: "closed loop" for a ring with no source or sink, never a percentage. */
export function fmtClosure(value: Num, closedLoop?: boolean | null): string {
  if (closedLoop || value === null || value === undefined) {
    return closedLoop || value === null || value === undefined ? "closed loop" : MISSING;
  }
  return fmtPercent(value);
}

/** ISO-8601 -> Date; a value with no offset is UTC (as formatters._parse treats naive values). */
function parse(value: string | null | undefined): Date | null | "invalid" {
  if (value === null || value === undefined) return null;
  const text = String(value);
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(text);
  const moment = new Date(hasZone ? text : `${text}Z`);
  return Number.isNaN(moment.getTime()) ? "invalid" : moment;
}

function parts(moment: Date, timeZone: string, withSeconds: boolean, zoneName: boolean) {
  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined, hourCycle: "h23",
  });
  const out: Record<string, string> = {};
  for (const part of formatter.formatToParts(moment)) out[part.type] = part.value;
  if (zoneName) {
    // The browser's own locale names the zone ("IST", "CET"), as Python's tzname() would.
    const zone = new Intl.DateTimeFormat(undefined, { timeZone, timeZoneName: "short" }).formatToParts(moment);
    out.timeZoneName = zone.find((part) => part.type === "timeZoneName")?.value ?? "";
  }
  return out;
}

function validZone(zone: string | undefined): string {
  if (!zone) return "UTC";
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return zone;
  } catch {
    return "UTC";
  }
}

/** The viewer's zone, as the browser reports it. */
export function viewerZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/**
 * The instant in the viewer's zone, "YYYY-MM-DD HH:MM ZONE" (falls back to UTC when the zone is
 * unknown); a value that is not an ISO-8601 instant is shown as received.
 */
export function fmtTime(value: string | null | undefined, tzName?: string): string {
  const moment = parse(value);
  if (moment === "invalid") return String(value);
  if (moment === null) return MISSING;
  const p = parts(moment, validZone(tzName ?? viewerZone()), false, true);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute} ${p.timeZoneName || "UTC"}`;
}

/** The same instant in UTC, for hover text. */
export function fmtTimeUtc(value: string | null | undefined): string {
  const moment = parse(value);
  if (moment === "invalid") return String(value);
  if (moment === null) return MISSING;
  const p = parts(moment, "UTC", true, false);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second} UTC`;
}

/** A duration in seconds with separators; missing or NaN (no hold time) shows as a dash. */
export function fmtSeconds(value: Num): string {
  if (value === null || value === undefined || Number.isNaN(value)) return MISSING;
  return `${format(Number(value), 0, true)} s`;
}

export function fmtBool(value: boolean | null | undefined): string {
  return value === null || value === undefined ? MISSING : value ? "Yes" : "No";
}

/** Prefix spreadsheet formula markers in text cells; preserve other values (app.py::_csv_safe_text). */
export function csvSafeText<T>(value: T): T | string {
  if (typeof value === "string" && value && "=+-@\t\r".includes(value[0])) return `'${value}`;
  return value;
}

/** FR-D54: a simulated verdict carries a 'Simulated' tag wherever it is shown. */
export function verdictLabel(item: { verdict: string; is_simulated: boolean }): string {
  return item.is_simulated ? `${item.verdict} · Simulated` : item.verdict;
}
