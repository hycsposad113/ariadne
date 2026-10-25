// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import * as THREE from 'three';
import { Viewport2D } from './Viewport2D';
import { Viewport3D } from './Viewport3D';
import { ScenarioModel3D } from './ScenarioModel3D';
import type { Segment } from '../types';
const traces = vi.hoisted(() => ({ scenes: [] as unknown[] }));
vi.mock('../utils/surroundingContext', async importOriginal => ({
  ...await importOriginal<typeof import('../utils/surroundingContext')>(),
  useSurroundingContext: () => ({data:null,status:'idle',error:null}),
}));
vi.mock('three', async importOriginal => ({
  ...await importOriginal<typeof import('three')>(),
  WebGLRenderer: class {
    domElement=document.createElement('canvas'); shadowMap={enabled:false};
    setSize() {} setPixelRatio() {} dispose() {}
    render(scene: unknown) { traces.scenes.push(scene); }
  },
}));
const road: Segment = {id:'proposal-road',geometry:{type:'LineString',coordinates:[[90000,435000],[90020,435000]]},
  length_m:20,layer:0,modes:['pedestrian','bicycle'],origin:'new',width_m:4.5,semantics_provenance:'ASSUMED_COMMANDER'};
beforeEach(() => {
  traces.scenes=[];
  Object.defineProperty(HTMLElement.prototype,'clientWidth',{configurable:true,get:()=>800});
  Object.defineProperty(HTMLElement.prototype,'clientHeight',{configurable:true,get:()=>600});
  // Most 3D viewports schedule recursively; execute only the first frame per test.
  let first=true;
  vi.stubGlobal('requestAnimationFrame',vi.fn((callback: FrameRequestCallback) => { if(first) {first=false;callback(0);}return 1; }));
  vi.stubGlobal('cancelAnimationFrame',vi.fn());
});
afterEach(() => {cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();});

describe('proposal roads in actual viewport construction', () => {
  it('strokes the shared road in the 2D canvas with mode colour and a visible width', () => {
    const strokes:Array<{color:string;width:number}>=[];
    const context=new Proxy({strokeStyle:'',lineWidth:0,stroke(){strokes.push({color:this.strokeStyle,width:this.lineWidth});}}, {
      get(target,key) {return key in target ? target[key as keyof typeof target] : () => {};},
    });
    vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
    render(<Viewport2D studyAreaGeometry={null} buildings={[]} segments={[road]} activeSyntaxLayer={null} spatialZones={[]}
      selectedFeatureId={null} onSelectFeature={vi.fn()} figureContext={{} as never} figureExportReady={false} />);
    expect(strokes.some(s=>s.color==='#2dd4bf' && s.width===3)).toBe(true);
  });
  it('constructs an actual 4.5 metre road ribbon in Compare 3D, independent of Syntax visibility', () => {
    render(<Viewport3D studyAreaGeometry={null} buildings={[]} segments={[road]} selectedFeatureId={null}
      onSelectFeature={vi.fn()} figureContext={{} as never} figureExportReady={false} syntaxOverlayVisible={false} />);
    const scene=traces.scenes[0] as THREE.Scene;
    const ribbon=scene.getObjectByName('proposal-road-surface:proposal-road') as THREE.Mesh;
    expect(ribbon).toBeTruthy();expect(ribbon.geometry.getAttribute('position').count).toBe(6);
    expect((ribbon.material as THREE.MeshBasicMaterial).color.getHexString()).toBe('2dd4bf');
  });
  it('constructs proposal roads in the Refine massing viewer', () => {
    render(<ScenarioModel3D buildings={[]} roadFeatures={[{id:road.id,geometry:road.geometry,properties:{role:'road',width_m:4.5,modes:road.modes,origin:'new'}}]}
      selectedBuildingId="" onSelectBuilding={vi.fn()} onPreview={vi.fn()} onEdit={async()=>{}} />);
    const scene=traces.scenes[0] as THREE.Scene;
    expect(scene.getObjectByName('proposal-road:proposal-road')).toBeTruthy();
  });
});
