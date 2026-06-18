export function parseApiError(text: string, status: number): string {
  if (!text) {
    return `Request failed with ${status}`;
  }
  try {
    const payload = JSON.parse(text) as { detail?: string | { msg?: string }[] };
    if (typeof payload.detail === 'string') {
      return payload.detail;
    }
    if (Array.isArray(payload.detail) && payload.detail.length > 0) {
      const first = payload.detail[0];
      if (typeof first === 'object' && first && 'msg' in first) {
        return String(first.msg);
      }
    }
  } catch {
    // keep raw text
  }
  return text;
}
