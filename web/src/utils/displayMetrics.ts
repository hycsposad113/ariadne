/** Display precision only; persisted measurements remain unchanged. */
export const formatFar = (value: number): string => value.toFixed(2);
export const formatPercentage = (value: number): string => `${(value * 100).toFixed(1)}%`;
