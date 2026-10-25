"""Fail-closed versioned renderer evidence; never qualifies historical bytes."""
from dataclasses import dataclass
from enum import Enum
import math
import re
import hashlib
import struct
from pathlib import Path
import xml.etree.ElementTree as ET
from collections.abc import Mapping

class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_REQUESTED = "NOT_REQUESTED"

@dataclass(frozen=True)
class GateResult:
    status: GateStatus
    reason: str

REQUIRED = ("version", "parent_svg", "png", "runtime", "fonts", "glyph_proof")
RUNTIME_REQUIRED = ("python", "executable", "qgis", "qt", "pyqt", "libraries", "loaded_libraries", "os", "machine", "dpi", "png_formats", "environment")
HISTORICAL_NODE = "tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema"
RECORD_KEYS = frozenset(("version", "parent_svg", "actual_input", "png", "runtime", "fonts", "glyph_proof", "command", "helper", "code"))
BASELINE_SCHEMA = "renderer-gates-v2"
BASELINE_KEYS = frozenset(("schema_version", "parent_snapshot", "records", "byte_equivalence", "gates", "release_acceptance", "migration_diagnostics"))
CURRENT_GATE = "CURRENT_VERSION_REPRODUCIBILITY"
PINNED_GATE = "PINNED_BASELINE_REPLAY"
CODE_REQUIRED = frozenset(("scripts/build_versioned_render_baseline.py", "src/urban_design/rendering_provenance.py", "scripts/create_site_proposal_rotterdam.py"))
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
DEJAVU_LICENSE_SHA256 = "d75938dec098f06f0ac3c00853065d94f020be1c3c62ef1dc2975ba15b4d9b0e"
# Exact bundled assets used by qgis-qt-dejavu-outlines-v2 and its retained licence.
# A modified font cannot inherit that licence assertion from a filename alone.
DEJAVU_FONT_SHA256 = {
    "DejaVuSans-Bold.ttf": "b184b89e3c1075f22f6b71575b6fc20d4972b3cfd3b23322ca6fd596dcaef167",
    "DejaVuSans.ttf": "3fdf69cabf06049ea70a00b5919340e2ce1e6d02b0cc3c4b44fb6801bd1e0d22",
    "DejaVuSansMono.ttf": "602ec86b8948cfcd956482fe64f94c36c867770149ef2f791d4613f443bcecb3",
}


def _result(status, reason):
    return GateResult(status, reason)


def _nonempty_text(value):
    return type(value) is str and bool(value.strip())


def _valid_identity(value, with_path=False):
    fields = {"sha256", "size"}
    if with_path:
        fields.add("path")
    if not isinstance(value, Mapping) or set(value) != fields:
        return False
    if type(value.get("sha256")) is not str or not _SHA256.fullmatch(value["sha256"]):
        return False
    if type(value.get("size")) is not int or value["size"] <= 0:
        return False
    return not with_path or _nonempty_text(value.get("path"))


def _finite_number(value, positive=False):
    if type(value) not in (int, float):
        return False
    try:
        if not math.isfinite(value):
            return False
    except (OverflowError, ValueError):
        return False
    return not positive or value > 0


def _validate_runtime(runtime):
    if not isinstance(runtime, Mapping) or set(runtime) != set(RUNTIME_REQUIRED):
        return "incomplete runtime fingerprint schema"
    for key in ("python", "qgis", "qt", "pyqt", "os", "machine"):
        if not _nonempty_text(runtime.get(key)):
            return "empty runtime identity: " + key
    if runtime["qt"] != "5.15.2" or runtime["qgis"] != "3.40.5-Bratislava":
        return "unsupported runtime version"
    if not _valid_identity(runtime.get("executable"), with_path=True):
        return "invalid runtime executable binary identity"
    libraries = runtime.get("libraries")
    required_libraries = {"QtCore", "QtGui", "QtSvg"}
    if not isinstance(libraries, Mapping) or not required_libraries.issubset(libraries):
        return "required Qt runtime library identities unavailable"
    for name, identity in libraries.items():
        if not _nonempty_text(name) or not _valid_identity(identity, with_path=True):
            return "invalid runtime library binary identity"
    loaded = runtime.get("loaded_libraries")
    if type(loaded) is not list or not loaded or any(not _valid_identity(item, with_path=True) for item in loaded):
        return "invalid loaded runtime binary identities"
    dpi = runtime.get("dpi")
    if not isinstance(dpi, Mapping) or set(dpi) != {"logical", "physical", "ratio"}:
        return "invalid runtime DPI schema"
    if any(not _finite_number(dpi[key], positive=True) for key in ("logical", "physical", "ratio")):
        return "invalid runtime DPI value"
    formats = runtime.get("png_formats")
    if type(formats) is not list or not formats or any(not _nonempty_text(item) for item in formats):
        return "invalid runtime PNG format list"
    if "png" not in [item.casefold() for item in formats]:
        return "PNG output format unavailable"
    environment = runtime.get("environment")
    if not isinstance(environment, Mapping) or any(not _nonempty_text(key) or type(value) is not str for key, value in environment.items()):
        return "invalid runtime environment fingerprint"
    return None


