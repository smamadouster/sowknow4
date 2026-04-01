/**
 * Shared date formatting utility.
 *
 * @param dateStr  ISO date string
 * @param options  Intl.DateTimeFormat options (defaults include time)
 * @param locale   BCP-47 locale tag (defaults to browser locale)
 */
export function formatDate(
  dateStr: string,
  options?: Intl.DateTimeFormatOptions,
  locale?: string,
): string {
  const defaults: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  };
  return new Date(dateStr).toLocaleDateString(locale, options ?? defaults);
}

/** Date-only variant (no time component). */
export function formatDateShort(
  dateStr: string,
  locale?: string,
): string {
  return formatDate(dateStr, { year: 'numeric', month: 'short', day: 'numeric' }, locale);
}
