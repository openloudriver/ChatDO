const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"
];

export function formatPublishedDate(isoDate?: string | null): string | null {
  if (!isoDate) return null;

  // Parse ISO string manually to avoid timezone issues
  const parts = isoDate.split("-");
  if (parts.length !== 3) return null;

  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);

  if (!year || !month || !day) return null;

  const monthName = MONTH_NAMES[month - 1];

  return `${day} ${monthName} ${year}`;  // e.g. "11 January 2025"
}

