export type EditableFloor = { floor_id: string; level: number };

export type MassingCommand =
  | { type: 'add_floor'; new_floor_id: string }
  | { type: 'remove_floor'; floor_id: string }
  | { type: 'push_side'; floor_edge_indices: Array<[string, number]>; steps: number; origin_geometry_hash: string }
  | { type: 'move'; dx_m: number; dy_m: number }
  | { type: 'rotate'; angle_degrees: number };

export type RoadNodeRecord = {
  node_id: string;
  x_m: number;
  y_m: number;
  layer?: number | null;
  bridge?: boolean | null;
  tunnel?: boolean | null;
  lineage_ids: string[];
};

export type RoadEdgeRecord = {
  edge_id: string;
  start_node_id: string;
  end_node_id: string;
  layer?: number | null;
  bridge?: boolean | null;
  tunnel?: boolean | null;
  locked: boolean;
  lineage_ids: string[];
};

export type RoadGraphRecord = {
  graph_hash: string;
  nodes: RoadNodeRecord[];
  edges: RoadEdgeRecord[];
};

export type RoadSnapKind =
  | 'ENDPOINT'
  | 'NEAREST_POINT'
  | 'MIDPOINT'
  | 'INTERSECTION'
  | 'PERPENDICULAR'
  | 'QUARTER'
  | 'THREE_QUARTER';

export type RoadSnapCandidate = {
  kind: RoadSnapKind;
  snap_kind: RoadSnapKind;
  target_id: string;
  target_node_id: string | null;
  target_edge_ids: string[];
  x_m: number;
  y_m: number;
  distance_m: number;
  position_semantics: string;
  target_length_m?: number;
  distance_along_m?: number;
  target_fraction?: number;
};

export type RoadSnapSearchOptions = {
  /** The W5 two-kind set remains the default for existing callers. */
  kinds?: readonly RoadSnapKind[];
  /** A fixed node at the other end of an incident edge for PERPENDICULAR. */
  perpendicularAnchorNodeId?: string | null;
};

const DEFAULT_SNAP_KINDS: readonly RoadSnapKind[] = ['ENDPOINT', 'NEAREST_POINT'];
const EPSILON = 1e-9;

function hasKnownRoadLevel(record: Pick<RoadNodeRecord, 'layer' | 'bridge' | 'tunnel'> | Pick<RoadEdgeRecord, 'layer' | 'bridge' | 'tunnel'>): boolean {
  return typeof record.layer === 'number' && Number.isFinite(record.layer)
    && typeof record.bridge === 'boolean'
    && typeof record.tunnel === 'boolean';
}

function sameRoadLevel(
  first: Pick<RoadNodeRecord, 'layer' | 'bridge' | 'tunnel'>,
  second: Pick<RoadNodeRecord, 'layer' | 'bridge' | 'tunnel'> | Pick<RoadEdgeRecord, 'layer' | 'bridge' | 'tunnel'>,
): boolean {
  return hasKnownRoadLevel(first) && hasKnownRoadLevel(second)
    && first.layer === second.layer
    && first.bridge === second.bridge
    && first.tunnel === second.tunnel;
}

function hasConsistentRoadLevels(graph: RoadGraphRecord): boolean {
  const nodeById = new Map(graph.nodes.map((node) => [node.node_id, node]));
  return graph.edges.every((edge) => {
    const start = nodeById.get(edge.start_node_id);
    const end = nodeById.get(edge.end_node_id);
    return Boolean(start && end && sameRoadLevel(edge, start) && sameRoadLevel(edge, end));
  });
}

type Segment = {
  edge: RoadEdgeRecord;
  start: RoadNodeRecord;
  end: RoadNodeRecord;
  dx: number;
  dy: number;
  length: number;
  lengthSquared: number;
};

