"""Render J11 result GeoJSON using the pre-existing system matplotlib runtime."""
import argparse
import json
import matplotlib
matplotlib.use('Agg')
# Founder 2026-10-08: plans sent to the Founder are labelled in Traditional Chinese.
from matplotlib import font_manager as _fm
for _path in ('/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/Hiragino Sans GB.ttc'):
    try:
        _fm.fontManager.addfont(_path); matplotlib.rcParams['font.family'] = _fm.FontProperties(fname=_path).get_name(); break
    except (OSError, RuntimeError):
        continue
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch
from matplotlib.lines import Line2D
p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);a=p.parse_args()
row=json.load(open(a.input));fig,ax=plt.subplots(figsize=(12,8))
site=None
frontage_labelled=False
for f in row['geometry']['features']:
 g=f['geometry'];role=f['properties']['role'];cs=g['coordinates']
 if g['type']=='Point':
  if role=='entrance':ax.scatter(cs[0],cs[1],marker='^',color='#174fa2',s=25,zorder=5)
  continue
 if g['type']=='LineString':
  if role in ('road','removed_road'):
   properties=f['properties'];origin=properties.get('origin','new');modes=properties.get('modes',[])
   color='#c0c0c0' if role=='removed_road' else '#a96738' if 'motor_vehicle' in modes else '#247d77' if 'bicycle' in modes else '#974cac'
   ax.plot([c[0] for c in cs],[c[1] for c in cs],color=color,linestyle={'retained':'-','transformed':'-.','new':':','removed':'--'}[origin],linewidth=.7 if role=='removed_road' else 3.5 if properties.get('hierarchy')=='main' else 1.5,zorder=1 if role=='removed_road' else 2)
   if properties.get('active_frontage_candidate_sides')=='both' and not frontage_labelled:
    frontage_labelled=True
    mid=cs[len(cs)//2];ax.annotate('活躍立面候選（兩側）',xy=mid,xytext=(6,6),textcoords='offset points',fontsize=5,color='#247d77')
  continue
 if g['type'] not in ('Polygon','MultiPolygon'):continue
 polygons=[cs] if g['type']=='Polygon' else cs
 for rings in polygons:
  verts=[];codes=[]
  for ring in rings:
   verts.extend(ring);codes.extend([Path.MOVETO]+[Path.LINETO]*(len(ring)-2)+[Path.CLOSEPOLY])
  ax.add_patch(PathPatch(Path(verts,codes),facecolor={'water':'#b5d5e8','retained':'#555555','new_building':'#d59b50','street_block':'#eeeeee','central_core':'#aed87b','green_band':'#c7e8a9'}.get(role,'none'),edgecolor='black' if role=='site_area' else 'none',alpha=.8,zorder=3 if role in ('retained','new_building') else 0))
  if role=='site_area':site=[c for ring in rings for c in ring]
if site:
 xs=[c[0] for c in site];ys=[c[1] for c in site];ax.set_xlim(min(xs)-20,max(xs)+20);ax.set_ylim(min(ys)-20,max(ys)+20)
ax.legend(handles=[Line2D([0],[0],color='#a96738',label='汽車／服務車道'),Line2D([0],[0],color='#247d77',label='步行＋自行車共用'),Line2D([0],[0],color='#974cac',label='僅步行'),Line2D([0],[0],color='black',linestyle='-',label='保留既有道路'),Line2D([0],[0],color='black',linestyle='-.',label='改造既有道路'),Line2D([0],[0],color='black',linestyle=':',label='新建道路'),Line2D([0],[0],color='#c0c0c0',linestyle='--',label='移除的既有道路'),Line2D([0],[0],marker='^',color='#174fa2',linestyle='',label='入口'),Line2D([0],[0],color='#aed87b',linewidth=6,label='中央公共空間／綠帶'),Line2D([0],[0],color='#247d77',linewidth=3.5,label='主軸（較寬的共用道）')],loc='upper left',fontsize=7)
ax.set_aspect('equal');_family={'radial':'向心型','axial':'軸線型','grid':'網格型','green_service':'綠廊＋服務環路型'}.get(row['id'].rsplit('-',1)[0],row['id'])
_status={'VALID':'硬性檢查通過','INVALID':'硬性檢查未通過'}.get(row['status'],row['status'])
_quality={'PASS':'幾何品質合格','WARN':'幾何品質有警示'}.get(row.get('quality_status'),'')
ax.set_title(f"{_family}（變體 {row['id'].rsplit('-',1)[-1]}）｜{_status}｜{_quality}｜草案｜座標 EPSG:28992（公尺）")
ax.set_xlabel('RD X 座標（公尺）');ax.set_ylabel('RD Y 座標（公尺）');fig.savefig(a.output,dpi=150);plt.close(fig)
