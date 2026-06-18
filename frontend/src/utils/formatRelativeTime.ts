export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  const diffSec = Math.round((Date.now() - date.getTime()) / 1000);
  if (diffSec < 60) {
    return 'just now';
  }
  if (diffSec < 3600) {
    return `${Math.floor(diffSec / 60)} min ago`;
  }
  if (diffSec < 86400) {
    return `${Math.floor(diffSec / 3600)} h ago`;
  }
  return `${Math.floor(diffSec / 86400)} d ago`;
}