function segmentFor(edge: RoadEdgeRecord, nodeById: Map<string, RoadNodeRecord>): Segment | null {
  const start = nodeById.get(edge.start_node_id);
  const end = nodeById.get(edge.end_node_id);
  if (!start || !end) return null;
  if (![start.x_m, start.y_m, end.x_m, end.y_m].every(Number.isFinite)) return null;
  const dx = end.x_m - start.x_m;
  const dy = end.y_m - start.y_m;
  const lengthSquared = dx * dx + dy * dy;
  if (lengthSquared <= EPSILON * EPSILON) return null;
  const length = Math.sqrt(lengthSquared);
  return { edge, start, end, dx, dy, length, lengthSquared };
}

function candidateFor(input: {
  kind: RoadSnapKind;
  targetId: string;
  targetNodeId?: string | null;
  targetEdgeIds?: string[];
  x: number;
  y: number;
  queryX: number;
  queryY: number;
  positionSemantics: string;
  segment?: Segment;
  fraction?: number;
}): RoadSnapCandidate {
  const distanceAlong = input.segment && input.fraction !== undefined
    ? input.segment.length * input.fraction
    : undefined;
  return {
    kind: input.kind,
    snap_kind: input.kind,
    target_id: input.targetId,
    target_node_id: input.targetNodeId ?? null,
    target_edge_ids: input.targetEdgeIds ?? [],
    x_m: input.x,
    y_m: input.y,
    distance_m: Math.hypot(input.queryX - input.x, input.queryY - input.y),
    position_semantics: input.positionSemantics,
    ...(input.segment ? { target_length_m: input.segment.length } : {}),
    ...(distanceAlong !== undefined ? { distance_along_m: distanceAlong, target_fraction: input.fraction } : {}),
  };
}

function projectToSegment(segment: Segment, x: number, y: number): { x: number; y: number; fraction: number } {
  const fraction = Math.max(0, Math.min(1, ((x - segment.start.x_m) * segment.dx + (y - segment.start.y_m) * segment.dy) / segment.lengthSquared));
  return {
    x: segment.start.x_m + fraction * segment.dx,
    y: segment.start.y_m + fraction * segment.dy,
    fraction,
  };
}

function intersectionOf(first: Segment, second: Segment): { x: number; y: number; firstFraction: number; secondFraction: number } | null {
  const denominator = first.dx * second.dy - first.dy * second.dx;
  if (Math.abs(denominator) <= EPSILON) return null; // Parallel and collinear overlaps have no unique crossing point.
  const offsetX = second.start.x_m - first.start.x_m;
  const offsetY = second.start.y_m - first.start.y_m;
  const firstFraction = (offsetX * second.dy - offsetY * second.dx) / denominator;
  const secondFraction = (offsetX * first.dy - offsetY * first.dx) / denominator;
  if (firstFraction < -EPSILON || firstFraction > 1 + EPSILON || secondFraction < -EPSILON || secondFraction > 1 + EPSILON) return null;
  const boundedFirst = Math.max(0, Math.min(1, firstFraction));
  const boundedSecond = Math.max(0, Math.min(1, secondFraction));
  return {
    x: first.start.x_m + boundedFirst * first.dx,
    y: first.start.y_m + boundedFirst * first.dy,
    firstFraction: boundedFirst,
    secondFraction: boundedSecond,
  };
}

export function isRoadNodeLocked(graph: RoadGraphRecord, nodeId: string): boolean {
  return graph.edges.some((edge) => edge.locked && (edge.start_node_id === nodeId || edge.end_node_id === nodeId));
}

