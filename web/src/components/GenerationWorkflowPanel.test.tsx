// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { GenerationWorkflowPanel } from './GenerationWorkflowPanel';
import { clearReadinessCache, fetchDedupedReadiness } from '../utils/readinessClient';
const root = 'http://127.0.0.1:8830/api/v1/projects/fixture/generation-workflows';
const receipt = { workflow_id: 'wf1', project_id: 'fixture', mode: 'FULL_SCHEME',
  status: 'AWAITING_SELECTION', readiness: 'FIXTURE_ONLY', stage: 'MASSING', job_id: 'job1',
  job_status: 'READY', manifest_sha256: `sha256:${'1'.repeat(64)}`, publication_status: 'FIXTURE_ONLY', accepted: false,
  output_refs: [{ artifact_id: 'candidate-a', relative_path: 'a.json', sha256: `sha256:${'2'.repeat(64)}` }] };
function response(value: unknown) { return new Response(JSON.stringify(value)); }
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); clearReadinessCache(); });

it.each(['en', 'zh-TW'] as const)('blocks all modes without approved context (%s)', async language => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response({ ...receipt, workflow_id: null, mode: null,
    status: 'NOT_READY', readiness: 'BLOCKED', output_refs: [] }));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language={language} />);
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('GenerationContext'));
  const select = screen.getByRole('combobox');
  expect(select.querySelectorAll('option')).toHaveLength(3);
  const start = screen.getByRole('button', { name: language === 'en' ? 'Start workflow' : '開始流程' });
  expect((start as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(start);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('restores by GET and binds stage selection to job and manifest, without acceptance', async () => {
  localStorage.setItem(`generation-workflow:${root}`, 'wf1');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(receipt));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" />);
  await screen.findByText('candidate-a');
  expect(fetch.mock.calls[0][0]).toBe(`${root}/wf1`);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Select for this workflow' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(JSON.parse(fetch.mock.calls[1][1]!.body as string)).toEqual({job_id: 'job1', manifest_sha256: receipt.manifest_sha256, artifact_ids: ['candidate-a']});
});

it('restores a lost start response by persisted request key without redispatch', async () => {
  localStorage.setItem(`generation-workflow:${root}:start`, 'request-1');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(receipt));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" />);
  await screen.findByText('candidate-a');
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toBe(`${root}/requests/request-1`);
});

