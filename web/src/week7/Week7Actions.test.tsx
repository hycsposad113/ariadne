// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Week7Actions } from './FixtureWeek7Actions';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it('sends inspect to the server and shows the persisted payload', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input).endsWith('/e3e4')) {
      return new Response(JSON.stringify({ e3: { status: 'NOT_ACCEPTED' }, e4: { status: 'NOT_ACCEPTED' } }), { status: 200 });
    }
    return new Response(JSON.stringify({
      forged_calculation: false,
      result_count_unchanged: true,
    }), { status: 200 });
  });
  render(<Week7Actions apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  fireEvent.click(screen.getByTestId('week7-op-inspect'));
  const result = await screen.findByTestId('week7-op-result');
  await waitFor(() => expect(result).toHaveTextContent('forged_calculation'));
  expect(result).toHaveTextContent('false');
  expect(result).not.toHaveTextContent('live model reply');
  const inspectCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/operations/inspect'));
  expect(inspectCall).toBeTruthy();
  const init = inspectCall?.[1];
  expect(JSON.parse(String(init && typeof init === 'object' && 'body' in init ? init.body : '')).payload.evidence_id).toBe('card-b2-sun');
});

it('labels E3 and E4 as NOT_ACCEPTED from the server payload', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    e3: { status: 'NOT_ACCEPTED' },
    e4: { status: 'NOT_ACCEPTED' },
  }), { status: 200 }));
  render(<Week7Actions apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  expect(await screen.findByTestId('week7-e3e4')).toHaveTextContent('E3 NOT_ACCEPTED / E4 NOT_ACCEPTED');
});

it('keeps the compare action explicit about a different radius family', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    if (String(input).endsWith('/e3e4')) {
      return new Response(JSON.stringify({ e3: { status: 'NOT_ACCEPTED' }, e4: { status: 'NOT_ACCEPTED' } }), { status: 200 });
    }
    return new Response(JSON.stringify({
      comparable: false,
      not_comparable: ['unit', 'extent', 'method', 'radius_family'],
    }), { status: 200 });
  });
  render(<Week7Actions apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  fireEvent.click(screen.getByTestId('week7-op-compare'));
  await waitFor(() => expect(screen.getByTestId('week7-op-result')).toHaveTextContent('radius_family'));
  const compareCall = fetchMock.mock.calls.find((call) => String(call[0]).includes('/operations/compare'));
  expect(compareCall).toBeTruthy();
  const body = JSON.parse(String(compareCall?.[1]?.body));
  expect(body.payload.left.radius_family).toBe('accessibility');
  expect(body.payload.right.radius_family).toBe('syntax');
});