export function findRoadSnapCandidates(
  graph: RoadGraphRecord,
  nodeId: string,
  x_m: number,
  y_m: number,
  tolerance_m: number,
  options: RoadSnapSearchOptions = {},
): RoadSnapCandidate[] {
  if (!Number.isFinite(x_m) || !Number.isFinite(y_m) || !Number.isFinite(tolerance_m) || tolerance_m <= 0) return [];
  if (!hasConsistentRoadLevels(graph)) return [];
  const moving = graph.nodes.find((node) => node.node_id === nodeId);
  if (!moving) return [];
  const incident = graph.edges.filter((edge) => edge.start_node_id === nodeId || edge.end_node_id === nodeId);
  if (incident.length === 0 || incident.some((edge) => edge.locked)) return [];
  const kinds = new Set(options.kinds ?? DEFAULT_SNAP_KINDS);

  const usedNodeIds = new Set(graph.edges.flatMap((edge) => [edge.start_node_id, edge.end_node_id]));
  const incidentNodeIds = new Set(incident.flatMap((edge) => [edge.start_node_id, edge.end_node_id]));
  const endpointCandidates = kinds.has('ENDPOINT') ? graph.nodes
    .filter((node) => node.node_id !== nodeId && usedNodeIds.has(node.node_id) && sameRoadLevel(moving, node))
    .filter((node) => !incidentNodeIds.has(node.node_id) && Number.isFinite(node.x_m) && Number.isFinite(node.y_m))
    .map((node) => candidateFor({
      kind: 'ENDPOINT', targetId: node.node_id, targetNodeId: node.node_id,
      x: node.x_m, y: node.y_m, queryX: x_m, queryY: y_m,
      positionSemantics: 'existing connected road node',
    }))
    .filter((candidate) => candidate.distance_m <= tolerance_m)
    : [];

  const nodeById = new Map(graph.nodes.map((node) => [node.node_id, node]));
  const eligibleSegments = graph.edges
    .filter((edge) => !edge.locked && edge.start_node_id !== nodeId && edge.end_node_id !== nodeId && sameRoadLevel(moving, edge))
    .map((edge) => segmentFor(edge, nodeById))
    .filter((segment): segment is Segment => segment !== null)
    .sort((left, right) => left.edge.edge_id.localeCompare(right.edge.edge_id));
  const edgeCandidates: RoadSnapCandidate[] = [];

  if (kinds.has('NEAREST_POINT')) {
    eligibleSegments.forEach((segment) => {
      const projected = projectToSegment(segment, x_m, y_m);
      if (projected.fraction <= EPSILON || projected.fraction >= 1 - EPSILON) return;
      const candidate = candidateFor({
        kind: 'NEAREST_POINT', targetId: segment.edge.edge_id, targetEdgeIds: [segment.edge.edge_id],
        x: projected.x, y: projected.y, queryX: x_m, queryY: y_m,
        positionSemantics: 'nearest point on a finite straight road segment', segment, fraction: projected.fraction,
      });
      if (candidate.distance_m <= tolerance_m) edgeCandidates.push(candidate);
    });
  }

  const fractionKinds: Array<{ kind: 'MIDPOINT' | 'QUARTER' | 'THREE_QUARTER'; fraction: number }> = [
    { kind: 'QUARTER', fraction: 0.25 },
    { kind: 'MIDPOINT', fraction: 0.5 },
    { kind: 'THREE_QUARTER', fraction: 0.75 },
  ];
  for (const { kind, fraction } of fractionKinds) {
    if (!kinds.has(kind)) continue;
    eligibleSegments.forEach((segment) => {
      const candidate = candidateFor({
        kind, targetId: segment.edge.edge_id, targetEdgeIds: [segment.edge.edge_id],
        x: segment.start.x_m + fraction * segment.dx,
        y: segment.start.y_m + fraction * segment.dy,
        queryX: x_m, queryY: y_m,
        positionSemantics: `${kind.toLowerCase().replaceAll('_', '-')} of a straight road segment by length`,
        segment, fraction,
      });
      if (candidate.distance_m <= tolerance_m) edgeCandidates.push(candidate);
    });
  }

  if (kinds.has('PERPENDICULAR') && options.perpendicularAnchorNodeId) {
    const anchor = nodeById.get(options.perpendicularAnchorNodeId);
    const isFixedIncidentAnchor = anchor && anchor.node_id !== nodeId
      && incident.some((edge) => (edge.start_node_id === anchor.node_id || edge.end_node_id === anchor.node_id) && !edge.locked);
    if (anchor && isFixedIncidentAnchor && sameRoadLevel(moving, anchor)) {
      eligibleSegments.forEach((segment) => {
        const projected = projectToSegment(segment, anchor.x_m, anchor.y_m);
        const anchorDistance = Math.hypot(anchor.x_m - projected.x, anchor.y_m - projected.y);
        if (projected.fraction <= EPSILON || projected.fraction >= 1 - EPSILON || anchorDistance <= EPSILON) return;
        const candidate = candidateFor({
          kind: 'PERPENDICULAR', targetId: segment.edge.edge_id, targetEdgeIds: [segment.edge.edge_id],
          x: projected.x, y: projected.y, queryX: x_m, queryY: y_m,
          positionSemantics: `perpendicular projection from fixed incident anchor ${anchor.node_id} onto a finite straight segment`,
          segment, fraction: projected.fraction,
        });
        if (candidate.distance_m <= tolerance_m) edgeCandidates.push(candidate);
      });
    }
  }

  if (kinds.has('INTERSECTION')) {
    for (let firstIndex = 0; firstIndex < eligibleSegments.length; firstIndex += 1) {
      const first = eligibleSegments[firstIndex];
      if (!first) continue;
      for (let secondIndex = firstIndex + 1; secondIndex < eligibleSegments.length; secondIndex += 1) {
        const second = eligibleSegments[secondIndex];
        if (!second) continue;
        if ([first.edge.start_node_id, first.edge.end_node_id].some((id) => id === second.edge.start_node_id || id === second.edge.end_node_id)) continue;
        const crossing = intersectionOf(first, second);
        if (!crossing) continue;
        const edgeIds = [first.edge.edge_id, second.edge.edge_id].sort((left, right) => left.localeCompare(right));
        const primary = edgeIds[0] === first.edge.edge_id ? first : second;
        const fraction = edgeIds[0] === first.edge.edge_id ? crossing.firstFraction : crossing.secondFraction;
        const candidate = candidateFor({
          kind: 'INTERSECTION', targetId: edgeIds[0]!, targetEdgeIds: edgeIds,
          x: crossing.x, y: crossing.y, queryX: x_m, queryY: y_m,
          positionSemantics: 'at-grade intersection of compatible straight road segments',
          segment: primary, fraction,
        });
        if (candidate.distance_m <= tolerance_m) edgeCandidates.push(candidate);
      }
    }
  }

  return [...endpointCandidates, ...edgeCandidates].sort((left, right) => {
    const kindOrder = left.kind.localeCompare(right.kind);
    return kindOrder || left.distance_m - right.distance_m || left.target_id.localeCompare(right.target_id)
      || left.target_edge_ids.join('|').localeCompare(right.target_edge_ids.join('|'));
  });
}

