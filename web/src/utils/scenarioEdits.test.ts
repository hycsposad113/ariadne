import { describe, expect, it } from 'vitest';
import { commandFromDrag, findRoadSnapCandidates, isRoadNodeLocked, type EditableFloor, type RoadGraphRecord } from './scenarioEdits';

const floors: EditableFloor[] = [
  { floor_id: 'b-floor-1', level: 0 },
  { floor_id: 'b-floor-2', level: 1 },
];

describe('scenario massing drag commands', () => {
  it('adds exactly one floor for an upward top-face drag regardless of drag distance', () => {
    expect(commandFromDrag({ face: 'top', deltaY: -240, buildingId: 'b-1', floors, edgeIndex: 0, originGeometryHash: 'abc' }))
      .toEqual({ type: 'add_floor', new_floor_id: 'b-1-floor-3' });
  });

  it('uses an integer metre count along the selected side and does not create free-scale commands', () => {
    expect(commandFromDrag({ face: 'side', deltaY: -45, buildingId: 'b-1', floors, edgeIndex: 2, originGeometryHash: 'abc' }))
      .toEqual({ type: 'push_side', floor_edge_indices: [['b-floor-1', 2], ['b-floor-2', 2]], steps: 1, origin_geometry_hash: 'abc' });
    expect(commandFromDrag({ face: 'side', deltaY: -12, buildingId: 'b-1', floors, edgeIndex: 2, originGeometryHash: 'abc' })).toBeNull();
  });

  it('removes one top floor on a downward top-face drag and protects the ground floor', () => {
    expect(commandFromDrag({ face: 'top', deltaY: 100, buildingId: 'b-1', floors, edgeIndex: 0, originGeometryHash: 'abc' }))
      .toEqual({ type: 'remove_floor', floor_id: 'b-floor-2' });
    expect(commandFromDrag({ face: 'top', deltaY: 100, buildingId: 'b-1', floors: floors.slice(0, 1), edgeIndex: 0, originGeometryHash: 'abc' })).toBeNull();
  });
});

const roadGraph: RoadGraphRecord = {
  graph_hash: 'graph-v1',
  nodes: [
    { node_id: 'west', x_m: 0, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'east', x_m: 10, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'moving', x_m: 4, y_m: 10, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'tail', x_m: 4, y_m: 20, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'endpoint', x_m: 5, y_m: 1, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'endpoint-tail', x_m: 5, y_m: 5, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'locked', x_m: 20, y_m: 0, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
    { node_id: 'locked-tail', x_m: 20, y_m: 10, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
  ],
  edges: [
    { edge_id: 'horizontal', start_node_id: 'west', end_node_id: 'east', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'moving-spur', start_node_id: 'moving', end_node_id: 'tail', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'endpoint-link', start_node_id: 'endpoint', end_node_id: 'endpoint-tail', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
    { edge_id: 'locked-road', start_node_id: 'locked', end_node_id: 'locked-tail', layer: 0, bridge: false, tunnel: false, locked: true, lineage_ids: [] },
  ],
};

describe('road snap previews', () => {
  it('shows the nearest compatible endpoint and nearest point candidates in ground metres', () => {
    const candidates = findRoadSnapCandidates(roadGraph, 'moving', 4.4, 0.2, 1.5);
    expect(candidates).toHaveLength(2);
    expect(candidates[0]).toMatchObject({ kind: 'ENDPOINT', target_id: 'endpoint', x_m: 5, y_m: 1 });
    expect(candidates[0]?.distance_m).toBeCloseTo(1, 10);
    expect(candidates[1]).toMatchObject({ kind: 'NEAREST_POINT', target_id: 'horizontal', x_m: 4.4, y_m: 0 });
    expect(candidates[1]?.distance_m).toBeCloseTo(0.2, 10);
  });

  it('does not offer drag or snap candidates for a node incident to a locked road', () => {
    expect(isRoadNodeLocked(roadGraph, 'locked')).toBe(true);
    expect(findRoadSnapCandidates(roadGraph, 'locked', 18, 1, 2)).toEqual([]);
  });

  it('places midpoint, quarter, and three-quarter candidates by straight-segment length', () => {
    const candidates = findRoadSnapCandidates(roadGraph, 'moving', 4.8, 0, 6, {
      kinds: ['MIDPOINT', 'QUARTER', 'THREE_QUARTER'],
    }).filter((candidate) => candidate.target_id === 'horizontal');

    expect(candidates.map((candidate) => [candidate.kind, candidate.x_m, candidate.y_m, candidate.distance_along_m, candidate.target_length_m, candidate.target_fraction]))
      .toEqual([
        ['MIDPOINT', 5, 0, 5, 10, 0.5],
        ['QUARTER', 2.5, 0, 2.5, 10, 0.25],
        ['THREE_QUARTER', 7.5, 0, 7.5, 10, 0.75],
      ]);
    expect(candidates.every((candidate) => candidate.position_semantics.includes('by length'))).toBe(true);
  });

  it('offers a perpendicular projection from an explicitly selected fixed incident anchor', () => {
    const candidates = findRoadSnapCandidates(roadGraph, 'moving', 4.2, 0.2, 1, {
      kinds: ['PERPENDICULAR'],
      perpendicularAnchorNodeId: 'tail',
    });

    expect(candidates).toHaveLength(1);
    expect(candidates[0]).toMatchObject({
      kind: 'PERPENDICULAR',
      target_id: 'horizontal',
      x_m: 4,
      y_m: 0,
      target_fraction: 0.4,
      position_semantics: 'perpendicular projection from fixed incident anchor tail onto a finite straight segment',
    });
    expect(candidates[0]?.distance_along_m).toBe(4);
  });

  it('offers only at-grade straight-segment intersections and keeps both target edges', () => {
    const crossingGraph: RoadGraphRecord = {
      graph_hash: 'crossing',
      nodes: [
        ...roadGraph.nodes,
        { node_id: 'north', x_m: 5, y_m: -5, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
        { node_id: 'south', x_m: 5, y_m: 5, layer: 0, bridge: false, tunnel: false, lineage_ids: [] },
      ],
      edges: [
        ...roadGraph.edges,
        { edge_id: 'vertical', start_node_id: 'north', end_node_id: 'south', layer: 0, bridge: false, tunnel: false, locked: false, lineage_ids: [] },
      ],
    };
    const candidate = findRoadSnapCandidates(crossingGraph, 'moving', 5.1, 0.1, 1, { kinds: ['INTERSECTION'] })[0];
    expect(candidate).toMatchObject({
      kind: 'INTERSECTION',
      target_id: 'horizontal',
      target_edge_ids: ['horizontal', 'vertical'],
      x_m: 5,
      y_m: 0,
      position_semantics: 'at-grade intersection of compatible straight road segments',
    });

    const gradeSeparated = {
      ...crossingGraph,
      edges: crossingGraph.edges.map((edge) => edge.edge_id === 'vertical' ? { ...edge, layer: 1 } : edge),
    };
    expect(findRoadSnapCandidates(gradeSeparated, 'moving', 5, 0, 1, { kinds: ['INTERSECTION'] })).toEqual([]);
  });

  it('fails closed when road-level metadata is unknown', () => {
    const unknownLayer: RoadGraphRecord = {
      ...roadGraph,
      nodes: roadGraph.nodes.map((node) => node.node_id === 'west' ? { ...node, layer: null } : node),
    };
    expect(findRoadSnapCandidates(unknownLayer, 'moving', 4, 0, 2)).toEqual([]);
  });
});
