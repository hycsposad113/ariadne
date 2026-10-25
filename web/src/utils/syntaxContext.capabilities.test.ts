import { afterEach, expect, it, vi } from 'vitest';
import { fetchSyntaxContext } from './syntaxContext';
afterEach(() => vi.unstubAllGlobals());
it('does not request disabled syntax context and reports the configured reason', async () => {
 const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ enabled: false, status: 'NOT_CONFIGURED', reason_zh: '尚未設定語法結果來源' }) }));
 vi.stubGlobal('fetch', fetch);
 await expect(fetchSyntaxContext('pedestrian', 1000, 'http://fixture', 'project')).rejects.toThrow('尚未設定語法結果來源');
 expect(fetch).toHaveBeenCalledExactlyOnceWith('http://fixture/api/v1/projects/project/syntax/context/capabilities');
});
it('requests context when capability is enabled', async () => {
 const fetch = vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith('capabilities') ? { enabled: true } : { segments: [] } }));
 vi.stubGlobal('fetch', fetch);
 expect(await fetchSyntaxContext('pedestrian', 1000, 'http://fixture', 'project')).toEqual({ segments: [] });
 expect(fetch).toHaveBeenCalledTimes(2); expect(fetch).toHaveBeenLastCalledWith('http://fixture/api/v1/projects/project/syntax/context?mode=pedestrian&distance_m=1000');
});