export function commandFromDrag(input: {
  face: 'top' | 'side';
  deltaY: number;
  buildingId: string;
  floors: EditableFloor[];
  edgeIndex: number;
  originGeometryHash: string;
}): MassingCommand | null {
  if (input.face === 'top') {
    if (input.deltaY < 0) {
      const highestLevel = Math.max(...input.floors.map((floor) => floor.level), -1);
      return { type: 'add_floor', new_floor_id: `${input.buildingId}-floor-${highestLevel + 2}` };
    }
    if (input.floors.length <= 1) return null;
    const topFloor = [...input.floors].sort((left, right) => right.level - left.level)[0];
    return topFloor ? { type: 'remove_floor', floor_id: topFloor.floor_id } : null;
  }

  const metres = Math.round(Math.abs(input.deltaY) / 40);
  if (metres === 0) return null;
  const steps = Math.sign(-input.deltaY) * metres;
  return {
    type: 'push_side',
    floor_edge_indices: input.floors.map((floor) => [floor.floor_id, input.edgeIndex]),
    steps,
    origin_geometry_hash: input.originGeometryHash,
  };
}

export function oneMetreMove(dx_m: number, dy_m: number): MassingCommand {
  if (!Number.isInteger(dx_m) || !Number.isInteger(dy_m)) throw new Error('move increments must be whole metres');
  return { type: 'move', dx_m, dy_m };
}

export function rotationStep(angle_degrees: number): MassingCommand {
  if (!Number.isInteger(angle_degrees)) throw new Error('rotation increments must be whole degrees');
  return { type: 'rotate', angle_degrees };
}
