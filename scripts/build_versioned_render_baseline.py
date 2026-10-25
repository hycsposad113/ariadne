"""Render the retained SVG twice in separate QGIS Qt processes; exclusive output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from urban_design.rendering_provenance import (
    GateResult,
    GateStatus,
    assess,
    validate_baseline_manifest,
    HISTORICAL_NODE,
    CURRENT_GATE,
    PINNED_GATE,
    BASELINE_SCHEMA,
    validate_record,
    validate_artifact_semantics,
)
PYTHON = "/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3"
SVG = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v4/run-20260915T125400Z/map-preview-v4.svg"
VERSION = "qgis-qt-dejavu-outlines-v2"

HELPER = r'''import hashlib,json,os,platform,sys
from pathlib import Path
from PyQt5 import QtCore,QtGui,QtSvg
from PyQt5.QtWidgets import QApplication
from qgis.core import Qgis
app=QApplication(['m2-t02-render'])
import xml.etree.ElementTree as ET
fontdir=Path('/Applications/QGIS-LTR.app/Contents/Resources/python/site-packages/matplotlib-3.3.0-py3.9-macosx-10.13.0-x86_64.egg/matplotlib/mpl-data/fonts/ttf')
def ref(p):
 p=Path(p).resolve();return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size)
input_bytes=Path(sys.argv[1]).read_bytes()
actual_input=dict(sha256=hashlib.sha256(input_bytes).hexdigest(),size=len(input_bytes))
root=ET.fromstring(input_bytes)
ns='{http://www.w3.org/2000/svg}'
styles={'map-label':dict(size=12,bold=True,fill='#202427'),'legend-text':dict(size=12,bold=False,fill='#202427'),'meta':dict(size=11,bold=False,fill='#4a5054'),'mono':dict(size=11,bold=False,fill='#202427')}
fonts=[];mapping=[];text_count=0;character_count=0
for parent in list(root.iter()):
 for e in list(parent):
  if e.tag!=ns+'text':continue
  if list(e) or set(e.attrib)-{'class','fill','font-family','font-size','font-weight','id','x','y'}:raise SystemExit('BLOCKED unsupported text structure')
  text=e.text or ''
  text_count+=1;character_count+=len(text)
  cfg=styles.get(e.get('class'),dict(size=12,bold=False,fill='#202427'))
  name='DejaVuSansMono.ttf' if e.get('class')=='mono' else ('DejaVuSans-Bold.ttf' if e.get('font-weight')=='700' or cfg['bold'] else 'DejaVuSans.ttf')
  file=fontdir/name
  if file.read_bytes()[:4]!=b'\x00\x01\x00\x00':raise SystemExit('BLOCKED expected single-face TTF')
  fid=QtGui.QFontDatabase.addApplicationFont(str(file))
  if fid<0:raise SystemExit('BLOCKED registration failed')
  size=float(e.get('font-size',cfg['size']))
  raw=QtGui.QRawFont(str(file),size,QtGui.QFont.PreferNoHinting)
  if not raw.isValid():raise SystemExit('BLOCKED raw font invalid')
  glyphs=raw.glyphIndexesForString(text)
  if len(glyphs)!=len(text) or any(not g or not raw.supportsCharacter(ord(c)) for c,g in zip(text,glyphs)):raise SystemExit('BLOCKED unsupported glyph; fallback prohibited')
  identity={**ref(file),'face_index':0,'family':raw.familyName(),'style':raw.styleName(),'registered_families':QtGui.QFontDatabase.applicationFontFamilies(fid),'license':ref(fontdir/'LICENSE_DEJAVU')}
  if identity not in fonts:fonts.append(identity)
  path=QtGui.QPainterPath();x=float(e.get('x','0'));y=float(e.get('y','0'))
  advances=raw.advancesForGlyphIndexes(glyphs)
  for c,g,advance in zip(text,glyphs,advances):
   glyphpath=raw.pathForGlyph(g)
   glyphpath.translate(x,y);path.addPath(glyphpath)
   mapping.append(dict(text_index=len(mapping),codepoint=ord(c),glyph=g,font_sha256=identity['sha256'],face_index=0,pixel_size=size,x=x,y=y))
   x+=advance.x();y+=advance.y()
  pieces=[];i=0
  while i<path.elementCount():
   point=path.elementAt(i)
   if point.type==QtGui.QPainterPath.MoveToElement:pieces.append('M %.17g %.17g'%(point.x,point.y))
   elif point.type==QtGui.QPainterPath.LineToElement:pieces.append('L %.17g %.17g'%(point.x,point.y))
   elif point.type==QtGui.QPainterPath.CurveToElement:
    p1=path.elementAt(i+1);p2=path.elementAt(i+2)
    pieces.append('C %.17g %.17g %.17g %.17g %.17g %.17g'%(point.x,point.y,p1.x,p1.y,p2.x,p2.y));i+=2
   else:raise SystemExit('BLOCKED unsupported path element')
   i+=1
  attrs={'d':' '.join(pieces),'fill':e.get('fill',cfg['fill']),'fill-rule':'evenodd'}
  if e.get('class')=='map-label':attrs.update(stroke='#fff',**{'stroke-width':'3','paint-order':'stroke'})
  if e.get('id'):attrs['id']=e.get('id')
  index=list(parent).index(e);parent.remove(e);parent.insert(index,ET.Element(ns+'path',attrs))
if any(e.tag in (ns+'text',ns+'tspan',ns+'use',ns+'image') for e in root.iter()):raise SystemExit('BLOCKED remaining text or external rendering reference')
derived=Path(sys.argv[2]+'.svg');ET.ElementTree(root).write(str(derived),encoding='utf-8',xml_declaration=True)
glyph_proof=dict(status='COMPLETE_NO_FALLBACK',mapping=mapping,derived_svg=ref(derived),transformation='raw-file-face0-glyph-outline-v1',text_nodes=text_count,character_count=character_count)
image=QtGui.QImage(1240,850,QtGui.QImage.Format_ARGB32);image.fill(0xffffffff)
renderer=QtSvg.QSvgRenderer(str(derived))
if not renderer.isValid():raise SystemExit('invalid derived SVG')
painter=QtGui.QPainter(image);renderer.render(painter);painter.end()
if not image.save(sys.argv[2],'PNG'):raise SystemExit('PNG save failed')
import ctypes
lib=ctypes.CDLL(None)
lib._dyld_image_count.restype=ctypes.c_uint32
lib._dyld_get_image_name.argtypes=[ctypes.c_uint32]
lib._dyld_get_image_name.restype=ctypes.c_char_p
loaded=[]
for i in range(lib._dyld_image_count()):
 path=Path(lib._dyld_get_image_name(i).decode())
 if path.is_file():loaded.append(ref(path))
libs={name:ref(module.__file__) for name,module in [('QtCore',QtCore),('QtGui',QtGui),('QtSvg',QtSvg)]}
for name in ('QtCore','QtGui','QtSvg','qgis_core'):
 p=Path('/Applications/QGIS-LTR.app/Contents/Frameworks')/(name+'.framework')/name
 if p.is_file():libs[name+'-framework']=ref(p)
print(json.dumps(dict(actual_input=actual_input,python=sys.version,executable=ref(sys.executable),qgis=Qgis.QGIS_VERSION,qt=QtCore.qVersion(),pyqt=QtCore.PYQT_VERSION_STR,libraries=libs,loaded_libraries=loaded,os=platform.platform(),machine=platform.machine(),dpi=dict(logical=app.primaryScreen().logicalDotsPerInch(),physical=app.primaryScreen().physicalDotsPerInch(),ratio=app.primaryScreen().devicePixelRatio()),png_formats=[bytes(x).decode() for x in QtGui.QImageWriter.supportedImageFormats()],environment={k:v for k,v in os.environ.items() if k.startswith(('QT_','QGIS_','DYLD_'))},fonts=fonts,glyph_proof=glyph_proof)))
'''

def ref(path):
    data=path.read_bytes()
    return {"sha256":hashlib.sha256(data).hexdigest(),"size":len(data)}


def blocked(reason):
    return GateResult(GateStatus.BLOCKED, reason)


def capture_parent_snapshot(source, output_dir):
    """Capture one exclusive, read-only parent SVG for both render children."""
    source = Path(source)
    output_dir = Path(output_dir)
    data = source.read_bytes()
    snapshot = output_dir / "parent-snapshot.svg"
    descriptor = os.open(str(snapshot), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        snapshot.chmod(0o400)
    except BaseException:
        try:
            snapshot.rename(output_dir / "failed-parent-snapshot.svg")
        except OSError:
            pass
        raise
    return snapshot.resolve()


def build_render_command(helper, parent_snapshot, png):
    return [PYTHON, str(Path(helper).resolve()), str(Path(parent_snapshot).resolve()), str(Path(png).resolve())]


def validate_baseline_artifacts(manifest, manifest_path):
    """Bind a validated manifest to the retained files beside it."""
    valid = validate_baseline_manifest(manifest)
    if valid.status is not GateStatus.PASS:
        return valid
    directory = Path(manifest_path).resolve().parent
    try:
        parent_identity = ref(directory / "parent-snapshot.svg")
        helper_identity = ref(directory / "qt-render.py")
        if parent_identity != manifest["parent_snapshot"]:
            return blocked("pinned parent snapshot identity drift")
        for index, record in enumerate(manifest["records"]):
            png_identity = ref(directory / ("render-%d.png" % index))
            svg_identity = ref(directory / ("render-%d.png.svg" % index))
            if png_identity != record["png"]:
                return blocked("pinned render-%d PNG identity drift" % index)
            if svg_identity != record["glyph_proof"]["derived_svg"]:
                return blocked("pinned render-%d derived SVG identity drift" % index)
            if helper_identity != record["helper"]:
                return blocked("pinned renderer helper identity drift")
            semantics = validate_artifact_semantics(record, (directory / "parent-snapshot.svg").read_bytes(), (directory / ("render-%d.png.svg" % index)).read_bytes())
            if semantics.status is not GateStatus.PASS:
                return semantics
    except (OSError,RuntimeError,ValueError) as exc:
        return blocked("pinned renderer artifact missing or unreadable: %s" % exc)
    return GateResult(GateStatus.PASS, "both pinned artifacts and source/font/derived-node semantics verified; Qt outline geometry NOT_INDEPENDENTLY_RECOMPUTED")


def validate_runtime_files(record):
    """Verify reported runtime, font, and licence identities against local bytes."""
    valid = validate_record(record)
    if valid.status is not GateStatus.PASS:
        return valid
    runtime = record["runtime"]
    identities = [runtime["executable"]]
    identities.extend(runtime["libraries"].values())
    identities.extend(runtime["loaded_libraries"])
    for font in record["fonts"]:
        identities.append({key: font[key] for key in ("path", "sha256", "size")})
        identities.append(font["license"])
    checked = set()
    try:
        for identity in identities:
            path = Path(identity["path"]).resolve(strict=True)
            if not path.is_file():
                return blocked("runtime identity path is not a regular file: %s" % path)
            observed = ref(path)
            expected = {"sha256": identity["sha256"], "size": identity["size"]}
            if observed != expected:
                return blocked("runtime/font/license file identity drift: %s" % path)
            checked.add(str(path))
    except (OSError,RuntimeError,ValueError) as exc:
        return blocked("runtime/font/license identity unreadable: %s" % exc)
    return GateResult(GateStatus.PASS, "verified %d runtime, font, and licence file identities" % len(checked))


def load_baseline(path, verify_runtime=False):
    """Read and validate a pinned baseline without changing its bytes."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, blocked("pinned baseline unavailable: %s" % exc)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return None, blocked("pinned baseline JSON invalid; sha256=%s; original left unchanged: %s" % (digest, exc))
    valid = validate_baseline_manifest(manifest)
    if valid.status is not GateStatus.PASS and valid.reason.startswith("migration diagnostic:"):
        return manifest, blocked("%s; path=%s; sha256=%s; original left unchanged" % (valid.reason, path, digest))
    if valid.status is not GateStatus.PASS:
        return manifest, valid
    artifacts = validate_baseline_artifacts(manifest, path)
    if artifacts.status is not GateStatus.PASS:
        return manifest, artifacts
    if verify_runtime:
        for record in manifest["records"]:
            files = validate_runtime_files(record)
            if files.status is not GateStatus.PASS:
                return manifest, files
            for name, identity in record["code"].items():
                try:
                    if ref(ROOT / name) != identity:
                        return manifest, blocked("renderer source code identity drift: " + name)
                except OSError as exc:
                    return manifest, blocked("renderer source code unreadable: %s" % exc)
        return manifest, GateResult(GateStatus.PASS, "artifact semantics and local runtime/source bytes verified; execution replay NOT_VERIFIED")
    artifacts = GateResult(GateStatus.PASS, artifacts.reason + "; runtime/source bytes NOT_VERIFIED; execution replay NOT_VERIFIED")
    return manifest, artifacts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--baseline",type=Path,help="Previously pinned manifest; never modified")
    args=parser.parse_args()
    args.output.mkdir(mode=0o700,parents=False,exist_ok=False)
    args.output=args.output.resolve()
    helper=args.output/"qt-render.py"
    with helper.open("x",encoding="utf-8") as stream:
        stream.write(HELPER)
    source_before=ref(SVG)
    snapshot=capture_parent_snapshot(SVG,args.output)
    parent=ref(snapshot)
    failures=[]
    if source_before!=parent:
        failures.append("source SVG changed while its immutable snapshot was captured")
    code_paths=(Path(__file__).resolve(),ROOT/"src/urban_design/rendering_provenance.py",ROOT/"scripts/create_site_proposal_rotterdam.py")
    try:
        code={str(path.relative_to(ROOT)):ref(path) for path in code_paths}
    except OSError as exc:
        code={}
        failures.append("renderer source code identity unavailable: %s" % exc)
    records=[]
    input_mismatch=False
    for index in range(2):
        png=args.output/("render-%d.png"%index)
        command=build_render_command(helper,snapshot,png)
        try:
            result=subprocess.run(command,capture_output=True,text=True,timeout=90,env={**os.environ,"QT_QPA_PLATFORM":"offscreen"})
        except (OSError,subprocess.TimeoutExpired,UnicodeDecodeError) as exc:
            failures.append("Qt render-%d could not complete: %s" % (index,exc))
            continue
        (args.output/("stderr-%d.txt"%index)).write_text(result.stderr,encoding="utf-8")
        (args.output/("stdout-%d.json"%index)).write_text(result.stdout,encoding="utf-8")
        if result.returncode:
            failures.append("Qt render-%d failed with exit %d" % (index,result.returncode))
            continue
        try:
            payload=json.loads(result.stdout)
            if not isinstance(payload,Mapping):
                raise ValueError("runtime evidence root is not a mapping")
            runtime=dict(payload)
            actual_input=runtime.pop("actual_input")
            if actual_input != parent:
                input_mismatch=True
                raise ValueError("actual parsed input differs from captured parent identity: %s" % actual_input)
            fonts=runtime.pop("fonts")
            proof=dict(runtime.pop("glyph_proof"))
            derived=dict(proof["derived_svg"])
            if Path(derived["path"]).resolve()!=Path(str(png)+".svg").resolve():
                raise ValueError("derived SVG path does not match this render output")
            derived.pop("path")
            proof["derived_svg"]=derived
            record=dict(version=VERSION,parent_svg=parent,actual_input=actual_input,png=ref(png),runtime=runtime,fonts=fonts,glyph_proof=proof,command=command,helper=ref(helper),code=code)
            gate=assess(record,record)
            if gate.status is not GateStatus.PASS:
                raise ValueError(gate.reason)
            files_gate=validate_runtime_files(record)
            if files_gate.status is not GateStatus.PASS:
                raise ValueError(files_gate.reason)
            records.append(record)
        except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OSError) as exc:
            failures.append("Qt render-%d evidence BLOCKED: %s" % (index,exc))
    if ref(snapshot)!=parent:
        failures.append("captured parent SVG snapshot changed during rendering")
    if ref(SVG)!=source_before:
        failures.append("source SVG changed during rendering")
    if code:
        try:
            if any(ref(path)!={"sha256":code[str(path.relative_to(ROOT))]["sha256"],"size":code[str(path.relative_to(ROOT))]["size"]} for path in code_paths):
                failures.append("renderer source code changed during rendering")
        except OSError as exc:
            failures.append("renderer source code could not be rechecked: %s" % exc)
    if len(records)==2:
        gate=assess(records[0],records[1])
        byte_equivalence=(args.output/"render-0.png").read_bytes()==(args.output/"render-1.png").read_bytes()
        if byte_equivalence!=(records[0]["png"]==records[1]["png"]):
            gate=blocked("PNG byte comparison disagrees with recorded identities")
        if failures:
            gate=blocked("; ".join(failures))
    else:
        byte_equivalence=False
        gate=blocked("; ".join(failures) if failures else "two valid Qt render records were not produced")
    if input_mismatch:
        gate=GateResult(GateStatus.FAIL,"; ".join(failures))
    migration_diagnostics=[]
    pinned_gate=GateResult(GateStatus.NOT_REQUESTED,"no pinned baseline supplied")
    if args.baseline:
        baseline,pinned_gate=load_baseline(args.baseline,verify_runtime=True)
        if isinstance(baseline,Mapping):
            prior_diagnostics=baseline.get("migration_diagnostics")
            if type(prior_diagnostics) is list:
                migration_diagnostics.extend(item for item in prior_diagnostics if type(item) is str and item.strip())
        if pinned_gate.status is GateStatus.BLOCKED and pinned_gate.reason.startswith("migration diagnostic:"):
            migration_diagnostics.append(pinned_gate.reason)
        if pinned_gate.status is GateStatus.PASS:
            if len(records)!=2:
                pinned_gate=blocked("current two-render evidence unavailable for pinned replay")
            else:
                pinned_gate=assess(baseline["records"][0],records[0])
    manifest=dict(
        schema_version=BASELINE_SCHEMA,
        parent_snapshot=parent,
        records=records,
        byte_equivalence=byte_equivalence,
        gates={
            HISTORICAL_NODE:{"status":"HISTORICAL_BLOCKED","policy":"RENDER-C01","original_assertions":"UNCHANGED"},
            CURRENT_GATE:{"status":gate.status.value,"reason":gate.reason},
            PINNED_GATE:{"status":pinned_gate.status.value,"reason":pinned_gate.reason},
        },
        release_acceptance=False,
        migration_diagnostics=migration_diagnostics,
    )
    manifest_path=args.output/"manifest.json"
    manifest_validation=validate_baseline_manifest(manifest)
    if manifest_validation.status is GateStatus.PASS:
        artifact_validation=validate_baseline_artifacts(manifest,manifest_path)
        if artifact_validation.status is not GateStatus.PASS:
            failures.append(artifact_validation.reason)
            gate=blocked(artifact_validation.reason)
            manifest["gates"][CURRENT_GATE]={"status":gate.status.value,"reason":gate.reason}
            manifest_validation=validate_baseline_manifest(manifest)
    with manifest_path.open("x",encoding="utf-8") as stream:
        stream.write(json.dumps(manifest,indent=2)+"\n")
    try:
        written_manifest=json.loads(manifest_path.read_bytes())
        manifest_validation=validate_baseline_manifest(written_manifest)
        if manifest_validation.status is GateStatus.PASS:
            artifact_validation=validate_baseline_artifacts(written_manifest,manifest_path)
            if artifact_validation.status is not GateStatus.PASS:
                failures.append(artifact_validation.reason)
                manifest_validation=blocked(artifact_validation.reason)
    except (OSError,UnicodeDecodeError,ValueError,RecursionError) as exc:
        failures.append("written manifest could not be verified: %s" % exc)
        manifest_validation=blocked(failures[-1])
    report={"gates":manifest["gates"],"manifest_validation":manifest_validation.status.value,"manifest_reason":manifest_validation.reason,"failures":failures}
    print(json.dumps(report))
    return 0 if gate.status is GateStatus.PASS and pinned_gate.status in (GateStatus.PASS,GateStatus.NOT_REQUESTED) and not failures else 2

if __name__=='__main__':raise SystemExit(main())
