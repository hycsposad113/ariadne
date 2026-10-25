// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { PanelEvidenceAndCritic } from './PanelEvidenceAndCritic';
import { I18nProvider, useI18n } from '../i18n';
import type { EvidenceCard } from '../types';

describe('Site Facts panel', () => {
  afterEach(() => { cleanup(); localStorage.clear(); });

  const evidenceCard: EvidenceCard = {
    card_id: 'card-building-count',
    metric_key: 'building-count',
    metric_name: 'Building count',
    value: 3,
    unit: 'features',
    confidence: 'HIGH',
    source: 'BAG',
    limitations: ['Observed footprint geometry does not establish buildability.'],
    timestamp: '2026-09-24T00:00:00Z',
    status: 'SOURCE_ALIGNED_COVERAGE_LIMITED',
    crs: 'EPSG:28992',
    query_bounds: [],
    algorithm_version: 'test',
    input_sha256: 'input-hash',
    output_sha256: 'output-hash',
    source_package_id: 'source-package',
    source_package_revision: 'r01',
    study_area_id: 'study-area-v5',
    study_area_revision: 1,
    study_area_geometry_sha256: 'geometry-hash',
    source_feature_ids: [],
    source_artifact_ids: [],
    dataset_snapshot_ids: [],
    parents: [],
  };

  it('shows the Site Facts record and source details without the former critic controls', () => {
    render(
      <PanelEvidenceAndCritic
        evidenceCards={[evidenceCard]}
        evidenceCardsStatus="VERIFIED_SOURCE_RESULT_ALIGNMENT"
        evidenceGaps={[]}
      />,
    );

    expect(screen.getByRole('heading', { name: /Site Facts/ })).toBeTruthy();
    expect(screen.getByText('Building count')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Evidence Critic/ })).toBeNull();
    expect(screen.getByTestId('site-facts-status').textContent).not.toContain('VERIFIED_SOURCE_RESULT_ALIGNMENT');
    expect(screen.getByTestId('site-facts-status').querySelector('[data-status="VERIFIED_SOURCE_RESULT_ALIGNMENT"]')).toBeTruthy();
    expect(screen.getByTestId('site-facts-status').querySelector('[title="Source-to-result alignment verified"]')).toBeTruthy();
    expect(screen.getByTestId('site-facts-status').textContent).toContain('Source-to-result alignment verified');
  });

  it('focuses a Site Facts card when an Ariadne citation opens it', () => {
    render(
      <PanelEvidenceAndCritic
        evidenceCards={[evidenceCard]}
        evidenceCardsStatus="VERIFIED_SOURCE_RESULT_ALIGNMENT"
        evidenceGaps={[]}
        focusedCardId="card-building-count"
      />,
    );

    expect(screen.getByTestId('site-fact-card-card-building-count').getAttribute('data-ariadne-focused')).toBe('true');
  });

  it('switches Site Facts labels immediately to Traditional Chinese', () => {
    function LanguageSwitch() {
      const { setLanguage } = useI18n();
      return <button onClick={() => setLanguage('zh-TW')}>中文</button>;
    }

    render(
      <I18nProvider>
        <LanguageSwitch />
        <PanelEvidenceAndCritic
          evidenceCards={[evidenceCard]}
          evidenceCardsStatus="UNKNOWN"
          evidenceGaps={[{ topic: 'land use and occupancy', status: 'UNKNOWN', reason: 'No verified same-version land-use or occupancy source is part of spatial-r01.' }]}
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: '中文' }));
    expect(screen.getByText('基地資料 (1)')).toBeTruthy();
    expect(screen.getByText(/土地使用與占用/)).toBeTruthy();
    expect(screen.getByTestId('site-facts-status').textContent).toContain('證據狀態：');
    expect(screen.getByTestId('site-facts-status').textContent).toContain('未知狀態');
    expect(screen.queryByText('Site Facts (1)')).toBeNull();
  });
});
