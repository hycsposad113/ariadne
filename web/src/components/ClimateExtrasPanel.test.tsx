// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('./JudgementCard', () => ({JudgementPanel: ({skillId, subjectIds}: {skillId:string;subjectIds?:string[]}) => <section data-testid="judgement-placement" data-skill={skillId} data-subjects={subjectIds?.join(',')} />}));
import { ClimateExtrasPanel } from './ClimateExtrasPanel';
import { I18nProvider } from '../i18n';

const mockClimateSections = [
  {
    id: 'e1-fabric',
    title_zh: 'E1 四案日照對照',
    title_en: 'E1 Four-Fabric Sunlight Comparison',
    label_zh: '探索性，非認證',
    label_en: 'Exploratory, not certification',
    status: 'OK',
    missing_files: [],
    figures: [
      {
        path: 'e1-fabric/e1-compare-20261221-冬至-zh.png',
        path_en: 'e1-fabric/e1-compare-20261221-winter-solstice-en.png',
        title_zh: '冬至日照對照圖（2026-12-21）',
        title_en: 'Winter Solstice Sunlight Comparison (2026-12-21)',
        caption_zh: '四案冬至全日照時數與 ≥2h 比例對比',
        caption_en: 'Comparison of full-day sunlight hours and >=2h compliance across four fabrics on Winter Solstice',
        tag: '2026-12-21',
        season: 'winter_solstice',
      },
      {
        path: 'e1-fabric/e1-compare-20260321-春分-zh.png',
        title_zh: '春分日照對照圖（2026-03-21）',
        title_en: 'Spring Equinox Sunlight Comparison (2026-03-21)',
        caption_zh: '四案春分全日照時數與 ≥2h 比例對比',
        caption_en: 'Comparison of full-day sunlight hours and >=2h compliance across four fabrics on Spring Equinox',
        tag: '2026-03-21',
        season: 'spring_equinox',
      },
      {
        path: 'e1-fabric/e1-compare-20260621-夏至-zh.png',
        title_zh: '夏至日照對照圖（2026-06-21）',
        title_en: 'Summer Solstice Sunlight Comparison (2026-06-21)',
        caption_zh: '四案夏至全日照時數與 ≥2h 比例對比',
        caption_en: 'Comparison of full-day sunlight hours and >=2h compliance across four fabrics on Summer Solstice',
        tag: '2026-06-21',
        season: 'summer_solstice',
      },
    ],
    table: {
      columns: [
        { key: '紋理方案代碼', title_zh: '方案代碼', title_en: 'Scheme Code' },
        { key: '紋理方案名稱', title_zh: '方案名稱', title_en: 'Scheme Name' },
        { key: '開放空間類別', title_zh: '空間類別', title_en: 'Space Category' },
        { key: '冬至平均日照_小時', title_zh: '冬至平均日照 (h)', title_en: 'Winter Mean Sun (h)' },
      ],
      rows: [
        {
          紋理方案代碼: 'harbour_grain',
          紋理方案名稱: '港埠線性紋理',
          fabric_name_en: 'Harbour grain',
          開放空間類別: '全體開放空間',
          space_category_en: 'Total Open Space',
          冬至平均日照_小時: '2.75',
          is_selected: true,
        },
        {
          紋理方案代碼: 'closed_block_extension',
          紋理方案名稱: '圍合街廓延伸',
          fabric_name_en: 'Closed-block extension',
          開放空間類別: '全體開放空間',
          space_category_en: 'Total Open Space',
          冬至平均日照_小時: '3.28',
          is_selected: false,
        },
      ],
    },
    limitations_zh: '探索性分析，非日照權或法規認證。',
    limitations_en: 'Exploratory analysis, not statutory sunlight certification.',
    source_sha256: { 'comparison_table.csv': 'abc123hash' },
  },
  {
    id: 'utci',
    title_zh: 'UTCI 夏季熱舒適',
    title_en: 'UTCI Summer Thermal Comfort',
    label_zh: '探索性，非認證',
    label_en: 'Exploratory, not certification',
    status: 'OK',
    missing_files: [],
    figures: [
      {
        path: 'utci/harbour_grain_utci_1400.png',
        path_en: 'utci/harbour_grain_utci_1400-en.png',
        title_zh: '港埠線性紋理 14:00 UTCI 分布圖（選定）',
        title_en: 'Harbour grain 14:00 UTCI (Selected)',
        caption_zh: '最熱夏日（2017-08-19 14:00）開放空間 UTCI 等級分布圖',
        caption_en: 'Open space UTCI stress level distribution at 14:00 on the hottest summer day',
        fabric: 'harbour_grain',
        tag: 'harbour_grain',
      },
      {
        path: 'utci/closed_block_extension_utci_1400.png',
        title_zh: '圍合街廓延伸 14:00 UTCI 分布圖',
        title_en: 'Closed-block extension 14:00 UTCI',
        caption_zh: '最熱夏日開放空間 UTCI 等級分布圖',
        caption_en: 'Open space UTCI stress level distribution',
        fabric: 'closed_block_extension',
        tag: 'closed_block_extension',
      },
    ],
    table: {
      columns: [
        { key: 'scheme_name', title_zh: '方案名稱', title_en: 'Scheme' },
        { key: 'category_name', title_zh: '空間類別', title_en: 'Space Category' },
        { key: 'mean_utci_c', title_zh: '平均 UTCI (°C)', title_en: 'Mean UTCI (°C)' },
      ],
      rows: [
        {
          fabric_id: 'harbour_grain',
          scheme_name: '港埠線性紋理',
          scheme_name_en: 'Harbour grain',
          is_selected: true,
          category_name: '全體開放空間',
          category_name_en: 'Total Open Space',
          mean_utci_c: '36.1',
        },
      ],
    },
    limitations_zh: '探索性分析；風速採都市粗糙度對數律換算。',
    limitations_en: 'Exploratory UTCI analysis; wind speed derived from logarithmic profile.',
    source_sha256: { 'utci_stress_hours_comparison.json': 'def456hash' },
  },
  {
    id: 'e3-energy',
    title_zh: 'E3 建築耗能',
    title_en: 'E3 Building Energy Use',
    label_zh: '探索性，非認證',
    label_en: 'Exploratory, not certification',
    status: 'OK',
    missing_files: [],
    figures: [
      {
        path: 'e3e4-final/e3_eui_by_fabric.png',
        title_zh: '四案形態 EUI 比較圖（重質構造）',
        title_en: 'EUI Comparison by Fabric (Heavy Mass)',
        caption_zh: '全量建物模型重質構造年度 EUI 對比',
        caption_en: 'Annual EUI across full-model fabrics under heavy mass',
      },
    ],
    table: {
      columns: [
        { key: 'scheme_name', title_zh: '方案', title_en: 'Scheme' },
        { key: 'eui', title_zh: 'EUI (kWh/m²·年)', title_en: 'EUI (kWh/m²·y)' },
      ],
      rows: [
        {
          scheme_name: '港埠線性紋理',
          scheme_name_en: 'Harbour grain',
          is_selected: true,
          eui: '93.4',
        },
      ],
    },
    limitations_zh: '探索性分析，非能源認證。',
    limitations_en: 'Exploratory analysis, not energy certification.',
    source_sha256: { 'e3e4_results_zh.csv': 'e3hash' },
  },
  {
    id: 'e4-thermal-mass',
    title_zh: 'E4 蓄熱',
    title_en: 'E4 Thermal Mass Performance',
    label_zh: '探索性，非認證',
    label_en: 'Exploratory, not certification',
    status: 'OK',
    missing_files: [],
    figures: [
      {
        path: 'e3e4-final/e4_harbour_mass_vs_light.png',
        title_zh: '港埠方案重質 vs 輕質構造蓄熱表現',
        title_en: 'Harbour Grain Heavy Mass vs Light Construction',
        caption_zh: '港埠 253 棟重質與等效輕質構造在過熱時數之對比',
        caption_en: 'Thermal mass comparison of overheating hours for Harbour grain',
      },
    ],
    table: {
      columns: [
        { key: 'metric_zh', title_zh: '指標', title_en: 'Metric' },
        { key: 'mass_val', title_zh: '重質 (CZ5_Mass)', title_en: 'Heavy Mass' },
        { key: 'light_val', title_zh: '輕質 (CZ5_Light)', title_en: 'Light Construction' },
        { key: 'diff_val', title_zh: '輕質減重質', title_en: 'Difference' },
      ],
      rows: [
        {
          metric_zh: '夏季過熱時數',
          metric_en: 'Summer Overheating Hours',
          mass_val: '840.4',
          light_val: '883.9',
          diff_val: '+43.5',
        },
      ],
    },
    limitations_zh: '探索性分析，非材料熱性能認證。',
    limitations_en: 'Exploratory analysis, not material thermal certification.',
    source_sha256: { 'e4_harbour_mass_vs_light.png': 'e4hash' },
  },
  {
    id: 'e5-cfd',
    title_zh: 'E5 行人風場',
    title_en: 'E5 Pedestrian Wind Comfort',
    label_zh: '探索性，非認證',
    label_en: 'Exploratory, not certification',
    status: 'OK',
    missing_files: [],
    figures: [
      {
        path: 'e5-cfd/cfd_4winds_summary.png',
        title_zh: '4 風向 2x2 對比總覽面板',
        title_en: '4-Direction Wind Speed Ratio Summary (2x2)',
        caption_zh: '4 風向風速比總覽',
        caption_en: '4-direction wind ratio summary',
      },
    ],
    table: {
      columns: [
        { key: 'direction', title_zh: '風向', title_en: 'Direction' },
        { key: 'mean_ratio', title_zh: '平均風速比', title_en: 'Mean Wind Ratio' },
      ],
      rows: [
        { direction: 'SW', mean_ratio: '0.39' },
      ],
    },
    limitations_zh: 'Commander 審查補充：行人高度換算的限制',
    limitations_en: 'Commander Review Note: Pedestrian Level Conversion Limitations',
    source_sha256: { 'results_table.json': 'e5hash' },
  },
];

