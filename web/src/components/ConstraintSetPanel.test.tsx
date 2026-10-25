// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ConstraintSetPanel } from './ConstraintSetPanel';
import { I18nProvider } from '../i18n';

const digest = `sha256:${'e'.repeat(64)}`;
const draft = {
  constraint_set: {
    id: 'constraint-set-fixture',
    project_id: 'project-fixture',
    version: 'v1',
    status: 'proposed',
    allocation_policy: null,
    notes: 'D2 draft notes',
    constraints: [{ id: 'constraint-far-site', name: 'far_upper_limit', value: 0.8,
      unit: 'ratio', scope: 'whole_site', enforcement: 'HARD', status: 'proposed',
      source_refs: [], source_note: 'FOUNDER_STATED', denominator: 'land_area' }],
  },
  revision: 1,
  payload_digest: digest,
};

describe('ConstraintSetPanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    localStorage.clear();
  });

  it('previews a draft and uses HumanDecisionDialog for hash-bound activation', async () => {
    let currentStatus = 'proposed';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method || 'GET';
      if (url.endsWith('/constraint-sets') && method === 'GET') {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      if (url.endsWith('/constraint-sets') && method === 'POST') {
        return new Response(JSON.stringify(draft), { status: 201 });
      }
      if (url.includes('/constraint-sets/constraint-set-fixture')) {
        return new Response(JSON.stringify({
          ...draft,
          constraint_set: { ...draft.constraint_set, status: currentStatus },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 });
    });

    const onSubmitDecision = vi.fn(async () => {
      currentStatus = 'effective';
    });

    render(
      <ConstraintSetPanel
        apiBase="http://127.0.0.1:8789"
        projectId="project-fixture"
        onSubmitDecision={onSubmitDecision}
      />,
    );

    fireEvent.change(screen.getByLabelText('Overall FAR cap'), { target: { value: '0.8' } });
    fireEvent.change(screen.getByLabelText('Coverage ratio cap'), { target: { value: '0.35' } });
    fireEvent.change(screen.getByLabelText('Maximum height (m)'), { target: { value: '18' } });
    fireEvent.change(screen.getByLabelText('First-floor height (m)'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText('Standard-floor height (m)'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Rotation step (degrees)'), { target: { value: '15' } });
    fireEvent.change(screen.getByLabelText('Road hierarchy'), { target: { value: 'hierarchy-a' } });
    fireEvent.change(screen.getByLabelText('Road width (m)'), { target: { value: '6' } });
    for (const label of [
      'Overall FAR cap type',
      'Coverage ratio cap type',
      'Maximum height type',
      'First-floor height type',
      'Standard-floor height type',
      'Rotation step type',
      'Road width 1 type',
    ]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value: 'HARD' } });
    }
    fireEvent.click(screen.getByRole('button', { name: 'Save draft' }));

    await screen.findByText('PROPOSED');
    expect(screen.getByText('Overall FAR cap')).toBeTruthy();
    const postCall = fetchMock.mock.calls.find(c => c[1]?.method === 'POST')!;
    expect(postCall[0]).toBe('http://127.0.0.1:8789/api/v1/projects/project-fixture/constraint-sets');
    const request = JSON.parse(String(postCall[1]?.body));
    expect(request.constraints).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'far_upper_limit', value: 0.8, unit: 'ratio', scope: 'whole_site', enforcement: 'HARD', denominator: 'land_area' }),
      expect.objectContaining({ name: 'road_width', value: 6, unit: 'm', scope: 'road:hierarchy-a' }),
    ]));

    fireEvent.click(screen.getByRole('button', { name: 'Confirm and activate' }));
    expect(screen.getByRole('dialog', { name: 'Confirm human decision' })).toBeTruthy();
    expect(screen.getByText(digest)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Approve this reviewed set.' } });
    fireEvent.change(screen.getByLabelText('Decision key'), { target: { value: 'fixture-' + 'f'.repeat(32) } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm decision' }));

    await waitFor(() => expect(onSubmitDecision).toHaveBeenCalledWith(expect.objectContaining({
      target_id: 'constraint-set-fixture',
      target_type: 'ConstraintSet',
      target_version: 'v1',
      target_payload_digest: digest,
    })));
    await screen.findByText('EFFECTIVE');
  });

  it('lists available constraint sets and loads on click, keeping manual input as fallback', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/constraint-sets')) {
        return new Response(JSON.stringify({
          items: [
            {
              id: 'cs-proposed-1',
              version: 'v1',
              status: 'proposed',
              notes: 'Draft note for cs-1',
              revision: 1,
              payload_digest: digest,
            },
            {
              id: 'cs-effective-2',
              version: 'v2',
              status: 'effective',
              notes: null,
              revision: 2,
              payload_digest: digest,
            },
          ],
        }), { status: 200 });
      }
      if (url.includes('/constraint-sets/cs-proposed-1')) {
        return new Response(JSON.stringify({
          ...draft,
          constraint_set: {
            ...draft.constraint_set,
            id: 'cs-proposed-1',
            notes: 'Draft note for cs-1',
          },
        }), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 });
    });

    render(
      <ConstraintSetPanel
        apiBase="http://127.0.0.1:8789"
        projectId="project-fixture"
        onSubmitDecision={vi.fn()}
      />,
    );

    // List renders both sets with id, version, and status
    expect(await screen.findByText('cs-proposed-1')).toBeTruthy();
    expect(screen.getByText('cs-effective-2')).toBeTruthy();
    expect(screen.getByText('Draft note for cs-1')).toBeTruthy();

    // Manual input is also present as fallback
    expect(screen.getByLabelText('ConstraintSet ID')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Load draft' })).toBeTruthy();

    // Clicking cs-proposed-1 loads it
    fireEvent.click(screen.getByTestId('constraint-set-card-cs-proposed-1'));
    await screen.findByText('PROPOSED');
    expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).value).toBe('Draft note for cs-1');
  });
});

