// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { Week7Chrome } from './Week7Actions';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function realMetadata() {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => new Response(JSON.stringify(
    String(input).endsWith('/scenarios')
      ? [{entity_id:'real-design',revision:3,label:'Persisted design',status:'PROPOSED'}]
      : {revision_label:'workspace@8 / real-design@3',workspace_ref:{entity_id:'workspace',revision:8},scenario_ref:{entity_id:'real-design',revision:3},cards:[],runs:[],geometry_valid:true,human_status:'not_reviewed',run_status:'SUCCEEDED',freshness_text:'CURRENT',evidence_status:'validated',evidence_availability:'complete',panels:{ai:{evidence_ids:['persisted-card','persisted-card']}}}
  )));
}
it('renders one real status bar, collapsed evidence and actions, and no console errors across identities', async () => {
  realMetadata();
  const errors = vi.spyOn(console, 'error');
  const {rerender} = render(<Week7Chrome apiBase="http://localhost" workspaceId={null} />);
  rerender(<Week7Chrome apiBase="http://localhost" workspaceId="workspace" />);
  await waitFor(() => expect(screen.getByTestId('week7-revision')).toHaveTextContent('workspace@8 / real-design@3'));
  expect(screen.getAllByTestId('week7-status')).toHaveLength(1);
  expect(screen.getByText('Evidence (1)').closest('details')).not.toHaveAttribute('open');
  expect(screen.getByTestId('week7-actions')).not.toHaveAttribute('open');
  expect(screen.queryByText('persisted-card')).not.toBeInTheDocument();
  expect(document.querySelectorAll('.week7-badges > span[title]')).toHaveLength(5);
  expect(errors).toHaveBeenCalledTimes(0);
});
it.each(['en','zh-TW'] as const)('provides labels, descriptions and eight groups in %s', async language => {
  realMetadata();
  render(<I18nProvider language={language}><Week7Chrome apiBase="http://localhost" workspaceId="workspace" /></I18nProvider>);
  await waitFor(() => expect(screen.getByTestId('week7-revision')).toHaveTextContent('workspace@8'));
  fireEvent.click(screen.getByText(language === 'en' ? 'Challenge and modify' : '質疑與修改'));
  screen.getByTestId('week7-actions').setAttribute('open','');
  expect(screen.getByLabelText(language === 'en' ? /Reason \/ challenge/ : /理由／質疑/)).toBeInTheDocument();
  const fieldLabels: Record<string, [string, string]> = {
    scenario: ['W7 方案', 'W7 scenario'],
    'compare scenario': ['W7 比較方案', 'W7 compare scenario'],
    execution: ['W7 原始分析', 'W7 execution'],
    'rerun method': ['W7 重跑方法', 'W7 rerun method'],
    'figure kind': ['W7 出圖', 'W7 figure kind'],
  };
  for (const field of ['scenario','compare scenario','execution','rerun method','figure kind']) {
    const label = language === 'zh-TW' ? fieldLabels[field][0] : fieldLabels[field][1];
    const control = screen.getByLabelText(label);
    expect(control.closest('label')?.querySelector('small')?.textContent).toBeTruthy();
  }
  for (const kind of ['inspect','challenge','modify','rerun','compare','fork','reject','override']) {
    expect(screen.getByTestId(`week7-op-${kind}`).closest('fieldset')?.querySelector('legend')).toHaveTextContent(new RegExp(kind,'i'));
  }
  expect(screen.getByTestId('week7-op-reject')).toHaveTextContent(language === 'en' ? 'Founder decision pending' : '待 Founder 決策');
  expect(screen.getByTestId('week7-op-override')).toHaveTextContent(language === 'en' ? 'Founder decision pending' : '待 Founder 決策');
});

it.each(['en','zh-TW'] as const)('keeps actions and Reason visible after switching in %s', async language => {
 realMetadata();
 render(<I18nProvider language={language}><Week7Chrome apiBase="http://localhost" workspaceId="workspace" /></I18nProvider>);
 await waitFor(()=>expect(screen.getByTestId('week7-op-inspect')).toBeEnabled());
 const actions=screen.getByTestId('week7-actions') as HTMLDetailsElement;
 actions.open=true;
 fireEvent(actions,new Event('toggle'));
 expect(screen.getByLabelText(language==='en'?/Reason \/ challenge/:/理由／質疑/)).toBeVisible();
 fireEvent.click(screen.getByRole('button',{name:language==='en'?'Switch scenario':'切換方案'}));
 await waitFor(()=>expect(screen.getByTestId('week7-actions')).not.toBe(actions));
 await waitFor(()=>expect(screen.getByTestId('week7-op-inspect')).toBeEnabled());
 expect(screen.getByLabelText(language==='en'?/Reason \/ challenge/:/理由／質疑/)).toBeVisible();
});
