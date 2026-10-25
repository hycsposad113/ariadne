// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { ScenarioSyntaxControls, ProposalRoadLegend } from './ScenarioSyntaxControls';
import { comparisonContext, type ScenarioSyntaxResult } from '../utils/scenarioSyntax';
import { classifyContextValue } from '../utils/syntaxContext';
import { outsideRoadParts, proposalRoadMetadata, proposalRoadStyle, roadRibbonVertices } from '../utils/proposalRoads';
import { translate } from '../i18n';

const segment = { id:'s', coordinates:[[0,0],[10,0]] as [number,number][], distance_to_site_m:0, inside_site:true, boundary_effect_risk:false, nain:1, nach:.2 };
const result: ScenarioSyntaxResult = { status:'COMPUTED',mode:'pedestrian',radius_m:800,extract_buffer_m:1500,limitations:['EXPLORATORY'],
  legend_breaks:{nain:[0,.2,.4,.6,.8,1],nach:[0,.2,.4,.6,.8,1]},before:{segments:[segment],metrics:{}},after:{segments:[{...segment,nain:2}],metrics:{}},
  diff:[{...segment,delta:{nain:1,nach:-.1},comparison_status:'MATCHED_GEOMETRY'}] };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('scenario comparison DOM and road geometry', () => {
  it('switches modes and before/after/diff with a signed legend and after context values', async () => {
    const fetcher=vi.fn(async (url: string, _options?: RequestInit) => ({ok:true,json:async () => ({...result,mode:url.includes('bicycle')?'bicycle':'pedestrian'})}));
    vi.stubGlobal('fetch',fetcher);
    const onContext=vi.fn();
    render(<ScenarioSyntaxControls apiBase="http://fixture.test" scenarioId="scenario" onContext={onContext} />);
    await waitFor(() => expect(onContext.mock.calls.at(-1)?.[0]?.segments[0].nain).toBe(2));
    fireEvent.change(screen.getByLabelText('Syntax comparison view'),{target:{value:'before'}});
    await waitFor(() => expect(onContext.mock.calls.at(-1)?.[0]?.segments[0].nain).toBe(1));
    fireEvent.change(screen.getByLabelText('Syntax comparison view'),{target:{value:'diff'}});
    expect(await screen.findByTestId('syntax-difference-legend')).toBeTruthy();
    expect(screen.getByText('Warmer')).toBeTruthy();expect(screen.getByText('Cooler')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Transport mode'),{target:{value:'bicycle'}});
    await waitFor(() => expect(onContext.mock.calls.at(-1)?.[0]?.mode).toBe('bicycle'));
    expect(fetcher.mock.calls.some(([url])=>url.endsWith('mode=bicycle'))).toBe(true);
    expect(fetcher.mock.calls.every(([, options])=>!options)).toBe(true); // displaying never starts a paid or local compute job
  });
  it('clears stale values and never turns missing counterparts into zero', () => {
    expect(comparisonContext({...result,status:'STALE'},'after')).toBeNull();
    const context=comparisonContext({...result,diff:[{...result.diff[0],delta:null}]},'diff')!;
    expect(context.segments[0].nain).toBeNull();
    expect(classifyContextValue(context,'nain',null).isUncomputed).toBe(true);
    expect(classifyContextValue(context,'nain',1).strokeColor).toBe('#ef4444');
    expect(classifyContextValue(context,'nain',-1).strokeColor).toBe('#3b82f6');
  });
  it('defines mode styles and metre-wide 3D road surfaces', () => {
    const shared=proposalRoadMetadata({width_m:4.5});
    expect(shared.semantics_provenance).toBe('ASSUMED_COMMANDER');
    expect(proposalRoadStyle(shared).label).toBe('Pedestrian + bicycle');
    const collector=proposalRoadMetadata({road_id:'road:south_strip_collector:a',width_m:8});
    expect(proposalRoadStyle(collector).label).toBe('Motor / service access');
    const vertices=roadRibbonVertices([[0,0],[10,0]],4.5);
    expect(vertices.length).toBe(18);expect(vertices[1]).toBe(2.25);expect(vertices[4]).toBe(-2.25);
    render(<ProposalRoadLegend />);expect(screen.getByTestId('proposal-road-legend')).toBeTruthy();
    expect(translate('Pedestrian only','zh-TW')).toBe('僅行人');
  });
  it('removes replaced interior context strokes while preserving outside stubs and holes', () => {
    const site={type:'Polygon',coordinates:[[[0,0],[10,0],[10,10],[0,10],[0,0]]]};
    expect(outsideRoadParts([[-10,5],[20,5]],site)).toEqual([[[-10,5],[0,5]],[[10,5],[20,5]]]);
    expect(outsideRoadParts([[2,5],[8,5]],site)).toEqual([]);
  });
});
