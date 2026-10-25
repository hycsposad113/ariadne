// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { Week7Actions } from './Week7Actions';
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('uses real metadata and sends only the strict entity reference, without fixture values', async () => {
  const fetched = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url=String(input);
    if (url.endsWith('/scenarios')) return new Response(JSON.stringify([{entity_id:'real-scenario',revision:3,label:'Real design',status:'draft'}]));
    if (url.endsWith('/view')) return new Response(JSON.stringify({ workspace_ref:{entity_id:'ws',revision:8,payload_sha256:'sha256:x'},scenario_ref:{entity_id:'real-scenario',revision:3,entity_type:'DesignScenario',payload_sha256:'sha256:y'},cards:[],runs:[] }));
    if (init?.method==='POST') return new Response(JSON.stringify({entity_id:'real-scenario',revision:3}));
    throw Error('Unexpected route');
  });
  render(<I18nProvider><Week7Actions apiBase="http://localhost" workspaceId="ws" /></I18nProvider>);
  await waitFor(() => expect(screen.getByTestId('week7-op-inspect')).toBeEnabled());
  fireEvent.click(screen.getByTestId('week7-op-inspect'));
  await waitFor(() => expect(fetched.mock.calls.some(c => String(c[0]).endsWith('/operations/inspect'))).toBe(true));
  const request=fetched.mock.calls.find(c => String(c[0]).endsWith('/operations/inspect'))?.[1];
  const body=JSON.parse(String(request?.body));
  expect(body.target).toEqual({entity_id:'real-scenario',revision:3});
  expect(JSON.stringify(body)).not.toMatch(/rev-b2|card-b2|already_approved|proposed_value/);
  expect(screen.getByTestId('week7-op-reject')).toBeDisabled();
});

it.each(['disconnect', 'job-outcome-unknown', 'publication-refusal'])('locks mutations after %s and performs no automatic resend', async (outcome) => {
  let writes=0;
  vi.spyOn(globalThis,'fetch').mockImplementation(async (input,init) => {
    if (init?.method==='POST') {
      writes++;
      if (outcome === 'disconnect') throw Error('disconnected');
      return new Response(JSON.stringify(outcome === 'job-outcome-unknown' ? {status:'OUTCOME_UNKNOWN'} : {detail:{code:'OUTCOME_UNKNOWN'}}), {status:outcome === 'publication-refusal' ? 409 : 200});
    }
    if (String(input).endsWith('/scenarios')) return new Response(JSON.stringify([{entity_id:'s',revision:1,label:'s',status:'proposed'}]));
    return new Response(JSON.stringify({workspace_ref:{entity_id:'ws',revision:8},scenario_ref:{entity_id:'s',revision:1},cards:[],runs:[]}));
  });
  render(<I18nProvider><Week7Actions apiBase="http://localhost" workspaceId="ws" /></I18nProvider>);
  await waitFor(() => expect(screen.getByTestId('week7-op-inspect')).toBeEnabled());
  fireEvent.click(screen.getByTestId('week7-op-inspect'));
  await screen.findByRole('alert');
  expect(screen.getByTestId('week7-op-inspect')).toBeDisabled();
  expect(writes).toBe(1);
});

it.each(['en', 'zh-TW'] as const)('keeps Override pending and follows %s through formal human submission', async language => {
  const geometryHash = `sha256:${'a'.repeat(64)}`;
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      posts.push({ url, body });
      if (url.endsWith('/operations/override')) {
        return new Response(JSON.stringify({ status: 'PENDING_FOUNDER_DECISION', event: { event_id: 'event-w7-pending' } }));
      }
      return new Response(JSON.stringify({ id: 'human-decision-fixture' }), { status: 201 });
    }
    if (url.endsWith('/scenarios')) return new Response(JSON.stringify([
      { entity_id: 'scenario-proposed', revision: 4, label: '測試提案', status: 'proposed', geometry_sha256: geometryHash },
    ]));
    return new Response(JSON.stringify({ project_id: 'project-fixture',
      workspace_ref: { entity_id: 'workspace-fixture', revision: 2 },
      scenario_ref: { entity_id: 'scenario-proposed', revision: 4 }, cards: [], runs: [] }));
  });
  render(<I18nProvider language={language}><Week7Actions apiBase="http://localhost" workspaceId="workspace-fixture" /></I18nProvider>);
  await waitFor(() => expect(screen.getByTestId('week7-op-inspect')).toBeEnabled());
  fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: '請交由人類審議此覆寫提案。' } });
  fireEvent.click(screen.getByTestId('week7-op-override'));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('dialog')).toHaveTextContent('event-w7-pending');
  if (language === 'en') expect(screen.getByRole('dialog').textContent).not.toMatch(/[\u3400-\u9fff]/);
  expect(posts).toHaveLength(1);
  expect(posts[0].url).toMatch(/\/operations\/override$/);
  expect(posts[0].body).toMatchObject({ target: { entity_id: 'scenario-proposed', revision: 4 } });
  expect(screen.getByTestId('d1-dialog-submit-btn')).toBeEnabled();

  fireEvent.change(screen.getByLabelText(language === 'en' ? 'Reason' : '理由'), { target: { value: '人類確認此測試覆寫決定。' } });
  fireEvent.change(screen.getByLabelText(language === 'en' ? 'Decision key' : '決策金鑰'), { target: { value: 'fixture-human-key-only' } });
  fireEvent.click(screen.getByTestId('d1-dialog-submit-btn'));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1].url).toBe('http://localhost/api/v1/projects/project-fixture/decisions');
  expect(posts[1].body).toMatchObject({
    target_id: 'scenario-proposed', target_type: 'DesignScenario', target_version: '4',
    target_geometry_sha256: geometryHash, action: 'Override', status: 'overridden',
    decision_key: 'fixture-human-key-only',
  });
  expect(posts.filter(post => post.url.endsWith('/operations/override'))).toHaveLength(1);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByTestId('week7-op-result')).not.toHaveTextContent('fixture-human-key-only');
});
