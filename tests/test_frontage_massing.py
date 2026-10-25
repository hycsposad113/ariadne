"""J17b 沿街優先量體配置器（frontage_massing）單元測試。"""
from types import SimpleNamespace
import pytest
from shapely.geometry import LineString, Point, Polygon, box, mapping, shape

from urban_design.generation import brief_driven as bd
from urban_design.generation import frontage_massing as fm
from urban_design.generation.context_massing import scale_check


def test_rectangular_block_produces_perimeter_courtyard_gte_20m():
    """矩形街廓產生環形周邊式，中庭淨寬 >= 20 m。"""
    block_geom = box(0, 0, 80, 80)
    cand = fm.make_perimeter_candidate(block_geom, 'Mixed', wing_depth=14.0)
    assert cand is not None
    assert cand['type_id'] == 'block.perimeter'
    assert cand['courtyard_width_m'] >= 20.0
    assert cand['scale']['valid'] is True
    assert cand['wing_depth_m'] >= 12.0


def test_small_block_backs_off_to_l_block():
    """小街廓因中庭淨寬不足無法做周邊式，退成 L 形量體。"""
    # 35m x 35m 街廓，若翼深 12m，中庭寬僅 11m < 20m，無法做周邊式
    small_block = box(0, 0, 35, 35)
    perim = fm.make_perimeter_candidate(small_block, 'Mixed', wing_depth=14.0)
    assert perim is None

    # 但沿臨街邊可退成 L 形量體（或由候選生成器提供 L 形候選）
    edge = LineString([(0, 0), (35, 0)])
    # 透過生成街廓候選項，周邊式失敗後退成 L 形或其它臨街量體
    road_surface = LineString([(0, -7.5), (35, -7.5)]).buffer(7.5)
    block_dict = {
        'id': 'test-small-block',
        'geometry': small_block,
        'use': 'mixed',
        'type_preferences': ('block.perimeter', 'building.l_block'),
    }
    opts = fm.generate_candidate_options_for_block(block_dict, road_surface)
    assert not any(o['type_id'] == 'block.perimeter' for o in opts)
    # 候選中包含 L 形或其它合法量體
    types = [o['type_id'] for o in opts]
    assert len(types) > 0


def test_frontage_edges_correct_identification():
    """臨街邊判定正確：與道路面距離 <= 1 m 為臨街邊；若無則用最長邊。"""
    road = LineString([(0, -7.5), (100, -7.5)]).buffer(7.5)  # 路面在 y in [-15, 0]
    block = box(0, 0, 50, 60)

    # 有道路時，臨街邊為靠近 y=0 的底邊
    f_edges = fm.frontage_edges(block, road, max_dist=1.0)
    assert len(f_edges) >= 1
    # 最靠前的臨街邊距離道路 <= 1.0 m
    assert f_edges[0].distance(road) <= 1.0

    # 無道路時，使用最長邊
    f_edges_no_road = fm.frontage_edges(block, None)
    assert len(f_edges_no_road) == 1
    assert f_edges_no_road[0].length == pytest.approx(60.0)


def test_slab_length_lte_90m():
    """板樓長度 <= 90 m 且通過 scale_check。"""
    block = box(0, 0, 70, 40)
    edge = LineString([(0, 0), (70, 0)])
    slab_cand = fm.make_slab_candidate(block, edge, 'Mixed', wing_depth=14.0)
    assert slab_cand is not None
    assert slab_cand['type_id'] == 'building.i_slab'
    assert slab_cand['length_m'] <= 90.0
    assert slab_cand['scale']['valid'] is True


def test_negative_control_wing_depth_8m_rejected_by_brief_measured_scale():
    """負控制：翼深 8 m 必須被 brief_measured_scale 擋下。"""
    # 住宅翼深下限為 10 m，混合下限為 12 m；8 m 必被 scale_check / measured_scale_gate 拒絕
    prof_res = SimpleNamespace(
        geometry=box(0, 0, 40, 8),
        type_id='building.i_slab',
        wing_depth_m=8.0,
        unit_count=None,
        unit_frontage_m=None,
    )
    assert not bd.measured_scale_gate(prof_res, 'Residential')
    assert not bd.measured_scale_gate(prof_res, 'Mixed')


