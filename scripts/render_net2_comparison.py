"""Plot actual NET2 geometries in common RD coordinates; no basemap inference."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape

NAMES = {'harbour_grain':'港埠長條紋理','closed_block_extension':'圍合周邊街廓','courtyard_islands':'院落大島','landscape_figure':'地景綠軸'}
FONT='/System/Library/Fonts/STHeiti Medium.ttc'

def render_panel(image, plan, bounds, frame, title):
    draw=ImageDraw.Draw(image); x,y,w,h=frame
    font=ImageFont.truetype(FONT,22); small=ImageFont.truetype(FONT,17)
    scale=min((w-60)/(bounds[2]-bounds[0]),(h-145)/(bounds[3]-bounds[1]))
    dx=x+(w-(bounds[2]-bounds[0])*scale)/2
    dy=y+85+(h-145-(bounds[3]-bounds[1])*scale)/2
    def xy(c):return (dx+(c[0]-bounds[0])*scale,dy+(bounds[3]-c[1])*scale)
    def plot(g,color,width=1,fill=None):
        if g.is_empty:return
        if hasattr(g,'geoms'):
            for q in g.geoms:plot(q,color,width,fill)
        elif g.geom_type=='Polygon':
            draw.polygon([xy(c) for c in g.exterior.coords],fill=fill,outline=color,width=width)
            if fill:
                for ring in g.interiors:draw.polygon([xy(c) for c in ring.coords],fill='#faf9f5')
        elif g.geom_type in ('LineString','LinearRing'):draw.line([xy(c) for c in g.coords],fill=color,width=width)
    draw.rectangle((x,y,x+w,y+h),outline='#d6d4ce',width=2)
    draw.text((x+20,y+15),title,font=font,fill='#202e30')
    plot(shape(plan['site']),'#606e70',2,'#faf9f5')
    plot(shape(plan['water']),'#a4c7d3',1,'#cde4eb')
    for r in plan.get('land_use',[]):
        category=r['properties'].get('category')
        if category in ('parks','waterfront'):
            plot(shape(r['geometry']),'#b6cba9',1,'#dbe7ce' if category=='parks' else '#c3dbc9')
    for r in plan.get('blocks',[]):plot(shape(r['geometry']),'#b4b2a7',1)
    for r in plan['buildings']:
        retained=r['properties'].get('retained',False)
        plot(shape(r['geometry']),'#566368' if retained else '#8d8173',1,'#566368' if retained else '#b3a38f')
    for r in plan['roads']:
        p=r['properties'];role=p.get('role','')
        if role=='primary_street':continue
        color='#46877c' if role in ('waterfront_path','waterfront_detour') else '#c09440' if p.get('assumption')=='ASSUMED_BRIDGE' else '#8a9ba0'
        plot(shape(r['geometry']),color,3 if role in ('waterfront_path','canal_bridge') else 1)
    for r in plan['roads']:
        if r['properties'].get('role')=='primary_street':plot(shape(r['geometry']),'#bd453b',5)
    draw.text((x+w-50,y+55),'北↑',font=small,fill='#202e30')
    sx=x+25;sy=y+h-36
    draw.line((sx,sy,sx+100*scale,sy),fill='#202e30',width=3)
    draw.text((sx,sy+3),'100 公尺',font=small,fill='#202e30')
    gfa=plan.get('metrics',{}).get('new_gfa_m2')
    summary=f'新建樓地板：{gfa:,.0f} m²（{gfa/146873*100:.2f}%）' if gfa is not None else '新建樓地板：未計算'
    draw.text((x+230,y+h-36),summary,font=small,fill='#202e30')

def save(image,path):
    if path.exists():raise ValueError('Preserve prior render: '+str(path))
    image.save(path)
    if path.stat().st_size>=5_000_000:raise ValueError('Render exceeds 5,000,000 bytes')

def run(root, before, output, label):
    output.mkdir(parents=True,exist_ok=True)
    for path in sorted(root.glob('*-plan.json')):
        fabric=path.stem.removesuffix('-plan');plan=json.loads(path.read_text());old=json.loads((before/path.name).read_text())
        bounds=shape(plan['site']).buffer(70).bounds
        canvas=Image.new('RGB',(2400,1240),'white');draw=ImageDraw.Draw(canvas)
        draw.text((25,15),f'NET2 街廓調整前後｜{NAMES[fabric]}｜{label}',font=ImageFont.truetype(FONT,29),fill='#202e30')
        render_panel(canvas,old,bounds,(20,75,1170,1050),'調整前：NET1／run-6')
        render_panel(canvas,plan,bounds,(1210,75,1170,1050),'調整後：NET2／'+label)
        draw.text((25,1145),'紅：主街　綠：水岸步行路徑　黃：假設橋梁　深灰：保留建築　棕：新量體　細框：街廓',font=ImageFont.truetype(FONT,23),fill='#202e30')
        draw.text((25,1183),'EPSG:28992／公尺；同一視域與比例。設計尚未接受；圖示不證明通行權、高差或橋梁結構。',font=ImageFont.truetype(FONT,21),fill='#596568')
        save(canvas,output/(fabric+'-before-after-zh.png'))
        single=Image.new('RGB',(1600,1100),'white');render_panel(single,plan,bounds,(10,10,1580,1070),NAMES[fabric]+'｜NET2 '+label)
        save(single,root/(fabric+'-net2-network-zh.png'))
        print(fabric,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--before',type=Path,default=Path('artifacts/fab1/run-6'));p.add_argument('--output',required=True,type=Path);p.add_argument('--label',default='第1輪')
    a=p.parse_args();run(a.root,a.before,a.output,a.label)
