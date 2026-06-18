import { describe, expect, it } from 'vitest';
import { parseApiError } from '../utils/apiError';

describe('parseApiError', () => {
  it('parses JSON detail payloads', () => {
    const message = parseApiError('{"detail":"Bad request"}', 400);
    expect(message).toContain('Bad request');
  });

  it('falls back to status text', () => {
    const message = parseApiError('', 500);
    expect(message).toContain('500');
  });
});
