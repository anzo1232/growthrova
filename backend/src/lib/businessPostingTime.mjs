/** Resolve wall-clock choices only. The server independently validates the saved offset. */
export function postingTimeChoices(localTime, timezone) {
  const empty = error => ({choices: [], error});
  if (!localTime) return empty(null);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(localTime)) return empty('invalid_time');
  const wall = Date.parse(localTime + ':00Z');
  if (!Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 16) !== localTime)
    return empty('invalid_time');
  let formatter;
  try {
    formatter = new Intl.DateTimeFormat('en-GB', {timeZone: timezone, calendar: 'gregory',
      numberingSystem: 'latn', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
  } catch { return empty('invalid_zone'); }
  const at = instant => Object.fromEntries(formatter.formatToParts(instant)
    .filter(part => part.type !== 'literal').map(part => [part.type, Number(part.value)]));
  const offsets = new Set();
  // Sample both sides of a transition, including half-hour changes and date-line skips.
  for (let hours = -48; hours <= 48; hours += 6) {
    const instant = wall + hours * 3600000;
    const p = at(instant);
    offsets.add((Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - instant) / 60000);
  }
  const choices = [...offsets].filter(offset => Number.isInteger(offset) && Math.abs(offset) <= 840)
    .map(utcOffsetMinutes => ({utcOffsetMinutes, utcTime: new Date(wall - utcOffsetMinutes * 60000).toISOString()}))
    .filter(choice => {
      const p = at(Date.parse(choice.utcTime));
      return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) === wall;
    }).sort((a, b) => a.utcTime.localeCompare(b.utcTime));
  return {choices, error: choices.length ? null : 'nonexistent'};
}
