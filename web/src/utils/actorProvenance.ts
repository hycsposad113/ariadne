export type ActorKind = 'HUMAN_UI' | 'QGIS_PLUGIN' | 'AGENT_AUTOMATION' | 'TEST_HARNESS';

const ACTOR_SESSION_STORAGE_KEY = 'urban-design-actor-session-id';

export function actorKindFromEnvironment(value: string | undefined): ActorKind {
  if (value === 'AGENT_AUTOMATION' || value === 'TEST_HARNESS') return value;
  return 'HUMAN_UI';
}

export function getActorSessionId(): string {
  const existing = window.sessionStorage.getItem(ACTOR_SESSION_STORAGE_KEY);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.sessionStorage.setItem(ACTOR_SESSION_STORAGE_KEY, created);
  return created;
}
