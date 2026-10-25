"""Read-only observational height binding at freeze; no decision creation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from urban_design.approved_generation import ApprovedGenerationBlocked, _verify_artifact_bytes
from urban_design.morphology.floor_estimate import estimate_floor_count_from_3dbag
from urban_design.store import EntityNotFoundError
from urban_design.models import UnavailableValue
from urban_design.three_d_bag import load_3dbag_height_table


@dataclass(frozen=True)
class HeightBinding:
    snapshots: tuple[Any, ...]
    artifacts: tuple[Any, ...]
    manifest: tuple[dict, ...]
    estimates: tuple[dict, ...]


def bind_retained_heights(store, inputs) -> HeightBinding:
    """Bind all registered 3D BAG tile snapshots and reconcile normalized lineage.

    Missing tile snapshots or invalid bytes block the freeze. A missing building
    match stays UNAVAILABLE in a valid manifest, blocking subsequent hard FAR.
    This supplements D1 inputs with observations without changing D1 authority.
    """
    retained = inputs.retained_buildings
    if not retained:
        return HeightBinding((), (), (), ())
    try:
        snapshots = tuple(sorted((s for s in store.list_current('DatasetSnapshot', project_id=inputs.project_id)
                                 if '3dbag' in str(s.payload.get('source', '')).casefold()
                                 or '3d bag' in str(s.payload.get('source', '')).casefold()), key=lambda s: s.entity_id))
        if not snapshots:
            raise ValueError('missing registered 3D BAG DatasetSnapshot')
        artifacts = {}
        tables = {}
        manifest = []
        for snapshot in snapshots:
            if snapshot.payload.get('id') != snapshot.entity_id or snapshot.payload.get('project_id') != inputs.project_id:
                raise ValueError('3D BAG snapshot identity/project mismatch')
            raw_id = snapshot.payload.get('raw_artifact_id')
            normalized_id = snapshot.payload.get('normalized_artifact_id')
            if not isinstance(raw_id, str) or not isinstance(normalized_id, str):
                raise ValueError('3D BAG snapshot lacks raw/normalized artifact refs')
            raw = _verify_artifact_bytes(store, raw_id, inputs.project_id)
            normalized = _verify_artifact_bytes(store, normalized_id, inputs.project_id)
            if snapshot.payload.get('sha256', '').removeprefix('sha256:') != raw.payload['sha256'].removeprefix('sha256:'):
                raise ValueError('3D BAG snapshot SHA-256 differs from raw artifact')
            if raw_id not in normalized.payload.get('parent_artifact_ids', []):
                raise ValueError('3D BAG normalized artifact does not bind raw parent')
            if normalized_id not in tables:
                tables[normalized_id] = load_3dbag_height_table(normalized.payload['uri'])
            table = tables[normalized_id]
            if (table.study_area_id != inputs.study_area.entity_id
                    or table.study_area_geometry_sha256 != inputs.study_area.payload.get('geometry_sha256')):
                raise ValueError('3D BAG height table StudyArea binding mismatch')
            tile = [t for t in table.source_tiles if t.get('url') == snapshot.payload.get('source')]
            if len(tile) != 1 or tile[0].get('sha256') != raw.payload['sha256']:
                raise ValueError('3D BAG tile source lineage mismatch')
            if table.data_version != snapshot.payload.get('version'):
                raise ValueError('3D BAG snapshot version differs from height table')
            artifacts[raw_id], artifacts[normalized_id] = raw, normalized
            manifest.append(dict(snapshot_id=snapshot.entity_id, revision=snapshot.revision,
                payload_hash=hashlib.sha256(json.dumps(snapshot.payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                raw_artifact_id=raw_id, raw_sha256=raw.payload['sha256'],
                normalized_artifact_id=normalized_id, normalized_sha256=normalized.payload['sha256'],
                tile_id=tile[0]['tile_id'], data_version=table.data_version,
                vertical_reference=table.vertical_reference, license=table.license))
        # Every raw tile used to derive each height table must have a registered,
        # byte-verified snapshot, even when only one tile covers retained buildings.
        for table in tables.values():
            bound = {m['tile_id'] for m in manifest}
            if {t['tile_id'] for t in table.source_tiles} != bound:
                raise ValueError('missing 3D BAG snapshot for height-table source tile set')
        heights = [c for c in inputs.constraint_set.constraints if c.name == 'standard_floor_height' and c.scope == 'whole_site']
        if len(heights) != 1:
            raise ValueError('unique approved standard floor height required')
        estimates = []
        for disposition, geometry, properties in retained:
            bag_id = properties.get('bag_id') or properties.get('identificatie')
            matches = [(id, table, table.lookup(bag_id)) for id, table in tables.items() if table.lookup(bag_id) is not None]
            if len(matches) > 1:
                raise ValueError(f'ambiguous 3D BAG height match for {bag_id}')
            # No match remains unavailable; a table reference records the searched
            # source coverage rather than inventing an observation.
            id, table, record = matches[0] if matches else (next(iter(tables)), next(iter(tables.values())), None)
            use = str(properties.get('gebruiksdoel', ''))
            # BAG often lists several uses separated by commas.
            industrial = 'industriefunctie' in {v.strip().casefold() for v in use.split(',')}
            estimate = estimate_floor_count_from_3dbag(building_id=disposition.feature_id, bag_id=bag_id,
                building_use='industriefunctie' if industrial else use, height_table=table,
                floor_height_m=float(heights[0].value), floor_height_status='APPROVED',
                floor_height_decision_id=inputs.constraint_decision.id)
            count = estimate.floor_count
            unavailable = isinstance(count, UnavailableValue)
            lower, upper = (None, None) if unavailable else count if isinstance(count, tuple) else (count, count)
            demolished = (bag_id == '0599100000765601' and record is None
                          and str(properties.get('status', properties.get('pandstatus', ''))).casefold() == 'pand gesloopt')
            if demolished:
                unavailable = False
                lower = upper = 0
            source_ids = sorted(m['snapshot_id'] for m in manifest if m['normalized_artifact_id'] == id
                                and (record is None or m['tile_id'] in record.source_tile_ids))
            estimates.append(dict(building_id=disposition.feature_id, bag_id=bag_id,
                rule_version='formal-floor-estimate-upper-bound-v2', status='ASSUMED_COMMANDER' if demolished else 'UNAVAILABLE' if unavailable else 'ESTIMATE',
                commander_assumption='Demolished BAG #5: existing GFA zero; footprint remains excluded from new massing' if demolished else None,
                bag_observed_status=properties.get('status', properties.get('pandstatus')),
                footprint_source_artifact_id=getattr(disposition, "source_artifact_id", None),
                floor_height_m=estimate.floor_height_m, floor_height_decision_id=inputs.constraint_decision.id,
                floor_count=dict(status='UNAVAILABLE' if unavailable else 'ESTIMATE', lower=lower, upper=upper,
                    reason='ASSUMED_COMMANDER: source BAG Pand gesloopt; existing GFA zero' if demolished else count.reason if unavailable else 'PD-11 round(height / approved floor height); industrial range [1, estimate]'),
                footprint_area_m2=geometry.area, gfa_lower_m2=None if lower is None else geometry.area*lower,
                gfa_upper_m2=None if upper is None else geometry.area*upper,
                height_above_ground_m=None if record is None else record.height_above_ground_m,
                snapshot_ids=source_ids, artifact_id=id, artifact_sha256=artifacts[id].payload['sha256'],
                data_version=table.data_version, limitations=list(estimate.limitations)))
        return HeightBinding(snapshots, tuple(artifacts[k] for k in sorted(artifacts)), tuple(manifest), tuple(estimates))
    except (EntityNotFoundError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ApprovedGenerationBlocked([f'3D BAG freeze binding: {exc}']) from exc
