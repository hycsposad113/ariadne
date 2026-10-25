import { describe, expect, it } from 'vitest';
import { normalizeFeatureDisposition, resolveFeatureDisposition } from './disposition';

describe('normalizeFeatureDisposition', () => {
  it('maps persisted lowercase dispositions into the UI enum', () => {
    expect(normalizeFeatureDisposition('preserve')).toBe('PRESERVE');
    expect(normalizeFeatureDisposition('editable')).toBe('EDITABLE');
    expect(normalizeFeatureDisposition('undecided')).toBe('UNDECIDED');
  });

  it('accepts already-normalized UI values', () => {
    expect(normalizeFeatureDisposition('EDITABLE')).toBe('EDITABLE');
  });

  it('fails closed for missing or unsupported values', () => {
    expect(normalizeFeatureDisposition(null)).toBeUndefined();
    expect(normalizeFeatureDisposition('approved')).toBeUndefined();
  });

  it('normalizes source fallback values when no valid persisted overlay exists', () => {
    expect(resolveFeatureDisposition(undefined, 'editable')).toBe('EDITABLE');
    expect(resolveFeatureDisposition('unsupported', 'preserve')).toBe('PRESERVE');
    expect(resolveFeatureDisposition(null, 'unknown')).toBe('UNDECIDED');
  });
});