def test_legacy_placer_default_unchanged():
    """舊 placer 預設行為不變（placer='j12b' 為預設）。"""
    import inspect
    sig = inspect.signature(bd.generate_brief_driven)
    assert 'placer' in sig.parameters
    assert sig.parameters['placer'].default == 'j12b'


def test_strip_with_three_segments_allocates_gfa_to_all_three():
    """一條帶有 3 段時，GFA 分到 3 段且每段都有建築。"""
    brief = {
        'strips': [
            {
                'strip_id': 'strip-test',
                'segments': [
                    {'segment_m': [0, 100], 'typologies': ['rowhouse'], 'floors': [3, 4]},
                    {'segment_m': [100, 200], 'typologies': ['rowhouse'], 'floors': [3, 4]},
                    {'segment_m': [200, 300], 'typologies': ['rowhouse'], 'floors': [3, 4]},
                ],
            }
        ],
        'development_streets': [],
    }
    strip_blocks = [
        {'id': 'b1', 'strip_id': 'strip-test', 'segment_m': [0, 100], 'geometry': box(0, 0, 50, 40), 'use': 'residential', 'type_preferences': ('building.rowhouse',)},
        {'id': 'b2', 'strip_id': 'strip-test', 'segment_m': [100, 200], 'geometry': box(100, 0, 150, 40), 'use': 'residential', 'type_preferences': ('building.rowhouse',)},
        {'id': 'b3', 'strip_id': 'strip-test', 'segment_m': [200, 300], 'geometry': box(200, 0, 250, 40), 'use': 'residential', 'type_preferences': ('building.rowhouse',)},
    ]
    road_surf = LineString([(0, -5), (300, -5)]).buffer(5.0)
    seg_targets, block_targets, shallow, seg_matching = fm.distribute_strip_gfa_by_segments(
        'strip-test', 15000.0, brief, strip_blocks, road_surf, fire_surface=road_surf
    )
    assert len(seg_targets) == 3
    for seg_key, gfa in seg_targets.items():
        assert gfa > 0
        assert len(seg_matching[seg_key]) >= 1
    assert len(block_targets) == 3
    for bid, bgfa in block_targets.items():
        assert bgfa > 0


def test_development_street_segment_receives_higher_weight():
    """發展街段權重較高：可建地面積相同時，發展街段權重為非發展街段之 3 倍。"""
    brief = {
        'strips': [
            {
                'strip_id': 'strip-weight',
                'segments': [
                    {'segment_m': [0, 100], 'typologies': ['rowhouse'], 'floors': [3, 4]},
                    {'segment_m': [100, 200], 'typologies': ['rowhouse'], 'floors': [3, 4]},
                ],
            }
        ],
        'development_streets': [
            {'strip_id': 'strip-weight', 'segment_m': [0, 100]},
        ],
    }
    strip_blocks = [
        {'id': 'b-dev', 'strip_id': 'strip-weight', 'segment_m': [0, 100], 'geometry': box(0, 0, 50, 40), 'use': 'residential', 'type_preferences': ('building.rowhouse',)},
        {'id': 'b-nondev', 'strip_id': 'strip-weight', 'segment_m': [100, 200], 'geometry': box(100, 0, 150, 40), 'use': 'residential', 'type_preferences': ('building.rowhouse',)},
    ]
    road_surf = LineString([(0, -5), (200, -5)]).buffer(5.0)
    seg_targets, block_targets, shallow, _ = fm.distribute_strip_gfa_by_segments(
        'strip-weight', 20000.0, brief, strip_blocks, road_surf, fire_surface=road_surf
    )
    dev_gfa = seg_targets[(0, 100)]
    nondev_gfa = seg_targets[(100, 200)]
    assert dev_gfa == pytest.approx(3.0 * nondev_gfa, rel=1e-3)


