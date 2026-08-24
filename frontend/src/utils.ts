export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString();
}

export function money(n: number): string {
  if (n >= 100) return "$" + n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (n >= 1) return "$" + n.toFixed(2);
  return "$" + n.toFixed(n < 0.01 ? 4 : 3);
}

export function relevanceBadgeClass(relevance: string): string {
  return `badge badge-${relevance || "low"}`;
}

/** Report titles are generated as "Desk • Report Type • Date Range" so the UI
 * can show them as separate table columns. Falls back for older titles that
 * used " — " as the separator, or shows the whole string if neither matches. */
export function splitReportTitle(title: string): [string, string, string] {
  const byBullet = title.split(" • ");
  if (byBullet.length === 3) return [byBullet[0], byBullet[1], byBullet[2]];
  const byDash = title.split(" — ");
  if (byDash.length === 3) return [byDash[0], byDash[1], byDash[2]];
  return [title, "", ""];
}
