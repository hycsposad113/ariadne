/// <reference types="node" />
// @vitest-environment jsdom
import {afterEach, describe, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {readFileSync} from 'node:fs';
import {I18nProvider} from '../i18n';
import {JudgementCard, JudgementPanel, type JudgementRecord} from './JudgementCard';
const record: JudgementRecord = {id:'card-a', status:'VALIDATED', round:2, created_at:'2026-10-17T00:00:00Z', model:'test-model', knowledge_units:[{id:'KU-CLI-007',title_zh:'日照與遮陰',title_en:'Sun and shade',summary_zh:'依季節檢視停留空間',summary_en:'Consider occupied space by season.'}], card:{skill_id:'J-CLIMATE',skill_version:'1.1.0',stage:'climate',subject:{kind:'scheme',ids:['harbour_grain']},judgement:{stance:'CONCERN',headline:'Outdoor space needs a seasonal review.'},observations:[{text:'Winter sunlight is limited.',refs:[{kind:'metric',id:'e1.harbour.winter.mean_h',value:1.79,unit:'h'}]}],reasoning:[{lens:'L1',text:'Inspect seasonal trade-offs before revising massing.',knowledge_refs:['KU-CLI-007']}],confidence:{level:'medium',why:'The available evidence has method limitations.'},revision_directions:[{action:'Review the southern building heights.',target:'courtyard',parameter_family:'height',expected_effect:'More winter sunlight.',trade_off:'Less floor area.'}],counterpoints:['Shade remains useful in summer.'],limitations:['Wind coupling is unavailable.'],questions_for_designer:['Which courtyard should be revised first?']}};
function wrap(node: React.ReactNode, language: 'en'|'zh-TW' = 'en') { return render(<I18nProvider language={language}>{node}</I18nProvider>); }
function json(data: unknown, ok = true) {return Promise.resolve({ok, json:async () => data} as Response);}
afterEach(() => {cleanup();vi.unstubAllGlobals();});
describe('JudgementCard', () => {
 it('keeps evidence collapsed and expands human metric and knowledge chips', async () => {
  wrap(<JudgementCard record={record}/>, 'zh-TW');
  expect(screen.queryByText('觀察與依據')).toBeNull();
  expect(screen.getByText('看依據與推理').closest('details')?.open).toBe(false);
  fireEvent.click(screen.getByText('看依據與推理'));
  await screen.findByText('觀察與依據');
  expect(screen.getByText('日照與遮陰').title).toContain('KU-CLI-007');
  fireEvent.click(screen.getByRole('button',{name:'港埠線性紋理｜冬至平均日照 1.79 小時'}));
  expect(screen.getByRole('note').textContent).toContain('1.79 小時');
  expect(screen.getByText(/test-model/)).toBeTruthy();
  expect(screen.getByText(/第 2 輪/)).toBeTruthy();
  expect(screen.getByText('看依據與推理').closest('article')?.textContent).not.toMatch(/CONCERN|e1\.harbour|KU-CLI/);
 });
 it('records agreement without mandatory text', async () => {
  const respond = vi.fn().mockResolvedValue(undefined); wrap(<JudgementCard record={record} onRespond={respond}/>);
  fireEvent.click(screen.getByRole('button',{name:'Agree'}));
  fireEvent.click(screen.getByRole('button',{name:'Record response'}));
  await screen.findByText(/Response recorded for the next round/); expect(respond).toHaveBeenCalledWith('agree','');
 });
 it('requires nonblank text, rejects over 1000 characters, and keeps input after failed response', async () => {
  const respond = vi.fn().mockRejectedValueOnce(new Error()).mockResolvedValueOnce(undefined);
  wrap(<JudgementCard record={record} onRespond={respond}/>);
  fireEvent.click(screen.getByRole('button',{name:'Agree'}));
  const button = screen.getByRole('button',{name:'Record response'}) as HTMLButtonElement;
  const input = screen.getByRole('textbox');
  expect(screen.getByRole('button',{name:'Agree'}).getAttribute('aria-pressed')).toBe('true');
  expect(button.disabled).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Contest'}));
  expect(button.disabled).toBe(true);
  expect(screen.getByRole('button',{name:'Contest'}).getAttribute('aria-pressed')).toBe('true');
  fireEvent.change(input,{target:{value:' '.repeat(10)}}); expect(button.disabled).toBe(true);
  fireEvent.change(input,{target:{value:'a'.repeat(1001)}}); expect(button.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Contest'}));
  fireEvent.change(input,{target:{value:'Review the winter assumption.'}}); fireEvent.click(button);
  await screen.findByRole('alert'); expect((input as HTMLTextAreaElement).value).toBe('Review the winter assumption.');
  fireEvent.click(button); await screen.findByText(/Response recorded for the next round/);
  expect(respond).toHaveBeenLastCalledWith('contest','Review the winter assumption.');
 });
});
describe('JudgementPanel', () => {
 it('loads history without any automatic model POST and creates a round only after a click', async () => {
  const fetcher = vi.fn((_: string, options?: RequestInit) => options?.method === 'POST' ? json({...record,id:'card-b',round:3}) : json({cards:[record],usage:{calls:7,limit:30}})); vi.stubGlobal('fetch', fetcher);
  wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-CLIMATE" subjectIds={['harbour_grain']}/>);
  await screen.findByText(/Weekly usage/);
  expect(fetcher.mock.calls.every(([,options]) => !options?.method)).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Request new round'}));
  await screen.findByRole('navigation',{name:'Earlier judgement rounds'});
  const post = fetcher.mock.calls.find(([,options]) => options?.method === 'POST');
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({skill_id:'J-CLIMATE',subject_ids:['harbour_grain'],language:'en',force:true});
  expect(screen.getAllByRole('article')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button',{name:'Round 2'}));
  expect(screen.getByRole('button',{name:'Round 2'}).getAttribute('aria-pressed')).toBe('true');
 });
 it('posts response then explicitly requests the next round; response is kept in history', async () => {
  const fetcher = vi.fn((url: string, options?: RequestInit) => url.endsWith('/responses') ? json({kind:'supplement',text:'Courtyards are occupied in winter.'}) : options?.method === 'POST' ? json({...record,id:'next',round:3}) : json({cards:[record],usage:{calls:7,limit:30}})); vi.stubGlobal('fetch', fetcher);
  wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-CLIMATE"/>);
  await screen.findByText(/Weekly usage/);
  fireEvent.click(screen.getByRole('button',{name:'Supplement'}));
  fireEvent.change(screen.getByRole('textbox'),{target:{value:'Courtyards are occupied in winter.'}});
  fireEvent.click(screen.getByRole('button',{name:'Record response'}));
  await screen.findByText(/Response recorded for the next round/);
  expect(fetcher.mock.calls.filter(([,options]) => options?.method === 'POST')).toHaveLength(1);
  fireEvent.click(screen.getByRole('button',{name:'Request new round'})); await screen.findByRole('navigation',{name:'Earlier judgement rounds'});
  fireEvent.click(screen.getByRole('button',{name:'Round 2'}));
  expect(screen.getByText('Courtyards are occupied in winter.',{exact:false})).toBeTruthy();
 });
 it('shows localized safe errors and never renders backend internal status codes', async () => {
  vi.stubGlobal('fetch',vi.fn(() => json({cards:[{...record,card:null,status:'BLOCKED_AI_AUTHORIZATION'}],usage:{calls:0,limit:30}})));
  wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-SITE"/>, 'zh-TW');
  await screen.findByText(/本週使用量/); expect(screen.queryByText(/BLOCKED_AI_AUTHORIZATION/)).toBeNull();
  expect(screen.getByText(/尚未啟用 AI 判讀/)).toBeTruthy();
 });
 it('offers a manual retry after request failure without automatic retry', async () => {
  const fetcher = vi.fn((_:string, options?:RequestInit) => options?.method === 'POST' ? json({},false) : json({cards:[],usage:{calls:0,limit:30}})); vi.stubGlobal('fetch',fetcher);
  wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-SITE"/>);
  await screen.findByText(/Weekly usage/); fireEvent.click(screen.getByRole('button',{name:'Ask Ariadne to interpret the site'}));
  await screen.findByRole('alert'); await waitFor(() => expect(fetcher.mock.calls.filter(([,options]) => options?.method === 'POST')).toHaveLength(1));
  expect((screen.getByRole('button',{name:'Ask Ariadne to interpret the site'}) as HTMLButtonElement).disabled).toBe(false);
 });
});

describe('live smoke fixtures', () => {
 for (const file of ['J-SITE-validated.json', 'J-COMPARE-validated.json', 'J-CLIMATE-harbour-validated.json']) {
  it(`renders ${file} without leaking identifiers or long decimals`, async () => {
   const fixture = JSON.parse(readFileSync(`${process.cwd()}/../artifacts/w8/rehearsal/p2-judgement/live-smoke/${file}`, 'utf8')) as JudgementRecord;
   const {container} = wrap(<JudgementCard record={fixture}/>, 'zh-TW');
   expect(container.querySelector('details')?.open).toBe(false);
   fireEvent.click(screen.getByText('看依據與推理')); await screen.findByText('觀察與依據');
   expect(container.textContent).not.toMatch(/\b[A-Z]+(?:_[A-Z0-9]+)+\b|(?:e[1-5]|utci|syntax|scheme|designer)\.[a-z]|KU-[A-Z]+-\d+|\d+\.\d{4,}/);
   for (const unit of fixture.knowledge_units ?? []) {
    if (fixture.card?.reasoning.some(reason => reason.knowledge_refs.includes(unit.id))) expect(screen.getAllByText(unit.title_zh!).length).toBeGreaterThan(0);
   }
  });
 }
 for (const language of ['en','zh-TW'] as const) for (const status of ['VALIDATION_FAILED','OUTCOME_UNKNOWN','BLOCKED_BUDGET','BLOCKED_AI_AUTHORIZATION','BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED']) {
  it(`localizes ${status} in ${language}`, () => {
   wrap(<JudgementCard record={{...record, card:null, status}}/>, language);
   expect(screen.getByRole('status').textContent).not.toMatch(/_[A-Z]/);
   if (status === 'OUTCOME_UNKNOWN') expect(screen.getByRole('status').textContent).toMatch(/管理者對帳|administrator/);
  });
 }
 it('uses English knowledge titles and resets details when switching rounds', async () => {
  vi.stubGlobal('fetch',vi.fn(() => json({cards:[record,{...record,id:'older',round:1,responses:[{kind:'contest',text:'Keep the courtyard.'}]}]})));
  wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-CLIMATE"/>);
  await screen.findByRole('button',{name:'Round 1'});
  fireEvent.click(screen.getByText('View evidence and reasoning')); await screen.findByText('Sun and shade');
  fireEvent.click(screen.getByRole('button',{name:'Round 1'}));
  expect(screen.queryByText('Sun and shade')).toBeNull();
  expect(screen.getByText(/Keep the courtyard/)).toBeTruthy();
 });
});

describe('judgement panel default round', () => {
  it('shows the most recent validated round when the newest round failed validation', async () => {
    const validated = {...record, id: 'ok-1', round: 1, status: 'VALIDATED'} as JudgementRecord;
    const failed = {...record, id: 'bad-2', round: 2, status: 'VALIDATION_FAILED', card: null} as unknown as JudgementRecord;
    vi.stubGlobal('fetch', vi.fn((input: string) => json(String(input).includes('/judgements?') ? {cards: [failed, validated]} : {mode: 'LIVE', weekly_calls_used: 1, weekly_call_limit: 200})));
    wrap(<JudgementPanel apiBase="" projectId="p" skillId="J-COMPARE" />, 'zh-TW');
    expect(await screen.findByText(/最新一輪（第 2 輪）未通過驗證/)).toBeTruthy();
    expect(screen.getByText(record.card!.judgement.headline)).toBeTruthy();
  });
});

describe('J-MORPH card text', () => {
  it('shows check failures and solar fields in plain words in both languages', () => {
    const record = JSON.parse(readFileSync(`${process.cwd()}/../artifacts/w8/rehearsal/p4a-morph/samples/judgement-morph.json`, 'utf8')) as JudgementRecord;
    for (const language of ['zh-TW', 'en'] as const) {
      const {container, unmount} = wrap(<JudgementCard record={record} />, language);
      const details = container.querySelector('details') as HTMLDetailsElement;
      details.open = true;
      fireEvent(details, new Event('toggle'));
      const text = container.textContent ?? '';
      expect(text).not.toMatch(/ROAD_WATERFRONT_COMBINED_BUDGET|SOUTH_QUAY_[A-Z_]+|BUILDING_STREET_EDGE_3M|h_north_edge|south_edge_height_max|DATA_GAP/);
      expect(text).toContain(language === 'zh-TW' ? '南碼頭立面連續性' : 'south quay facade continuity');
      unmount();
    }
  });

  it('shows the AI profile in the footer in both languages', () => {
    const zhRecord: JudgementRecord = { ...record, provider_profile_id: 'codex-cli' };
    const { container: zhContainer, unmount: unmountZh } = wrap(<JudgementCard record={zhRecord} />, 'zh-TW');
    const zhDetails = zhContainer.querySelector('details') as HTMLDetailsElement;
    zhDetails.open = true;
    fireEvent(zhDetails, new Event('toggle'));
    expect(zhContainer.textContent).toContain('由 codex-cli 產生');
    unmountZh();

    const enRecord: JudgementRecord = { ...record, provider_profile_id: 'claude-cli' };
    const { container: enContainer, unmount: unmountEn } = wrap(<JudgementCard record={enRecord} />, 'en');
    const enDetails = enContainer.querySelector('details') as HTMLDetailsElement;
    enDetails.open = true;
    fireEvent(enDetails, new Event('toggle'));
    expect(enContainer.textContent).toContain('Generated by claude-cli');
    unmountEn();
  });
});

describe('judgement panel language filtering', () => {
  it('shows missing language notice and generate button when no card matches UI language', async () => {
    const zhCard: JudgementRecord = {
      ...record,
      id: 'zh-card-1',
      round: 1,
      language: 'zh-TW',
      card: {
        ...record.card!,
        judgement: { stance: 'SUPPORT', headline: '中文判讀標題' },
      },
    };
    const fetcher = vi.fn((_url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        return json({ ...zhCard, id: 'en-card-2', round: 2, language: 'en', card: { ...record.card!, judgement: { stance: 'SUPPORT', headline: 'English headline' } } });
      }
      return json({ cards: [zhCard], usage: { calls: 1, limit: 30 } });
    });
    vi.stubGlobal('fetch', fetcher);

    wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-CLIMATE" />, 'en');
    await screen.findByText(/Weekly usage/);

    expect(screen.getByText('No English judgement card is available yet.')).toBeTruthy();
    const generateBtn = screen.getByRole('button', { name: 'Generate in English' });
    expect(generateBtn).toBeTruthy();
    expect(screen.queryByText('中文判讀標題')).toBeNull();

    // Clicking Generate in English issues POST with language: 'en'
    fireEvent.click(generateBtn);
    await waitFor(() => {
      const postCall = fetcher.mock.calls.find(([, opt]) => opt?.method === 'POST');
      expect(postCall).toBeTruthy();
      expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({ language: 'en' });
    });

    // Older rounds remain selectable
    expect(screen.getByRole('button', { name: 'Round 1' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Round 1' }));
    expect(screen.getByText('中文判讀標題')).toBeTruthy();
  });

  it('shows Chinese missing language notice and generate button when cards are in English and UI is zh-TW', async () => {
    const enCard: JudgementRecord = {
      ...record,
      id: 'en-card-1',
      round: 1,
      language: 'en',
      card: {
        ...record.card!,
        judgement: { stance: 'SUPPORT', headline: 'English headline' },
      },
    };
    const fetcher = vi.fn((_url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        return json({ ...enCard, id: 'zh-card-2', round: 2, language: 'zh-TW', card: { ...record.card!, judgement: { stance: 'SUPPORT', headline: '中文判讀標題' } } });
      }
      return json({ cards: [enCard], usage: { calls: 1, limit: 30 } });
    });
    vi.stubGlobal('fetch', fetcher);

    wrap(<JudgementPanel apiBase="http://fake" projectId="p" skillId="J-CLIMATE" />, 'zh-TW');
    await screen.findByText(/本週使用量/);

    expect(screen.getByText('目前尚無中文判讀卡。')).toBeTruthy();
    expect(screen.getByRole('button', { name: '以中文產生' })).toBeTruthy();
    expect(screen.queryByText('English headline')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '以中文產生' }));
    await waitFor(() => {
      const postCall = fetcher.mock.calls.find(([, opt]) => opt?.method === 'POST');
      expect(postCall).toBeTruthy();
      expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({ language: 'zh-TW' });
    });
  });
});