def _validate_fonts(fonts):
    if type(fonts) is not list or not fonts:
        return "effective font identities unavailable"
    for font in fonts:
        fields = {"path", "sha256", "size", "face_index", "family", "style", "registered_families", "license"}
        if not isinstance(font, Mapping) or set(font) != fields:
            return "invalid effective font schema"
        if not _valid_identity({key: font[key] for key in ("path", "sha256", "size")}, with_path=True):
            return "invalid effective font binary identity"
        if type(font.get("face_index")) is not int or font["face_index"] != 0:
            return "only exact integer font face index zero is supported"
        if not _nonempty_text(font.get("family")) or not _nonempty_text(font.get("style")):
            return "effective font face identity unavailable"
        families = font.get("registered_families")
        if type(families) is not list or not families or any(not _nonempty_text(name) for name in families):
            return "registered font family identity unavailable"
        if font["family"] not in families:
            return "raw font family does not match registered font identity"
        if not _valid_identity(font.get("license"), with_path=True):
            return "font license file identity unavailable"
    return None


def _validate_glyph_proof(proof, fonts):
    fields = {"status", "mapping", "character_count", "text_nodes", "transformation", "derived_svg"}
    if not isinstance(proof, Mapping) or set(proof) != fields:
        return "invalid glyph proof schema"
    if proof.get("status") != "COMPLETE_NO_FALLBACK" or proof.get("transformation") != "raw-file-face0-glyph-outline-v1":
        return "missing or unsupported glyph proof"
    if type(proof.get("character_count")) is not int or proof["character_count"] <= 0:
        return "invalid glyph character count"
    if type(proof.get("text_nodes")) is not int or proof["text_nodes"] <= 0:
        return "invalid SVG text node count"
    mapping = proof.get("mapping")
    if type(mapping) is not list or not mapping or len(mapping) != proof["character_count"]:
        return "incomplete text glyph coverage"
    if not _valid_identity(proof.get("derived_svg")):
        return "invalid derived SVG artifact identity"
    identities = {(font["sha256"], font["face_index"]) for font in fonts}
    mapping_fields = {"text_index", "codepoint", "glyph", "font_sha256", "face_index", "pixel_size", "x", "y"}
    for index, glyph in enumerate(mapping):
        if not isinstance(glyph, Mapping) or set(glyph) != mapping_fields:
            return "invalid glyph mapping schema"
        if type(glyph.get("text_index")) is not int or glyph["text_index"] != index:
            return "glyph mapping indexes are not contiguous"
        codepoint = glyph.get("codepoint")
        if type(codepoint) is not int or not (0 <= codepoint <= 0x10FFFF) or 0xD800 <= codepoint <= 0xDFFF:
            return "glyph mapping contains an invalid Unicode scalar"
        if type(glyph.get("glyph")) is not int or glyph["glyph"] <= 0:
            return "glyph mapping contains an invalid glyph identifier"
        if type(glyph.get("face_index")) is not int or glyph["face_index"] != 0:
            return "glyph mapping does not use exact integer face zero"
        if type(glyph.get("font_sha256")) is not str or not _SHA256.fullmatch(glyph["font_sha256"]) or (glyph["font_sha256"], glyph["face_index"]) not in identities:
            return "unsupported glyph or unproven fallback identity"
        if not _finite_number(glyph.get("pixel_size"), positive=True):
            return "glyph mapping has invalid font size"
        if not _finite_number(glyph.get("x")) or not _finite_number(glyph.get("y")):
            return "glyph mapping has invalid position"
    return None


