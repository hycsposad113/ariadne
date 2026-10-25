import type { SyntaxContextMode } from './syntaxContext';

/** Shipped surrounding-syntax manifest. Display labels cite this hash and are not formal results. */
export const SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256 =
  'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1';

export const SYNTAX_CONTEXT_READINESS: Record<
  SyntaxContextMode,
  { radius_m: number; status: string; reason: string }
> = {
  pedestrian: {
    radius_m: 800,
    status: 'BLOCKED_BOUNDARY_STABILITY_UNASSESSED',
    reason:
      'Boundary stability has not been demonstrated for the 800 m radius. Manifest a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1 stays BLOCKED_BOUNDARY_STABILITY_UNASSESSED and is not PASS.',
  },
  bicycle: {
    radius_m: 2000,
    status: 'EXPLORATORY',
    reason:
      'The 2000 m layer on manifest a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1 is EXPLORATORY display. It is not a formal result. Network policy and method thresholds remain a Founder decision.',
  },
  motor_vehicle: {
    radius_m: 10000,
    status: 'EXPLORATORY',
    reason:
      'The 10000 m layer on manifest a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1 is EXPLORATORY display. It is not a formal result. Network policy and method thresholds remain a Founder decision.',
  },
};