it('shows outcome unknown and prevents repeating a failed dispatch', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response({ ...receipt, workflow_id: null, mode: null,
    status: 'READY_TO_START', output_refs: [] })).mockRejectedValueOnce(new Error('lost response'));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" />);
  await waitFor(() => expect((screen.getByRole('button', {name: 'Start workflow'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Start workflow' }));
  await screen.findByText(/OUTCOME_UNKNOWN/);
  expect((screen.getByRole('button', {name: 'Start workflow'}) as HTMLButtonElement).disabled).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('401 stops mutations without retry', async () => {
  localStorage.setItem(`generation-workflow:${root}`, 'wf1');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response({ ...receipt, mode: 'STEPWISE', status: 'READY_TO_RUN', job_status: null,
    stage: 'BLOCK_PROGRAM', output_refs: [] })).mockResolvedValueOnce(new Response('{}', {status: 401}));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" />);
  await waitFor(() => expect((screen.getByRole('button', {name: 'Continue generation'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Continue generation' }));
  await screen.findByText(/Request failed/);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect((screen.getByRole('button', {name: 'Reconcile after restart'}) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole('button', {name: 'Refresh receipt'}) as HTMLButtonElement).disabled).toBe(true);
});

it('can explicitly start a new mode after completion while retaining the server workflow', async () => {
  localStorage.setItem(`generation-workflow:${root}`, 'wf1');
  localStorage.setItem(`generation-workflow:${root}:start`, 'old-request');
  const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response({...receipt, status: 'COMPLETE_UNACCEPTED'}))
    .mockResolvedValueOnce(response({...receipt, workflow_id: null, mode: null, status: 'READY_TO_START', output_refs: []}));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" />);
  await waitFor(() => expect((screen.getByRole('button', {name: 'New workflow'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', {name: 'New workflow'}));
  await screen.findByRole('button', {name: 'Start workflow'});
  fireEvent.change(screen.getByRole('combobox'), {target: {value: 'STEPWISE'}});
  expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('STEPWISE');
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][1]?.method).toBe('GET');
  expect(localStorage.getItem(`generation-workflow:${root}:start`)).toBeNull();
});

it.each(['en', 'zh-TW'] as const)('shows checking readiness with spinner in-flight and never blocked early (%s)', async language => {
  let resolvePromise: (res: Response) => void;
  const inFlightPromise = new Promise<Response>(resolve => { resolvePromise = resolve; });
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => inFlightPromise);

  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language={language} />);

  const checkingText = language === 'en' ? 'Checking readiness…' : '正在檢查生成準備度…';
  const blockedText = 'approved GenerationContext required';
  expect(screen.getByRole('status').textContent).toContain(checkingText);
  expect(screen.getByRole('status').querySelector('.spinner')).not.toBeNull();
  expect(screen.queryByText(new RegExp(blockedText, 'i'))).toBeNull();
  expect((screen.getByRole('button', { name: language === 'en' ? 'Start workflow' : '開始流程' }) as HTMLButtonElement).disabled).toBe(true);

  resolvePromise!(response({ ...receipt, workflow_id: null, mode: null, status: 'NOT_READY', readiness: 'BLOCKED', output_refs: [] }));
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain(language === 'en' ? 'GenerationContext' : '已批准'));
});

it('shows server error when readiness fetch fails and never shows NOT_READY/BLOCKED', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('Internal server error', { status: 500 }));
  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language="en" />);

  await screen.findByRole('alert');
  expect(screen.getByRole('alert').textContent).toContain('Internal server error');
  expect(screen.queryByText(/approved GenerationContext required/i)).toBeNull();
});

it('FULL_SCHEME auto-advances, hides advance button, and displays View in Compare button', async () => {
  const onResults = vi.fn();
  const fetch = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(response({ ...receipt, workflow_id: null, mode: null, status: 'READY_TO_START', output_refs: [] }))
    .mockResolvedValueOnce(response({ ...receipt, workflow_id: 'wf-full', mode: 'FULL_SCHEME', status: 'READY_TO_RUN', job_status: null }))
    .mockResolvedValueOnce(response({ ...receipt, workflow_id: 'wf-full', mode: 'FULL_SCHEME', status: 'COMPLETE_UNACCEPTED', job_status: 'READY', publication_status: 'PUBLISHED' }));

  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language="en" onResults={onResults} />);

  await waitFor(() => expect((screen.getByRole('button', { name: 'Start workflow' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Start workflow' }));

  await waitFor(() => expect(screen.queryByRole('button', { name: 'Continue generation' })).toBeNull());

  const viewBtn = await screen.findByRole('button', { name: 'View in Compare' });
  expect(viewBtn).not.toBeNull();
  expect(screen.getByText(/Complete/)).not.toBeNull();

  fireEvent.click(viewBtn);
  expect(onResults).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls[2][0]).toBe(`${root}/wf-full/advance`);
});

it('FULL_SCHEME in zh-TW shows 到比較分頁查看 and completed state', async () => {
  localStorage.setItem(`generation-workflow:${root}`, 'wf-full');
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
    response({ ...receipt, workflow_id: 'wf-full', mode: 'FULL_SCHEME', status: 'COMPLETE_UNACCEPTED', job_status: 'READY', publication_status: 'PUBLISHED' })
  );

  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language="zh-TW" />);

  await screen.findByRole('button', { name: '到比較分頁查看' });
  expect(screen.queryByRole('button', { name: '繼續生成' })).toBeNull();
  expect(screen.getByText(/已完成/)).not.toBeNull();
});

it('STAGED mode (STEPWISE) shows advance button', async () => {
  localStorage.setItem(`generation-workflow:${root}`, 'wf-stepwise');
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
    response({ ...receipt, workflow_id: 'wf-stepwise', mode: 'STEPWISE', status: 'READY_TO_RUN', stage: 'BLOCK_PROGRAM', job_status: null })
  );

  render(<GenerationWorkflowPanel apiBase="http://127.0.0.1:8830" projectId="fixture" language="en" />);

  await waitFor(() => expect(screen.getByRole('button', { name: 'Continue generation' })).not.toBeNull());
  expect(screen.queryByRole('button', { name: 'View in Compare' })).toBeNull();
});

it('deduplicates concurrent readiness requests with only one in flight', async () => {
  let resolvePromise: (value: any) => void;
  const delayedPromise = new Promise(resolve => { resolvePromise = resolve; });
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(() => delayedPromise as Promise<Response>);

  const p1 = fetchDedupedReadiness(`${root}/readiness`);
  const p2 = fetchDedupedReadiness(`${root}/readiness`);
  expect(fetchSpy).toHaveBeenCalledTimes(1);

  resolvePromise!(response({ ...receipt, workflow_id: null, mode: null, status: 'NOT_READY', readiness: 'BLOCKED', output_refs: [] }));
  const [res1, res2] = await Promise.all([p1, p2]);
  expect(res1).toEqual(res2);
  expect(fetchSpy).toHaveBeenCalledTimes(1);
});