def validate_record(evidence, output_index=None):
    if not isinstance(evidence, Mapping) or set(evidence) != RECORD_KEYS:
        return _result(GateStatus.BLOCKED, "invalid renderer record root or field set")
    if not _nonempty_text(evidence.get("version")):
        return _result(GateStatus.BLOCKED, "missing renderer version identity")
    for key in ("parent_svg", "actual_input", "png"):
        if not _valid_identity(evidence.get(key)):
            return _result(GateStatus.BLOCKED, "invalid artifact identity: " + key)
    if evidence["actual_input"] != evidence["parent_svg"]:
        return _result(GateStatus.FAIL, "actual parsed input differs from captured parent identity")
    error = _validate_runtime(evidence.get("runtime"))
    if error:
        return _result(GateStatus.BLOCKED, error)
    error = _validate_fonts(evidence.get("fonts"))
    if error:
        return _result(GateStatus.BLOCKED, error)
    error = _validate_glyph_proof(evidence.get("glyph_proof"), evidence["fonts"])
    if error:
        return _result(GateStatus.BLOCKED, error)
    if type(evidence.get("command")) is not list or len(evidence["command"]) != 4 or any(not _nonempty_text(arg) for arg in evidence["command"]):
        return _result(GateStatus.BLOCKED, "invalid renderer command record")
    if evidence["command"][1].rsplit("/", 1)[-1] != "qt-render.py":
        return _result(GateStatus.BLOCKED, "renderer helper command identity mismatch")
    if output_index is not None and evidence["command"][3].rsplit("/", 1)[-1] != "render-%d.png" % output_index:
        return _result(GateStatus.BLOCKED, "renderer output command identity mismatch")
    if not _valid_identity(evidence.get("helper")):
        return _result(GateStatus.BLOCKED, "invalid renderer helper identity")
    code = evidence.get("code")
    if not isinstance(code, Mapping) or set(code) != CODE_REQUIRED:
        return _result(GateStatus.BLOCKED, "renderer source code identities unavailable")
    for name, identity in code.items():
        if not _nonempty_text(name) or not _valid_identity(identity):
            return _result(GateStatus.BLOCKED, "invalid renderer source code identity")
    return _result(GateStatus.PASS, "renderer record schema valid")


def assess(expected, observed):
    for evidence in (expected, observed):
        valid = validate_record(evidence)
        if valid.status is not GateStatus.PASS:
            return valid
    compared = ("version", "parent_svg", "actual_input", "png", "runtime", "fonts", "glyph_proof", "helper", "code")
    if any(expected[key] != observed[key] for key in compared):
        return _result(GateStatus.FAIL, "version/input/output/runtime/font/code/helper drift")
    return _result(GateStatus.PASS, "exact bytes and fingerprint reproduced")


