export function languageOf(menuCode, browserLanguage) {
  const code = String(menuCode || browserLanguage || 'en').toLowerCase();
  return /^(rum|ron|ro)/.test(code) ? 'ro' : 'en';
}

export function formatClock(date, language, timeZone) {
  const locale = language === 'ro' ? 'ro-RO' : 'en-GB';
  const time = new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hour12: false, timeZone }).format(
    date,
  );
  const day = new Intl.DateTimeFormat(locale, { weekday: 'long', day: 'numeric', month: 'long', timeZone }).format(
    date,
  );
  return { time, date: day };
}