describe('ConstraintSet draft review content', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

  it.each(['en', 'zh-TW'])('loads agent drafts and displays hash-bound notes and FAR denominator in %s', async language => {
    localStorage.setItem('urban-design-language', language);
    const zone = { ...draft.constraint_set.constraints[0], id: 'zone-far', name: 'zone_far_upper_limit', scope: 'zone:z', denominator: 'exploration_design_area', source_note: 'ASSUMED zone' };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
      const url = String(input);
      if (url.endsWith('/constraint-sets')) {
        return new Response(JSON.stringify({ items: [] }), { status: 200 });
      }
      return new Response(JSON.stringify({
        ...draft, constraint_set: { ...draft.constraint_set, constraints: [...draft.constraint_set.constraints, zone] },
      }), { status: 200 });
    });
    render(<I18nProvider><ConstraintSetPanel apiBase="http://testserver" projectId="p" onSubmitDecision={vi.fn()} /></I18nProvider>);
    fireEvent.change(screen.getByLabelText(language === 'en' ? 'ConstraintSet ID' : '條件集編號'), { target: { value: 'constraint-set-fixture' } });
    fireEvent.click(screen.getByRole('button', { name: language === 'en' ? 'Load draft' : '載入草稿' }));
    await screen.findByText('FOUNDER_STATED');
    const land = language === 'en' ? 'Denominator: land area' : '分母：陸地面積';
    const eda = language === 'en' ? 'Denominator: exploration design area' : '分母：探索設計範圍面積';
    expect(screen.getByText(land)).toBeTruthy();
    expect(screen.getByText(eda)).toBeTruthy();
    expect((screen.getByLabelText(language === 'en' ? 'Notes' : '備註') as HTMLTextAreaElement).value).toBe('D2 draft notes');
    fireEvent.click(screen.getByRole('button', { name: language === 'en' ? 'Confirm and activate' : '確認並啟用' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog.textContent).toContain(land);
    expect(dialog.textContent).toContain(eda);
    expect(dialog.textContent).toContain('FOUNDER_STATED');
    expect(dialog.textContent).toContain('D2 draft notes');
  });

  it('defaults manual global and zone FAR to land area and permits EDA selection', () => {
    render(<ConstraintSetPanel apiBase="http://testserver" projectId="p" onSubmitDecision={vi.fn()} />);
    const global = screen.getByLabelText('FAR denominator constraint-far-site') as HTMLSelectElement;
    expect(global.value).toBe('land_area');
    fireEvent.change(global, { target: { value: 'exploration_design_area' } });
    expect(global.value).toBe('exploration_design_area');
    fireEvent.click(screen.getByRole('button', { name: 'Add zone FAR' }));
    expect((screen.getByLabelText('FAR denominator constraint-zone-far-1') as HTMLSelectElement).value).toBe('land_area');
  });
});
