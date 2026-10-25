"""Render NET1 projected geometry, without inventing basemap or traffic data."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import shape


def render(folder):
    font=ImageFont.truetype('/System/Library/Fonts/STHeiti Medium.ttc',18)
    for file in folder.glob('*-plan.json'):
        plan=json.loads(file.read_text());site=shape(plan['site']);bounds=site.buffer(160).bounds
        w,h=1400,950;scale=min((w-40)/(bounds[2]-bounds[0]),(h-100)/(bounds[3]-bounds[1]))
        image=Image.new('RGB',(w,h),'white');draw=ImageDraw.Draw(image)
        def xy(c):return (20+(c[0]-bounds[0])*scale,h-50-(c[1]-bounds[1])*scale)
        def geometry(g,color,width=1,fill=False):
            if hasattr(g,'geoms'):
                for part in g.geoms:geometry(part,color,width,fill)
            elif g.geom_type=='Polygon':draw.polygon([xy(c) for c in g.exterior.coords],fill=color if fill else None,outline=color)
            elif g.geom_type=='LineString':draw.line([xy(c) for c in g.coords],fill=color,width=width)
        geometry(site,'#eee',fill=True);geometry(shape(plan['water']),'#c5e4f3',fill=True)
        for row in plan['buildings']:geometry(shape(row['geometry']),'#777',fill=True)
        for row in plan['roads']:geometry(shape(row['geometry']),'#aaa',2)
        for row in plan['net1']['added_roads']:
            geometry(shape(row['geometry']),'#dd981a' if row['properties']['role']=='canal_bridge' else '#c03832',4)
        draw.text((20,10),f"NET1 第 {plan['net1']['round']} 輪｜{plan['fabric_id']}｜EPSG:28992 m",font=font,fill='black')
        draw.text((20,38),'紅：新增接點／路徑；黃：ASSUMED_BRIDGE；灰：原路網／量體。設計未接受，高差與通行權未驗證。',font=font,fill='black')
        destination=folder/(file.stem.removesuffix('-plan')+'-net1-network-zh.png')
        if destination.exists():raise ValueError('Render exists; no overwrite')
        image.save(destination)
        if destination.stat().st_size>=5_000_000:raise ValueError('Image exceeds 5 MB')
        print(destination,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    render(parser.parse_args().root)