def validate_baseline_manifest(manifest):
    if not isinstance(manifest, Mapping):
        return _result(GateStatus.BLOCKED, "invalid renderer baseline manifest root")
    schema = manifest.get("schema_version")
    if schema != BASELINE_SCHEMA:
        return _result(GateStatus.BLOCKED, "migration diagnostic: unsupported baseline schema %r; expected %s" % (schema, BASELINE_SCHEMA))
    if set(manifest) != BASELINE_KEYS:
        return _result(GateStatus.BLOCKED, "invalid renderer baseline manifest field set")
    records = manifest.get("records")
    if type(records) is not list or len(records) != 2:
        return _result(GateStatus.BLOCKED, "renderer baseline requires exactly two render records")
    if not _valid_identity(manifest.get("parent_snapshot")):
        return _result(GateStatus.BLOCKED, "invalid captured parent SVG identity")
    for index, record in enumerate(records):
        valid = validate_record(record, output_index=index)
        if valid.status is not GateStatus.PASS:
            return valid
        if record["parent_svg"] != manifest["parent_snapshot"]:
            return _result(GateStatus.BLOCKED, "render record is not bound to the captured parent SVG")
    current = assess(records[0], records[1])
    pngs_equal = records[0]["png"] == records[1]["png"]
    if type(manifest.get("byte_equivalence")) is not bool or manifest["byte_equivalence"] != pngs_equal:
        return _result(GateStatus.BLOCKED, "byte equivalence flag does not match both PNG identities")
    gates = manifest.get("gates")
    expected_gate_keys = {HISTORICAL_NODE, CURRENT_GATE, PINNED_GATE}
    if not isinstance(gates, Mapping) or set(gates) != expected_gate_keys:
        return _result(GateStatus.BLOCKED, "invalid renderer baseline gate schema")
    if gates.get(HISTORICAL_NODE) != {"status": "HISTORICAL_BLOCKED", "policy": "RENDER-C01", "original_assertions": "UNCHANGED"}:
        return _result(GateStatus.BLOCKED, "historical strict PNG gate metadata changed")
    current_gate = gates.get(CURRENT_GATE)
    if not isinstance(current_gate, Mapping) or set(current_gate) != {"status", "reason"}:
        return _result(GateStatus.BLOCKED, "invalid current reproducibility gate schema")
    if current_gate.get("status") != current.status.value or current_gate.get("reason") != current.reason:
        return _result(GateStatus.BLOCKED, "current reproducibility gate disagrees with its two records")
    pinned_gate = gates.get(PINNED_GATE)
    if not isinstance(pinned_gate, Mapping) or set(pinned_gate) != {"status", "reason"}:
        return _result(GateStatus.BLOCKED, "invalid pinned replay gate schema")
    if pinned_gate.get("status") not in ("PASS", "FAIL", "BLOCKED", "NOT_REQUESTED") or not _nonempty_text(pinned_gate.get("reason")):
        return _result(GateStatus.BLOCKED, "invalid pinned replay gate state")
    if type(manifest.get("release_acceptance")) is not bool or manifest["release_acceptance"] is not False:
        return _result(GateStatus.BLOCKED, "release acceptance must remain false")
    diagnostics = manifest.get("migration_diagnostics")
    if type(diagnostics) is not list or any(not _nonempty_text(item) for item in diagnostics):
        return _result(GateStatus.BLOCKED, "invalid renderer migration diagnostics")
    return current


def _file_bytes(identity):
    data = Path(identity["path"]).read_bytes()
    if len(data) != identity["size"] or hashlib.sha256(data).hexdigest() != identity["sha256"]:
        raise ValueError("font/license binary identity drift")
    return data