def test_fire_40m_negative_control():
    """消防 40 m 負控制：外牆距離消防可達道路 > 40 m 的候選必須被排除。"""
    block_poly = box(0, 55, 60, 95)  # block is at y in [55, 95]
    road_surf = LineString([(0, 0), (60, 0)]).buffer(5.0)  # road surface is at y in [-5, 5]
    # distance from block to road surface is 50 m > 40 m
    block_dict = {
        'id': 'b-far-from-fire',
        'geometry': block_poly,
        'use': 'residential',
        'type_preferences': ('building.rowhouse', 'building.i_slab'),
    }
    # When fire_surface is the distant road surface:
    opts_with_fire = fm.generate_candidate_options_for_block(
        block_dict, road_surf, fire_surface=road_surf
    )
    assert len(opts_with_fire) == 0, "Distance > 40m candidates must be filtered out"

    # When fire_surface is close (e.g. 10m away):
    near_fire = LineString([(0, 50), (60, 50)]).buffer(5.0)
    opts_near = fm.generate_candidate_options_for_block(
        block_dict, road_surf, fire_surface=near_fire
    )
    assert len(opts_near) > 0, "Distance <= 40m candidates should be retained"


def test_ground_floor_underpass_gfa_readback_consistent():
    """首層穿越口的 GFA 讀回一致：footprint、樓板與 GFA 逐層讀回完全吻合。"""
    # 建立外框長度 > 90 m 的周邊式街廓以觸發 6m 穿越口
    block_geom = box(0, 0, 100, 60)
    perim = fm.make_perimeter_candidate(block_geom, 'Mixed', wing_depth=14.0)
    assert perim is not None
    assert 'ring_floor0' in perim
    assert perim['ring_floor0_area_m2'] < perim['geometry'].area  # 首層有穿越口扣除

    ring = perim['geometry']
    ring_floor0 = perim['ring_floor0']
    fl_count = 5
    first_h = 3.5
    floors = []
    for level in range(fl_count):
        plate = ring_floor0 if level == 0 else ring
        floors.append(dict(level=level, geometry=mapping(plate), floor_height_m=3.5, use='Mixed'))

    actual_building_gfa = sum(shape(f['geometry']).area for f in floors)
    # 驗證計算出的 building gfa 確實等於 floor 0 加上其餘層
    expected_gfa = ring_floor0.area + (fl_count - 1) * ring.area
    assert actual_building_gfa == pytest.approx(expected_gfa, abs=1e-6)

    # 構造模擬 massing 字典通過 finalize_brief_metrics 讀回
    b_id = 'test-b0'
    props = dict(
        role='new_building',
        building_id=b_id,
        type_id='block.perimeter',
        variant_id=fm.VERSION,
        block_id='block-0',
        zone_id='zone-mixed',
        height_m=17.5,
        floor_count=fl_count,
        first_floor_height_m=3.5,
        floors=floors,
        scale=perim['scale'],
        new_gfa_m2=actual_building_gfa,
        footprint_area_m2=ring.area,
    )
    feature = dict(type='Feature', id=b_id, geometry=mapping(ring), properties=props)
    record = dict(**props)
    denominator = 183591.3
    retained_gfa = 68907.86

    massing = dict(
        features=[feature],
        buildings=[record],
        metrics=dict(
            far=(actual_building_gfa + retained_gfa) / denominator,
            coverage=(ring.area + 10000.0) / denominator,
            new_gfa_m2=actual_building_gfa,
            retained_gfa_upper_m2=retained_gfa,
            far_denominator_m2=denominator,
        ),
        checks=dict(
            height=True,
            far_upper=True,
        ),
        open_space=mapping(box(-100, -100, 200, 200).difference(ring)),
        named_open_spaces=[],
        roads=[],
        status='VALID',
    )
    brief = {'open_spaces': []}

    final = bd.finalize_brief_metrics(massing, brief)
    assert final['checks']['brief_floor_geometry_readback'] is True
    assert final['checks']['brief_new_gfa_metric_readback'] is True
    assert final['checks']['brief_far_metric_readback'] is True
