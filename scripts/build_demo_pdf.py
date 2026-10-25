"""Offline backup demo PDF (zh): cover, platform walkthrough screenshots, W8 figures, results, limits."""
import json, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_w8_figures import get_font_path

R = Path(__file__).resolve().parents[1]; W, H = 2200, 1556
FONT = get_font_path()
def font(n): return ImageFont.truetype(FONT, n) if FONT else ImageFont.load_default()
commit = subprocess.check_output(['git', '-C', str(R), 'rev-parse', '--short', 'HEAD'], text=True).strip()
pages = []
def page(title, sub=None, image=None, lines=()):
    pg = Image.new('RGB', (W, H), (250, 250, 248)); d = ImageDraw.Draw(pg)
    d.text((80, 60), title, fill=(20, 30, 45), font=font(56))
    if sub: d.text((80, 135), sub, fill=(90, 100, 115), font=font(30))
    d.text((W - 640, H - 60), f'離線備用 demo · 版本 {commit} · {__import__('datetime').date.today().isoformat()}', fill=(140, 140, 140), font=font(24))
    y = 200
    if image:
        im = Image.open(image).convert('RGB'); im.thumbnail((W - 160, H - 300 - 40 * len(lines)))
        pg.paste(im, ((W - im.width) // 2, y)); y += im.height + 30
    for ln in lines:
        d.text((90, y), ln, fill=(40, 45, 55), font=font(32)); y += 46
    pages.append(pg)

page('Rotterdam M4H · Ariadne 都市設計平台', '七分鐘報告離線備用 demo｜選定方案：港埠線性紋理（Founder 已正式接受，2026-10-17）',
     lines=['內容：', '1. 四階段操作：理解基地 → 生成方案 → 比較檢驗 → 細修', '2. 四個紋理方案（第 7 輪定案）與空間語法對照',
            '3. 結果、方法發現與限制', '', '所有方案皆為「探索性草案（EXPLORATORY_DRAFT）」，未經 Founder 接受為正式設計。'])
S = R / 'artifacts/w8/demo/screens'; L = R / 'artifacts/w8/rehearsal/live-after-deploy'
for img, t, s in [(S/'site-zh.png', 'Understand｜基地', '基地資料、保留建築、步行／自行車／汽車三尺度空間語法'),
                  (S/'conditions-zh.png', 'Understand｜條件', '設計範圍、保留與分區（硬限制與偏好分開）'),
                  (L/'generate-zh-TW-3d-four-up.png', 'Explore｜生成：四案 3D', '港埠線性紋理、圍合街廓延伸、大型院落島、地景為圖'),
                  (L/'compare-zh-TW-2d-four-up.png', 'Test｜比較：四案平面', '同範圍、同圖例；右側為四案指標摘要'),
                  (L/'compare-zh-TW-syntax-diff.png', 'Test｜空間語法差值', '方案後減方案前（步行 800 m NAIN）'),
                  (S/'refine-zh.png', 'Refine｜細修', '編輯、重算與比較；E1 日照（草案）')]:
    if img.exists(): page(t, s, img)
F = R / 'artifacts/w8/figures/round-7-final2'
if (F/'comparison-massing.png').exists(): page('四案量體比較', '第 7 輪定案；同範圍、同比例', F/'comparison-massing.png')
for kind, label in [('site-nain-pedestrian','基地內步行整合度（NAIN）'),('site-nach-pedestrian','基地內步行選擇度（NACH）'),('site-nain-bicycle','基地內自行車整合度'),('site-nach-bicycle','基地內自行車選擇度')]:
    f = F / f'harbour_grain-{kind}.png'
    if f.exists(): page(f'選定方案 港埠線性紋理｜{label}', '只上色基地內路段；色階以基地內路段分級', f)
if (F/'comparison-site-nain-pedestrian.png').exists(): page('四案基地內步行整合度比較', '四案共用同一色階', F/'comparison-site-nain-pedestrian.png')
for fid, zh in [('harbour_grain','港埠線性紋理'),('closed_block_extension','圍合街廓延伸'),('courtyard_islands','大型院落島'),('landscape_figure','地景為圖')]:
    for kind, label in [('axonometric','等角圖'),('syntax-delta','步行語法差值')]:
        f = F / f'{fid}-{kind}.png'
        if f.exists(): page(f'{zh}｜{label}', None, f)
page('空間語法結果（NET2 第 7 輪 v3）', '百分位＝該道路在全網 NAIN 分布中的名次', lines=[
    '步行主街（整體／僅新設計段）：港埠 95.97／90.7、圍合 92.44／89.4、地景 90.37／74.9、院落 64.26／37.6',
    '  基準：Vierhavensstraat 57.34（符合）、Keileweg 87.67（優）；院落島整體過門檻是因含既有 Keileweg 段',
    '自行車主街：港埠 80.99、地景 70.45 達標（≥67.11）；圍合 64.56、院落 41.27 未達',
    '步行水岸：港埠 34.84、地景 15.99、圍合 8.07、院落 5.40，四案未達 43.46（半島末端、盡端路）',
    '新建 GFA：85.4%–94.7%（下限 85%，Founder 10-15 ASSUMED）；高度 ≤ 20 m（5 層）',
    '', '方法發現：兩個拓撲缺陷讓語法嚴重低估——交叉點端點微縫（0.5 mm–3.4 cm）與提案線和既有道路',
    '幾毫米近共線重疊。修正後港埠步行主街 27.8 → 52.6 → 95.97；設計在第 7 輪後沒有再改。'])
page('E2 輻射分析（正式執行 2026-10-16）', '夏季 6–8 月地面入射輻射；基準＝混合方案（Founder 選定），比較＝緊湊方案', lines=[
    'Honeybee-Radiance（驗證）  -1 h：409.5 → 401.5 kWh/平方公尺（-1.97%）',
    '                          0 h：411.8 → 403.8 kWh/平方公尺（-1.93%）',
    '                         +1 h：407.5 → 399.9 kWh/平方公尺（-1.87%）',
    'Ladybug（篩選）           0 h：404.1 → 395.8 kWh/平方公尺（-2.06%）',
    '',
    '緊湊方案地面受熱比混合方案低約 2%；兩種方法與 ±1 小時敏感度方向 6/6 一致。',
    '共同比較 5,901 點、146,233 平方公尺。三個決策由 Founder 以決策密語親自批准（job 7611e7e5…，validated）。'])
page('E2 輻射分析第二輪（正式，2026-10-17）', '港埠線性紋理 vs 混合方案（基準）；Founder 以決策密語接受港埠並批准計畫', lines=[
    'Honeybee-Radiance（驗證）  0 h：411.5 → 374.1 kWh/平方公尺（-9.1%）',
    'Ladybug（篩選）           0 h：404.0 → 360.0 kWh/平方公尺（-10.9%）',
    '±1 小時敏感度與兩種方法方向 6/6 一致（全部降低）；共同比較 4,932 點。',
    '',
    '港埠的建築量體為地面提供遮陰，夏季地面入射輻射明顯低於混合方案（job 2ffdd4a4…，validated）。'])
C = R / 'artifacts/w8'
for img, title, sub in [
    (C/'e1-fabric/e1-compare-20261221-冬至-zh.png', '附加氣候｜E1 四案冬至日照對照', '地景 3.22、圍合 2.79、港埠 2.15、院落 2.14 小時；含中庭與街廓內空地；三案中庭冬至僅 0.11–0.18 小時'),
    (C/'e1-fabric/e1-compare-20260321-春分-zh.png', '附加氣候｜E1 四案春分日照對照', '地景 7.22、圍合 6.74、院落 6.49、港埠 6.30 小時；四案 ≥2 小時面積比皆 ≥92%'),
    (C/'e1-fabric/e1-compare-20260621-夏至-zh.png', '附加氣候｜E1 四案夏至日照對照', '地景 8.44、圍合 8.21、院落 8.14、港埠 8.03 小時；港埠夏季自遮陰最多'),
    (C/'e1-fabric/comparison_summary_zh.png', '附加氣候｜E1 四案日照比較', '春分／夏至／冬至，含中庭與街廓內空地；地景冬至日照最多（3.22 小時）'),
    (C/'utci/harbour_grain_utci_1400.png', '附加氣候｜UTCI 夏季最熱日 14:00（港埠）', '港埠平均 UTCI 35.9 °C、非常強烈熱壓力 26.4%，四案最低；含中庭與街廓內空地；風速未含建築遮蔽'),
    (C/'e3e4-final/e3_eui_by_fabric.png', '附加氣候｜E3 建築耗能 EUI（四案全量）', '院落 63.1、港埠 93.4、圍合 100.4、地景 116.1 kWh/(平方公尺·年)；探索性，非能源認證'),
    (C/'e3e4-final/e4_harbour_mass_vs_light.png', '附加氣候｜E4 蓄熱（港埠重質 vs 輕質，全量 253 棟）', '重質構造夏季過熱少 43.5 小時、尖峰冷負荷低 260 kW（約 5.6%）'),
    (C/'e5-cfd/cfd_4winds_summary.png', '附加氣候｜E5 行人風場（OpenFOAM 粗略篩選）', '4 盛行風向；平均風速比 0.32–0.39，無強風加速區；只看趨勢')]:
    if img.exists(): page(title, sub, img)
page('限制與未完成', None, lines=[
    '・四案形態檢核仍有失敗（南碼頭立面連續、3 m 臨街退縮等）；方案皆為探索性草案。',
    '・水岸整合度四案皆未達基準；自行車主街兩案未達；院落島新設計段主街偏低。',
    '・附加氣候模擬（E1 逐案、UTCI、E3、E4、E5）皆為探索性；E3/E4 非能源認證，E5 為粗網格篩選、背風區不準。',
    '・W7 八項操作有元件／整合測試，Override 瀏覽器檢查未完成。',
    '・10 項 main 既有測試失敗（Week 4 歷史封存與 canonical PNG），不在本次範圍。',
    '・3D 模型匯出為 W9 附加項，未做；E5 細網格重跑需更多 Docker 資源。'])
out = R / 'artifacts/w8/demo/ariadne-w8-offline-demo-zh.pdf'
pages[0].save(out, save_all=True, append_images=pages[1:], resolution=150)
print(out, len(pages), 'pages')
