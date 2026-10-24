import { csvSafeText } from "./formatters";

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * CSV text with a header row, as Python's csv.DictWriter writes it (CRLF line ends). Fields in
 * `textFields` go through csvSafeText so a note cannot become a spreadsheet formula.
 */
export function toCsv<T extends Record<string, unknown>>(rows: T[], fields: (keyof T & string)[], textFields: Set<string> = new Set()): string {
  const lines = [fields.map(cell).join(",")];
  for (const row of rows) {
    lines.push(fields.map((field) => cell(textFields.has(field) ? csvSafeText(row[field]) : row[field])).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}

export function downloadText(text: string, fileName: string, type = "text/csv"): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}