def parse_ttf(data):
    """Bounded, single-face SFNT name/maxp/Unicode cmap 4 and 12 parser.

    No Qt or installed font database is used to validate the recorded mapping.
    Unsupported or ambiguous Unicode mappings fail closed.
    """
    def unpack(fmt, buffer, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(buffer):
            raise ValueError("TTF field outside table bounds")
        return struct.unpack_from(fmt, buffer, offset)

    if data[:4] != b"\x00\x01\x00\x00":
        raise ValueError("expected single-face TrueType font")
    count = unpack(">H", data, 4)[0]
    tables = {}
    for index in range(count):
        tag, _, start, length = unpack(">4sIII", data, 12 + 16 * index)
        if tag in tables or start < 12 + 16 * count or start + length > len(data):
            raise ValueError("invalid TTF table directory")
        tables[tag] = data[start:start + length]
    maximum = tables[b"maxp"]
    if maximum[:4] != b"\x00\x01\x00\x00":
        raise ValueError("unsupported TrueType maxp version")
    glyph_count = unpack(">H", maximum, 4)[0]
    if not glyph_count:
        raise ValueError("empty glyph table")
    names = tables[b"name"]
    name_format, count, string_start = unpack(">HHH", names, 0)
    if name_format != 0 or string_start < 6 + count * 12:
        raise ValueError("unsupported or invalid TTF name table")
    metadata = {}
    for index in range(count):
        platform, encoding, language, name_id, length, offset = unpack(">HHHHHH", names, 6 + index * 12)
        if string_start + offset + length > len(names):
            raise ValueError("TTF name string outside table")
        if platform == 3 and encoding in (1, 10) and language == 0x409:
            value = names[string_start + offset:string_start + offset + length].decode("utf-16-be")
            if name_id in metadata and metadata[name_id] != value:
                raise ValueError("ambiguous TTF English metadata")
            metadata[name_id] = value
    family = metadata.get(16, metadata.get(1))
    style = metadata.get(17, metadata.get(2))
    if not family or not style:
        raise ValueError("TTF family/style metadata unavailable")
    cmap = tables[b"cmap"]
    version, count = unpack(">HH", cmap, 0)
    if version != 0:
        raise ValueError("unsupported cmap version")
    maps = []
    for index in range(count):
        platform, encoding, start = unpack(">HHI", cmap, 4 + index * 8)
        if platform != 3 or encoding not in (1, 10):
            continue
        fmt = unpack(">H", cmap, start)[0]
        if fmt not in (4, 12):
            raise ValueError("unsupported Unicode cmap format")
        length = unpack(">I" if fmt == 12 else ">H", cmap, start + (4 if fmt == 12 else 2))[0]
        if start < 4 + count * 8 or start + length > len(cmap):
            raise ValueError("cmap subtable outside table")
        sub = cmap[start:start + length]
        mapping = {}
        if fmt == 12:
            groups = unpack(">I", sub, 12)[0]
            previous = -1
            for group in range(groups):
                first, last, glyph = unpack(">III", sub, 16 + group * 12)
                if first <= previous or first > last or last > 0x10FFFF or glyph + last - first >= glyph_count:
                    raise ValueError("invalid cmap12 group or glyph bounds")
                for cp in range(first, last + 1):
                    mapping[cp] = glyph + cp - first
                previous = last
        else:
            twice_segments = unpack(">H", sub, 6)[0]
            if not twice_segments or twice_segments % 2:
                raise ValueError("invalid cmap4 segment count")
            segments = twice_segments // 2
            ends = 14
            starts = ends + segments * 2 + 2
            deltas = starts + segments * 2
            ranges = deltas + segments * 2
            previous = -1
            for segment in range(segments):
                last = unpack(">H", sub, ends + segment * 2)[0]
                first = unpack(">H", sub, starts + segment * 2)[0]
                delta = unpack(">h", sub, deltas + segment * 2)[0]
                offset = unpack(">H", sub, ranges + segment * 2)[0]
                if first <= previous or first > last or offset % 2:
                    raise ValueError("invalid cmap4 segment")
                for cp in range(first, last + 1):
                    glyph = unpack(">H", sub, ranges + segment * 2 + offset + 2 * (cp - first))[0] if offset else cp
                    glyph = (glyph + delta) & 0xFFFF if not offset or glyph else 0
                    if glyph >= glyph_count:
                        raise ValueError("cmap4 glyph outside maxp bounds")
                    mapping[cp] = glyph
                previous = last
        maps.append((fmt, mapping))
    if not maps:
        raise ValueError("Unicode cmap unavailable")
    selected = max(maps, key=lambda item: item[0])[1]
    for _, mapping in maps:
        if any(selected.get(cp, 0) != glyph for cp, glyph in mapping.items() if cp != 0xFFFF):
            raise ValueError("conflicting Unicode cmaps")
    return family, style, selected, glyph_count


def validate_artifact_semantics(record, source_bytes, derived_bytes):
    """Bind source coverage and derived node positions to actual font bytes.

    This verifies semantic identities and transformation structure, not an
    independent recomputation of Qt outline geometry or rasterisation.
    """
    valid = validate_record(record)
    if valid.status is not GateStatus.PASS:
        return valid
    try:
        source_identity = {"sha256": hashlib.sha256(source_bytes).hexdigest(), "size": len(source_bytes)}
        if source_identity != record["actual_input"]:
            raise ValueError("source bytes differ from actual parsed input")
        source = ET.fromstring(source_bytes)
        derived = ET.fromstring(derived_bytes)
        ns = "{http://www.w3.org/2000/svg}"
        texts = [element for parent in list(source.iter()) for element in list(parent) if element.tag == ns + "text"]
        proof = record["glyph_proof"]
        derived_identity = {"sha256": hashlib.sha256(derived_bytes).hexdigest(), "size": len(derived_bytes)}
        if derived_identity != proof["derived_svg"]:
            raise ValueError("derived SVG bytes differ from their recorded identity")
        codepoints = [ord(char) for element in texts for char in (element.text or "")]
        if len(texts) != proof["text_nodes"] or len(codepoints) != proof["character_count"]:
            raise ValueError("source text node/character coverage mismatch")
        if codepoints != [item["codepoint"] for item in proof["mapping"]]:
            raise ValueError("source codepoint sequence mismatch")
        if any(element.tag in {ns + name for name in ("text", "tspan", "use", "image")} for element in derived.iter()):
            raise ValueError("derived SVG contains residual text/external references")
        fonts = {}
        for font in record["fonts"]:
            family, style, cmap, maximum = parse_ttf(_file_bytes(font))
            license_bytes = _file_bytes(font["license"])
            font_path = Path(font["path"]).resolve()
            license_path = Path(font["license"]["path"]).resolve()
            if license_path != font_path.parent / "LICENSE_DEJAVU" or hashlib.sha256(license_bytes).hexdigest() != DEJAVU_LICENSE_SHA256:
                raise ValueError("font is not bound to the retained DejaVu licence evidence")
            if DEJAVU_FONT_SHA256.get(font_path.name) != font["sha256"]:
                raise ValueError("font binary is not the retained DejaVu font/licence pair")
            if font["family"] != family or font["style"] != style or font["registered_families"] != [family]:
                raise ValueError("font family/style differs from TTF metadata")
            if font["sha256"] in fonts:
                raise ValueError("duplicate effective font identity")
            fonts[font["sha256"]] = (font_path.name, family, style, cmap, maximum)
        cursor = 0
        used = set()
        for element in texts:
            cls = element.get("class")
            bold = element.get("font-weight") == "700" or cls == "map-label"
            filename = "DejaVuSansMono.ttf" if cls == "mono" else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
            family = "DejaVu Sans Mono" if cls == "mono" else "DejaVu Sans"
            style = "Bold" if bold and cls != "mono" else "Book"
            size = float(element.get("font-size", 11 if cls in ("mono", "meta") else 12))
            for char in element.text or "":
                item = proof["mapping"][cursor]
                name, actual_family, actual_style, cmap, maximum = fonts[item["font_sha256"]]
                if (name, actual_family, actual_style) != (filename, family, style) or item["pixel_size"] != size:
                    raise ValueError("source text style is not bound to its effective font")
                if not 0 < item["glyph"] < maximum or item["glyph"] != cmap.get(ord(char), 0):
                    raise ValueError("glyph differs from font cmap/maxp")
                used.add(item["font_sha256"])
                cursor += 1
        if used != set(fonts):
            raise ValueError("unreferenced effective font identity")
        def compare(original, outlined):
            if original.tag == ns + "text":
                if list(original) or list(outlined) or outlined.tag != ns + "path" or outlined.text or outlined.tail:
                    raise ValueError("text-to-path node structure mismatch")
                cls = original.get("class")
                attrs = {"fill": original.get("fill", "#4a5054" if cls == "meta" else "#202427"), "fill-rule": "evenodd"}
                if cls == "map-label":
                    attrs.update(stroke="#fff", **{"stroke-width": "3", "paint-order": "stroke"})
                if original.get("id"):
                    attrs["id"] = original.get("id")
                actual = dict(outlined.attrib)
                if "d" not in actual:
                    raise ValueError("derived outline path data missing")
                actual.pop("d")
                if actual != attrs:
                    raise ValueError("text-to-path attributes mismatch")
                return
            if original.tag != outlined.tag or original.attrib != outlined.attrib or original.text != outlined.text or original.tail != outlined.tail or len(original) != len(outlined):
                raise ValueError("derived SVG structure differs outside text replacement")
            for before, after in zip(original, outlined):
                compare(before, after)
        compare(source, derived)
    except (OSError, ValueError, KeyError, struct.error, UnicodeError, ET.ParseError, RecursionError, RuntimeError) as exc:
        return _result(GateStatus.BLOCKED, "artifact semantic validation: %s" % exc)
    return _result(GateStatus.PASS, "source coverage, font cmap/maxp/metadata/licence and derived node structure verified; Qt outline geometry NOT_INDEPENDENTLY_RECOMPUTED")