describe('ClimateExtrasPanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders Chinese view with proper badges, figures, tables, and scheme selection', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockClimateSections), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    render(
      <I18nProvider language="zh-TW">
        <ClimateExtrasPanel apiBase="http://127.0.0.1:8981" />
      </I18nProvider>
    );

    // Verify title and exploratory badge
    await waitFor(() => {
      expect(screen.getByText('附加氣候模擬（探索性）')).toBeTruthy();
    });
    expect(screen.getAllByText('探索性，非認證').length).toBeGreaterThan(0);
    expect(screen.getByRole('img', { name: '冬至日照對照圖（2026-12-21）' }).getAttribute('src')).toContain('-zh.png');

    expect(screen.getByTestId('judgement-placement').dataset.skill).toBe('J-CLIMATE');
    expect(screen.getByTestId('judgement-placement').dataset.subjects).toBe('harbour_grain');
    fireEvent.change(screen.getByRole('combobox', {name: '判讀範圍'}), {target:{value:'all'}});
    expect(screen.getByTestId('judgement-placement').dataset.subjects).toBe('harbour_grain,closed_block_extension,courtyard_islands,landscape_figure');
    // Verify all 5 section titles in Chinese
    expect(screen.getByText('E1 四案日照對照')).toBeTruthy();
    expect(screen.getByText('UTCI 夏季熱舒適')).toBeTruthy();
    expect(screen.getByText('E3 建築耗能')).toBeTruthy();
    expect(screen.getByText('E4 蓄熱')).toBeTruthy();
    expect(screen.getByText('E5 行人風場')).toBeTruthy();

    // Verify scheme selection badge
    const selectedBadges = screen.getAllByText('選定');
    expect(selectedBadges.length).toBeGreaterThan(0);

    // Verify date switching buttons in E1
    const springBtn = screen.getByRole('button', { name: '春分 (2026-03-21)' });
    fireEvent.click(springBtn);
    expect(springBtn.className).toContain('active');

    // Verify UTCI scheme switcher
    const closedBlockBtn = screen.getByRole('button', { name: '圍合街廓延伸' });
    fireEvent.click(closedBlockBtn);
    expect(closedBlockBtn.className).toContain('active');

    // Verify Limitations section
    expect(screen.getAllByText('限制說明').length).toBe(5);
    expect(screen.getByText('Commander 審查補充：行人高度換算的限制')).toBeTruthy();
  });

  it('renders English view with no untranslated titles or controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(mockClimateSections), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    render(
      <I18nProvider language="en">
        <ClimateExtrasPanel apiBase="http://127.0.0.1:8981" />
      </I18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Additional Climate Simulations (Exploratory)')).toBeTruthy();
    });
    expect(screen.getAllByText('Exploratory, not certification').length).toBeGreaterThan(0);

    // Section titles in English
    expect(screen.getByText('E1 Four-Fabric Sunlight Comparison')).toBeTruthy();
    expect(screen.getByText('UTCI Summer Thermal Comfort')).toBeTruthy();
    expect(screen.getByText('E3 Building Energy Use')).toBeTruthy();
    expect(screen.getByText('E4 Thermal Mass Performance')).toBeTruthy();
    expect(screen.getByText('E5 Pedestrian Wind Comfort')).toBeTruthy();

    // Founder selected label in English
    const selectedBadges = screen.getAllByText('Selected');
    expect(selectedBadges.length).toBeGreaterThan(0);

    // Verify English controls
    expect(screen.getByRole('button', { name: 'Spring Equinox (2026-03-21)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Closed-block extension' })).toBeTruthy();
    const englishE1Image = screen.getByRole('img', { name: 'Winter Solstice Sunlight Comparison (2026-12-21)' });
    expect(englishE1Image.getAttribute('src')).toContain('winter-solstice-en.png');
    const englishUtciImage = screen.getByRole('img', { name: 'Harbour grain 14:00 UTCI (Selected)' });
    expect(englishUtciImage.getAttribute('src')).toContain('harbour_grain_utci_1400-en.png');
    fireEvent.click(screen.getByRole('button', { name: 'Spring Equinox (2026-03-21)' }));
    const fallbackImage = screen.getByRole('img', { name: 'Spring Equinox Sunlight Comparison (2026-03-21)' });
    expect(fallbackImage.getAttribute('src')).toContain('e1-compare-20260321-%E6%98%A5%E5%88%86-zh.png');
    expect(screen.getAllByText('Limitations').length).toBe(5);
    expect(screen.getByText('Commander Review Note: Pedestrian Level Conversion Limitations')).toBeTruthy();
  });

  it('renders MISSING status and lists missing files when artifacts are absent', async () => {
    const missingSections = [
      {
        id: 'e1-fabric',
        title_zh: 'E1 四案日照對照',
        title_en: 'E1 Four-Fabric Sunlight Comparison',
        label_zh: '探索性，非認證',
        label_en: 'Exploratory, not certification',
        status: 'MISSING',
        missing_files: ['e1-fabric/comparison_table.csv', 'e1-fabric/e1-compare-20261221-冬至-zh.png'],
        figures: [],
        table: null,
        limitations_zh: '資料缺失說明',
        limitations_en: 'Missing data explanation',
        source_sha256: {},
      },
    ];

    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(missingSections), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );

    render(
      <I18nProvider language="zh-TW">
        <ClimateExtrasPanel apiBase="http://127.0.0.1:8981" />
      </I18nProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('MISSING')).toBeTruthy();
    });

    expect(screen.getByText('資料缺失 · 未取得此節離線產物')).toBeTruthy();
    expect(screen.getByText('缺少來源檔案：')).toBeTruthy();
    expect(screen.getByText('e1-fabric/comparison_table.csv')).toBeTruthy();
    expect(screen.getByText('e1-fabric/e1-compare-20261221-冬至-zh.png')).toBeTruthy();
  });
});
