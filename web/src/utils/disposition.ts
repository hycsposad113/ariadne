import type { FeatureDispositionType } from '../types';

const FEATURE_DISPOSITIONS: readonly FeatureDispositionType[] = [
  'PRESERVE',
  'EDITABLE',
  'UNDECIDED',
];

export function normalizeFeatureDisposition(value: unknown): FeatureDispositionType | undefined {
  if (typeof value !== 'string') return undefined;
  const normalized = value.toUpperCase();
  return FEATURE_DISPOSITIONS.includes(normalized as FeatureDispositionType)
    ? normalized as FeatureDispositionType
    : undefined;
}

export function resolveFeatureDisposition(
  persistedValue: unknown,
  sourceValue: unknown,
): FeatureDispositionType {
  return normalizeFeatureDisposition(persistedValue)
    ?? normalizeFeatureDisposition(sourceValue)
    ?? 'UNDECIDED';
}
