"""Before/after values preserve missing measurements; deltas are deterministic."""
from __future__ import annotations

METRICS = {
    'courtyard_winter_mean_h': ('e1.harbour.courtyard.winter.mean_h', 'h'),
    'all_winter_mean_h': ('e1.harbour.all.winter.mean_h', 'h'),
    'all_winter_ge2h_pct': ('e1.harbour.all.winter.ge2h_pct', '%'),
    'street_winter_mean_h': ('e1.harbour.street.winter.mean_h', 'h'),
    'utci_very_strong_pct': ('utci.harbour.all.very_strong_pct', '%'),
}


def _previous_revision_metrics(proposal, registry, revision_root, previous_revision):
    """Measured results of the draft revision this proposal was applied on, if that revision was itself recomputed."""
    import json
    from pathlib import Path
    from .revision_inputs import assemble_revision
    subject = 'harbour_grain@draft-r' + str(previous_revision)
    for manifest in sorted(Path(revision_root).parent.glob('*/manifest.json')):
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError):
            continue
        if data.get('subject_id') == subject and data.get('project_id') == proposal['project_id']:
            try:
                return assemble_revision(None, proposal['project_id'], subject, registry, manifest.parent)['metrics']
            except (OSError, ValueError, KeyError):
                return {}
    return {}


_BASELINE_CACHE: dict = {}
_COMPARISON_CACHE: dict = {}


def cached_proposal_comparison(proposal, judgements, registry, revision_root):
    """Comparisons only change when the job (or the proposal's dry run) changes; recomputing them on every
    list/dialogue call read several revision bundles per proposal and starved the API."""
    import json
    job = proposal.get('job') or {}
    key = (str(revision_root), proposal.get('id'), proposal.get('card_id'), proposal.get('draft_revision'),
           json.dumps({k: job.get(k) for k in ('id', 'status', 'ended_at', 'judgement_id', 'previous_revision', 'draft_revision')}, sort_keys=True),
           json.dumps((proposal.get('dry_run') or {}).get('gfa_after_m2')))
    if key not in _COMPARISON_CACHE:
        _COMPARISON_CACHE[key] = proposal_comparison(proposal, judgements, registry, revision_root)
    return _COMPARISON_CACHE[key]


def _baseline_metrics(judgements, registry, project):
    if project in _BASELINE_CACHE:
        return _BASELINE_CACHE[project]
    try:
        from .inputs import assemble
        _BASELINE_CACHE[project] = assemble(getattr(judgements, 'store', None), project, 'J-CLIMATE', ['harbour_grain'], registry)['metrics']
        return _BASELINE_CACHE[project]
    except Exception:  # baseline artifacts unavailable: leave the comparison as a data gap
        return {}


def before_metrics_for(proposal, card, judgements, registry, revision_root, previous_revision):
    """The state a proposal was applied to: the previous draft revision's recomputed results, else the responded
    card's own metrics, else the baseline scheme (e.g. a J-MORPH card carries no E1 values). Returns (metrics, basis)."""
    ids = [ident for ident, _unit in METRICS.values()]
    candidates = [('previous_draft_revision', _previous_revision_metrics(proposal, registry, revision_root, previous_revision) if previous_revision else {}),
                  ('judgement_card', card.get('metrics', {}))]
    for basis, metrics in candidates:
        if any(metrics.get(ident, {}).get('value') is not None for ident in ids):
            return metrics, basis
    baseline = _baseline_metrics(judgements, registry, proposal['project_id'])
    return baseline, ('baseline_scheme' if any(baseline.get(ident, {}).get('value') is not None for ident in ids) else None)


def proposal_comparison(proposal, judgements, registry, revision_root):
    card = judgements.get(proposal['project_id'], proposal['card_id'])
    job = proposal.get('job') or {}
    errors = []
    before, before_basis = before_metrics_for(proposal, card, judgements, registry, revision_root,
                                              job.get('previous_revision', proposal.get('draft_revision')))
    after = {}
    if job.get('status') == 'SUCCEEDED':
        from .revision_inputs import assemble_revision
        subject = 'harbour_grain@draft-r' + str(job['draft_revision'])
        try:
            after = assemble_revision(None, proposal['project_id'], subject, registry, revision_root)['metrics']
        except (OSError, ValueError, KeyError) as exc:
            errors.append('REVISION_RESULTS_UNAVAILABLE:' + type(exc).__name__)
    comparison = {}
    for name, (ident, unit) in METRICS.items():
        old = before.get(ident, {}).get('value')
        new = after.get(ident, {}).get('value')
        comparison[name] = {'before': old, 'after': new, 'unit': unit,
                            'delta': new - old if isinstance(old, (float, int)) and isinstance(new, (float, int)) else None,
                            'status': 'AVAILABLE' if old is not None and new is not None else 'DATA_GAP'}
    dry = proposal.get('dry_run') or {}
    comparison['gfa_m2'] = {'before': dry.get('gfa_before_m2'), 'after': dry.get('gfa_after_m2'), 'unit': 'm²',
                            'floor_m2': 124842, 'floor_fraction': 0.85, 'floor_status': 'ASSUMED',
                            'before_meets_floor': dry['gfa_before_m2'] >= 124842 if dry.get('gfa_before_m2') is not None else None,
                            'after_meets_floor': not dry['below_gfa_floor'] if 'below_gfa_floor' in dry else None}
    comparison['affected_building_count'] = len(dry.get('affected_building_ids', []))
    comparison['before_basis'] = before_basis
    comparison['errors'] = errors
    return comparison
