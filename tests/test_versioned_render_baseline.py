import copy
import hashlib
import json
import os
from pathlib import Path
import pytest
from urban_design.rendering_provenance import assess, GateStatus, HISTORICAL_NODE, RUNTIME_REQUIRED


def evidence():
    runtime = {key: "fixture-only" for key in RUNTIME_REQUIRED}
    runtime.update(
        python="fixture-python",
        executable={"path": "/fixture/python", "sha256": "1" * 64, "size": 123},
        qgis="3.40.5-Bratislava",
        qt="5.15.2",
        pyqt="5.15.4",
        libraries={
            name: {"path": f"/fixture/{name}", "sha256": str(index) * 64, "size": 456 + index}
            for index, name in enumerate(("QtCore", "QtGui", "QtSvg"), start=2)
        },
        loaded_libraries=[
            {"path": f"/fixture/{name}", "sha256": str(index) * 64, "size": 456 + index}
            for index, name in enumerate(("QtCore", "QtGui", "QtSvg"), start=2)
        ],
        os="fixture-os",
        machine="x86_64",
        dpi={"logical": 100.0, "physical": 100.0, "ratio": 1.0},
        png_formats=["png"],
        environment={"QT_QPA_PLATFORM": "offscreen"},
    )
    font = {
        "path": "/fixture/font.ttf",
        "sha256": "c" * 64,
        "size": 789,
        "face_index": 0,
        "family": "DejaVu Sans",
        "style": "Book",
        "registered_families": ["DejaVu Sans"],
        "license": {"path": "/fixture/LICENSE", "sha256": "3" * 64, "size": 321},
    }
    mapping = [{
        "text_index": 0,
        "codepoint": 65,
        "glyph": 1,
        "font_sha256": "c" * 64,
        "face_index": 0,
        "pixel_size": 12.0,
        "x": 0.0,
        "y": 12.0,
    }]
    return {
        "version": "qt-v2",
        "parent_svg": {"sha256": "a" * 64, "size": 111},
        "actual_input": {"sha256": "a" * 64, "size": 111},
        "png": {"sha256": "b" * 64, "size": 222},
        "runtime": runtime,
        "fonts": [font],
        "glyph_proof": {
            "status": "COMPLETE_NO_FALLBACK",
            "mapping": mapping,
            "character_count": 1,
            "text_nodes": 1,
            "transformation": "raw-file-face0-glyph-outline-v1",
            "derived_svg": {"sha256": "d" * 64, "size": 333},
        },
        "command": ["/fixture/python", "qt-render.py", "parent.svg", "render-0.png"],
        "helper": {"sha256": "4" * 64, "size": 444},
        "code": {
            "scripts/build_versioned_render_baseline.py": {"sha256": "5" * 64, "size": 555},
            "src/urban_design/rendering_provenance.py": {"sha256": "6" * 64, "size": 666},
            "scripts/create_site_proposal_rotterdam.py": {"sha256": "7" * 64, "size": 777},
        },
    }


def assert_blocked(expected, observed):
    try:
        result = assess(expected, observed)
    except Exception as exc:
        pytest.fail(f"malformed evidence raised {type(exc).__name__}: {exc}")
    assert result.status == GateStatus.BLOCKED


def test_exact_version_reproduction():
    assert assess(evidence(), evidence()).status == GateStatus.PASS


@pytest.mark.parametrize("key", ["parent_svg", "png", "runtime", "fonts", "version"])
def test_drift_fails_closed(key):
    before = evidence()
    after = copy.deepcopy(before)
    if key in ("parent_svg", "png"):
        after[key]["sha256"] = "f" * 64
    elif key == "runtime":
        after[key]["python"] = "different-python"
    elif key == "fonts":
        after[key][0]["style"] = "Oblique"
    else:
        after[key] = "different-version"
    assert assess(before, after).status == GateStatus.FAIL


@pytest.mark.parametrize("key", ["parent_svg", "runtime", "fonts", "version", "png"])
def test_missing_evidence_blocks(key):
    after = evidence()
    del after[key]
    assert assess(evidence(), after).status == GateStatus.BLOCKED


def test_unresolved_effective_font_blocks():
    after = evidence()
    after["fonts"] = [{"family": "Helvetica", "path": None, "sha256": None}]
    assert assess(after, after).status == GateStatus.BLOCKED


@pytest.mark.parametrize("key", ["parent_svg", "png"])
def test_invalid_hash_identity_blocks(key):
    record = evidence()
    record[key]["sha256"] = "unproven"
    assert assess(record, record).status == GateStatus.BLOCKED


@pytest.mark.parametrize("key", RUNTIME_REQUIRED)
def test_missing_runtime_component_blocks(key):
    record = evidence()
    del record["runtime"][key]
    assert assess(record, record).status == GateStatus.BLOCKED


def test_empty_fonts_block():
    record = evidence()
    record["fonts"] = []
    assert assess(record, record).status == GateStatus.BLOCKED


def test_missing_face_index_blocks():
    record = evidence()
    record["fonts"] = [{"path": "/font", "sha256": "c" * 64}]
    assert assess(record, record).status == GateStatus.BLOCKED


def test_unsupported_glyph_blocks():
    record = evidence()
    record["glyph_proof"] = {"status": "UNSUPPORTED"}
    assert assess(record, record).status == GateStatus.BLOCKED


def test_wrong_runtime_version_blocks():
    record = evidence()
    record["runtime"]["qt"] = "unexpected"
    assert assess(record, record).status == GateStatus.BLOCKED


def test_zero_glyph_rejected():
    record=evidence()
    record["glyph_proof"]["mapping"][0]["glyph"]=0
    assert assess(record,record).status==GateStatus.BLOCKED


def test_unmapped_fallback_rejected():
    record=evidence()
    record["glyph_proof"]["mapping"][0]["font_sha256"]="e"*64
    assert assess(record,record).status==GateStatus.BLOCKED


def test_incomplete_text_coverage_rejected():
    record=evidence()
    record["glyph_proof"]["character_count"]=2
    assert assess(record,record).status==GateStatus.BLOCKED


@pytest.mark.parametrize("bad_mapping", [1, None, {"entry": {"glyph": 1}}])
def test_malformed_mapping_container_blocks(bad_mapping):
    record = evidence()
    record["glyph_proof"]["mapping"] = bad_mapping
    assert_blocked(record, record)


def test_mapping_entry_requires_source_character_and_index():
    record = evidence()
    record["glyph_proof"]["mapping"] = [{"glyph": 1, "font_sha256": "c" * 64, "face_index": 0}]
    assert_blocked(record, record)


@pytest.mark.parametrize("codepoint", [-1, 0x110000, 0xD800, True])
def test_invalid_unicode_scalar_blocks(codepoint):
    record = evidence()
    record["glyph_proof"]["mapping"][0]["codepoint"] = codepoint
    assert_blocked(record, record)


@pytest.mark.parametrize("glyph", [-1, 1.5, True])
def test_invalid_glyph_identifier_blocks(glyph):
    record = evidence()
    record["glyph_proof"]["mapping"][0]["glyph"] = glyph
    assert_blocked(record, record)


def test_noncontiguous_glyph_indexes_block():
    record = evidence()
    second = copy.deepcopy(record["glyph_proof"]["mapping"][0])
    second.update(text_index=2, codepoint=66, x=10.0)
    record["glyph_proof"]["mapping"].append(second)
    record["glyph_proof"]["character_count"] = 2
    assert_blocked(record, record)


@pytest.mark.parametrize("bad_identity", [
    {"sha256": "bad", "size": 333},
    {"sha256": "d" * 64, "size": False},
    {"sha256": "d" * 64, "size": 0},
])
def test_derived_svg_identity_must_be_complete(bad_identity):
    record = evidence()
    record["glyph_proof"]["derived_svg"] = bad_identity
    assert_blocked(record, record)


@pytest.mark.parametrize("face_index", [False, 1, 0.0])
def test_font_face_index_must_be_exact_integer_zero(face_index):
    record = evidence()
    record["fonts"][0]["face_index"] = face_index
    assert_blocked(record, record)


def test_mapping_face_index_must_be_exact_integer_zero():
    record = evidence()
    record["glyph_proof"]["mapping"][0]["face_index"] = False
    assert_blocked(record, record)


@pytest.mark.parametrize("sha256", [42, None, True])
def test_hash_fields_with_nonstring_values_block_without_exception(sha256):
    record = evidence()
    record["parent_svg"]["sha256"] = sha256
    assert_blocked(record, record)


def test_glyph_font_hash_with_nonstring_value_blocks_without_exception():
    record = evidence()
    record["glyph_proof"]["mapping"][0]["font_sha256"] = False
    assert_blocked(record, record)


def test_unrepresentably_large_font_size_blocks_without_exception():
    record = evidence()
    record["glyph_proof"]["mapping"][0]["pixel_size"] = 10 ** 10000
    assert_blocked(record, record)


def test_font_license_identity_is_required():
    record = evidence()
    del record["fonts"][0]["license"]
    assert_blocked(record, record)


def test_runtime_binary_identity_must_be_populated():
    record = evidence()
    record["runtime"]["executable"] = {"path": "/fixture/python", "sha256": "bad", "size": 0}
    assert_blocked(record, record)


@pytest.mark.parametrize("text_nodes", [0, False, "one"])
def test_text_node_count_is_positive_integer(text_nodes):
    record = evidence()
    record["glyph_proof"]["text_nodes"] = text_nodes
    assert_blocked(record, record)


def test_non_mapping_record_roots_block_without_exception():
    assert_blocked([], [])


def test_builder_has_typed_baseline_validation_entrypoint():
    from scripts import build_versioned_render_baseline as builder
    assert callable(getattr(builder, "validate_baseline_manifest", None))


def test_builder_has_immutable_parent_snapshot_entrypoint():
    from scripts import build_versioned_render_baseline as builder
    assert callable(getattr(builder, "capture_parent_snapshot", None))


def manifest_fixture():
    first = evidence()
    second = copy.deepcopy(first)
    second["command"][-1] = "render-1.png"
    return {
        "schema_version": "renderer-gates-v2",
        "parent_snapshot": copy.deepcopy(first["parent_svg"]),
        "records": [first, second],
        "byte_equivalence": True,
        "gates": {
            HISTORICAL_NODE: {
                "status": "HISTORICAL_BLOCKED",
                "policy": "RENDER-C01",
                "original_assertions": "UNCHANGED",
            },
            "CURRENT_VERSION_REPRODUCIBILITY": {
                "status": "PASS",
                "reason": "exact bytes and fingerprint reproduced",
            },
            "PINNED_BASELINE_REPLAY": {
                "status": "NOT_REQUESTED",
                "reason": "no pinned baseline supplied",
            },
        },
        "release_acceptance": False,
        "migration_diagnostics": [],
    }


def test_v2_manifest_accepts_complete_two_record_shape():
    from scripts import build_versioned_render_baseline as builder
    result = builder.validate_baseline_manifest(manifest_fixture())
    assert result.status == GateStatus.PASS, result.reason


@pytest.mark.parametrize("bad_records", [[], [evidence()], [evidence(), {}], [evidence(), evidence(), evidence()]])
def test_manifest_requires_exactly_two_valid_records(bad_records):
    from scripts import build_versioned_render_baseline as builder
    manifest = manifest_fixture()
    manifest["records"] = bad_records
    result = builder.validate_baseline_manifest(manifest)
    assert result.status == GateStatus.BLOCKED


@pytest.mark.parametrize("bad_equivalence", [False, 0, "true", None])
def test_manifest_requires_boolean_equivalence_matching_png_identities(bad_equivalence):
    from scripts import build_versioned_render_baseline as builder
    manifest = manifest_fixture()
    manifest["byte_equivalence"] = bad_equivalence
    result = builder.validate_baseline_manifest(manifest)
    assert result.status == GateStatus.BLOCKED


def test_manifest_cannot_claim_equivalence_when_png_identities_differ():
    from scripts import build_versioned_render_baseline as builder
    manifest = manifest_fixture()
    manifest["records"][1]["png"] = {"sha256": "e" * 64, "size": 223}
    result = builder.validate_baseline_manifest(manifest)
    assert result.status == GateStatus.BLOCKED


@pytest.mark.parametrize("changed", ["code", "helper", "png", "derived_svg"])
def test_manifest_checks_second_render_identity(changed):
    from scripts import build_versioned_render_baseline as builder
    manifest = manifest_fixture()
    second = manifest["records"][1]
    if changed == "code":
        second["code"]["scripts/build_versioned_render_baseline.py"]["sha256"] = "e" * 64
    elif changed == "helper":
        second["helper"]["sha256"] = "e" * 64
    elif changed == "png":
        second["png"]["sha256"] = "e" * 64
    else:
        second["glyph_proof"]["derived_svg"]["sha256"] = "e" * 64
    result = builder.validate_baseline_manifest(manifest)
    assert result.status in (GateStatus.BLOCKED, GateStatus.FAIL)


@pytest.mark.parametrize("field", ["schema_version", "gates", "release_acceptance", "migration_diagnostics"])
def test_manifest_rejects_invalid_top_level_contract(field):
    from scripts import build_versioned_render_baseline as builder
    manifest = manifest_fixture()
    if field == "schema_version":
        manifest[field] = "renderer-gates-v1"
    elif field == "gates":
        del manifest[field]["PINNED_BASELINE_REPLAY"]
    elif field == "release_acceptance":
        manifest[field] = True
    else:
        manifest[field] = "none"
    result = builder.validate_baseline_manifest(manifest)
    assert result.status == GateStatus.BLOCKED


def test_legacy_manifest_is_rejected_with_migration_diagnostic_without_rewrite(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    path = tmp_path / "old-manifest.json"
    original = b'{"schema_version":"renderer-gates-v1","records":[]}'
    path.write_bytes(original)
    _, result = builder.load_baseline(path)
    assert result.status == GateStatus.BLOCKED
    assert "renderer-gates-v1" in result.reason
    assert "renderer-gates-v2" in result.reason
    assert path.read_bytes() == original


def test_pathologically_nested_manifest_json_blocks_without_rewrite(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    path = tmp_path / "deep-manifest.json"
    original = b"[" * 12000 + b"0" + b"]" * 12000
    path.write_bytes(original)
    _, result = builder.load_baseline(path)
    assert result.status == GateStatus.BLOCKED
    assert path.read_bytes() == original


def _bind_path_identity(directory, name):
    path = directory / name
    path.write_bytes((name + " fixture binary").encode())
    data = path.read_bytes()
    return {"path": str(path), **_identity(data)}


def test_runtime_binary_font_and_license_hashes_are_verified_from_files(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    record = evidence()
    runtime = record["runtime"]
    runtime["executable"] = _bind_path_identity(tmp_path, "python")
    runtime["libraries"] = {
        name: _bind_path_identity(tmp_path, name)
        for name in ("QtCore", "QtGui", "QtSvg")
    }
    runtime["loaded_libraries"] = list(runtime["libraries"].values())
    record["fonts"][0]["path"] = str(tmp_path / "font.ttf")
    font_identity = _bind_path_identity(tmp_path, "font.ttf")
    record["fonts"][0].update(font_identity)
    record["glyph_proof"]["mapping"][0]["font_sha256"] = font_identity["sha256"]
    license_identity = _bind_path_identity(tmp_path, "LICENSE")
    record["fonts"][0]["license"] = license_identity
    result = builder.validate_runtime_files(record)
    assert result.status == GateStatus.PASS, result.reason
    (tmp_path / "LICENSE").write_bytes(b"license changed")
    assert builder.validate_runtime_files(record).status == GateStatus.BLOCKED


def _identity(data):
    return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def _write_bound_artifacts(directory, manifest):
    helper_bytes = b"# fixture render helper\n"
    parent_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><text>A</text></svg>"
    (directory / "parent-snapshot.svg").write_bytes(parent_bytes)
    manifest["parent_snapshot"] = _identity(parent_bytes)
    (directory / "qt-render.py").write_bytes(helper_bytes)
    for index, record in enumerate(manifest["records"]):
        png_bytes = b"same fixture png bytes"
        svg_bytes = b"<svg xmlns='http://www.w3.org/2000/svg'><path d='M0 0' fill='#202427' fill-rule='evenodd'/></svg>"
        (directory / f"render-{index}.png").write_bytes(png_bytes)
        (directory / f"render-{index}.png.svg").write_bytes(svg_bytes)
        record["parent_svg"] = _identity(parent_bytes)
        record["actual_input"] = _identity(parent_bytes)
        record["png"] = _identity(png_bytes)
        record["glyph_proof"]["derived_svg"] = _identity(svg_bytes)
        record["helper"] = _identity(helper_bytes)
    # Actual installed TTF and retained licence, rather than invented font bytes.
    # This fixture qualifies local artifact semantics only; no Qt render is claimed.
    font_dir = Path("/Applications/QGIS-LTR.app/Contents/Resources/python/site-packages/matplotlib-3.3.0-py3.9-macosx-10.13.0-x86_64.egg/matplotlib/mpl-data/fonts/ttf")
    for record in manifest["records"]:
        font = record["fonts"][0]
        font.update(path=str(font_dir / "DejaVuSans.ttf"), **_identity((font_dir / "DejaVuSans.ttf").read_bytes()))
        font["license"] = {"path": str(font_dir / "LICENSE_DEJAVU"), **_identity((font_dir / "LICENSE_DEJAVU").read_bytes())}
        record["glyph_proof"]["mapping"][0].update(font_sha256=font["sha256"], glyph=36)
        record["runtime"]["executable"] = _bind_path_identity(directory, "python")
        record["runtime"]["libraries"] = {name: _bind_path_identity(directory, name) for name in ("QtCore", "QtGui", "QtSvg")}
        record["runtime"]["loaded_libraries"] = list(record["runtime"]["libraries"].values())
        from scripts import build_versioned_render_baseline as builder
        record["code"] = {name: builder.ref(builder.ROOT / name) for name in record["code"]}
    manifest["records"][1]["command"][-1] = "render-1.png"
    return manifest


def test_artifact_validation_checks_both_pngs_derived_svgs_and_helper(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    assert builder.validate_baseline_manifest(manifest).status == GateStatus.PASS
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    result = builder.validate_baseline_artifacts(manifest, manifest_path)
    assert result.status == GateStatus.PASS, result.reason
    loaded, result = builder.load_baseline(manifest_path)
    assert result.status == GateStatus.PASS, result.reason
    assert loaded == manifest


@pytest.mark.parametrize("relative", ["parent-snapshot.svg", "render-1.png", "render-1.png.svg", "qt-render.py"])
def test_artifact_validation_detects_corruption_in_each_identity_class(tmp_path, relative):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    artifact = tmp_path / relative
    artifact.write_bytes(artifact.read_bytes() + b"corrupt")
    result = builder.validate_baseline_artifacts(manifest, tmp_path / "manifest.json")
    assert result.status == GateStatus.BLOCKED


def test_both_render_commands_use_one_captured_read_only_source_snapshot(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    source = tmp_path / "parent.svg"
    output = tmp_path / "exclusive-output"
    output.mkdir()
    original = b"<svg xmlns='http://www.w3.org/2000/svg'><text>A</text></svg>"
    source.write_bytes(original)
    snapshot = builder.capture_parent_snapshot(source, output)
    assert snapshot.read_bytes() == original
    assert os.stat(snapshot).st_mode & 0o222 == 0
    source.write_bytes(b"changed after capture")
    commands = [
        builder.build_render_command(output / "qt-render.py", snapshot, output / f"render-{i}.png")
        for i in range(2)
    ]
    assert commands[0][-2] == commands[1][-2] == str(snapshot)
    assert commands[0][-1] != commands[1][-1]
    assert snapshot.read_bytes() == original


def test_snapshot_capture_is_exclusive_and_does_not_overwrite(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    source = tmp_path / "parent.svg"
    output = tmp_path / "exclusive-output"
    output.mkdir()
    source.write_bytes(b"source")
    snapshot = output / "parent-snapshot.svg"
    snapshot.write_bytes(b"preserve me")
    with pytest.raises(FileExistsError):
        builder.capture_parent_snapshot(source, output)
    assert snapshot.read_bytes() == b"preserve me"


@pytest.mark.parametrize("probe", ["codepoint", "glyph", "text_nodes", "family"])
def test_semantic_forgery_is_rejected_from_bound_artifacts(tmp_path, probe):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    for record in manifest["records"]:
        if probe == "codepoint":
            record["glyph_proof"]["mapping"][0]["codepoint"] = 0x10FFFF
        elif probe == "glyph":
            record["glyph_proof"]["mapping"][0]["glyph"] = 2147483647
        elif probe == "text_nodes":
            record["glyph_proof"]["text_nodes"] = 999999
        else:
            record["fonts"][0].update(family="Invented Family", registered_families=["Invented Family"])
    result = builder.validate_baseline_artifacts(manifest, tmp_path / "manifest.json")
    assert result.status == GateStatus.BLOCKED, result.reason


def test_child_parses_one_buffer_and_reports_actual_input_identity():
    from scripts import build_versioned_render_baseline as builder
    assert "ET.fromstring(input_bytes)" in builder.HELPER
    assert "actual_input" in builder.HELPER
    assert "ET.parse(sys.argv[1])" not in builder.HELPER


@pytest.mark.parametrize("probe", ["executable", "source"])
def test_full_baseline_verification_rejects_runtime_and_source_forgery(tmp_path, probe):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    for record in manifest["records"]:
        if probe == "executable":
            record["runtime"]["executable"]["path"] = str(tmp_path / "nonexistent")
        else:
            record["code"]["scripts/create_site_proposal_rotterdam.py"]["sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    # Archival loading must never imply verification of local runtime/source bytes.
    _, archival = builder.load_baseline(path)
    assert "runtime/source bytes NOT_VERIFIED" in archival.reason
    _, full = builder.load_baseline(path, verify_runtime=True)
    assert full.status == GateStatus.BLOCKED, full.reason


@pytest.mark.parametrize("index", [0, 1])
def test_actual_input_digest_mismatch_is_fail_even_when_parent_is_restored(index):
    from urban_design.rendering_provenance import validate_baseline_manifest
    manifest = manifest_fixture()
    manifest["records"][index]["actual_input"]["sha256"] = "e" * 64
    result = validate_baseline_manifest(manifest)
    assert result.status == GateStatus.FAIL
    assert "actual parsed input" in result.reason


@pytest.mark.parametrize("probe", ["style", "license", "maxp", "derived_nodes", "source_sequence"])
def test_artifact_semantics_rejects_additional_relationship_forgery(tmp_path, probe):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    if probe in ("license", "maxp"):
        font = manifest["records"][0]["fonts"][0]
        original = Path(font["path"]).read_bytes()
        (tmp_path / "DejaVuSans.ttf").write_bytes(original)
        license_bytes = Path(font["license"]["path"]).read_bytes()
        if probe == "license":
            license_bytes += b" altered licence"
        else:
            import struct
            altered = bytearray(original)
            for index in range(struct.unpack_from(">H", original, 4)[0]):
                tag, _, offset, _ = struct.unpack_from(">4sIII", original, 12 + 16 * index)
                if tag == b"maxp":
                    struct.pack_into(">H", altered, offset + 4, 1)
            (tmp_path / "DejaVuSans.ttf").write_bytes(altered)
        (tmp_path / "LICENSE_DEJAVU").write_bytes(license_bytes)
        for record in manifest["records"]:
            record["fonts"][0].update(path=str(tmp_path / "DejaVuSans.ttf"), **builder.ref(tmp_path / "DejaVuSans.ttf"))
            record["fonts"][0]["license"] = {"path": str(tmp_path / "LICENSE_DEJAVU"), **builder.ref(tmp_path / "LICENSE_DEJAVU")}
            record["glyph_proof"]["mapping"][0]["font_sha256"] = record["fonts"][0]["sha256"]
    elif probe == "style":
        for record in manifest["records"]:
            record["fonts"][0]["style"] = "Invented Style"
    elif probe == "derived_nodes":
        for index, record in enumerate(manifest["records"]):
            path = tmp_path / f"render-{index}.png.svg"
            path.write_bytes(path.read_bytes().replace(b"</svg>", b"<path d='M0 0'/></svg>"))
            record["glyph_proof"]["derived_svg"] = builder.ref(path)
    else:
        path = tmp_path / "parent-snapshot.svg"
        path.write_bytes(path.read_bytes().replace(b">A<", b">B<"))
        manifest["parent_snapshot"] = builder.ref(path)
        for record in manifest["records"]:
            record["parent_svg"] = builder.ref(path)
            record["actual_input"] = builder.ref(path)
    result = builder.validate_baseline_artifacts(manifest, tmp_path / "manifest.json")
    assert result.status == GateStatus.BLOCKED
    assert "artifact semantic validation" in result.reason


def test_full_verification_accepts_bound_local_files_and_declares_no_execution(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    _, result = builder.load_baseline(path, verify_runtime=True)
    assert result.status == GateStatus.PASS, result.reason
    assert "local runtime/source bytes verified" in result.reason
    assert "execution replay NOT_VERIFIED" in result.reason


@pytest.mark.parametrize("data", [b"", b"bad font", b"\x00\x01\x00\x00"])
def test_truncated_ttf_is_rejected_without_qualification(data):
    from urban_design.rendering_provenance import parse_ttf
    with pytest.raises((ValueError, KeyError)):
        parse_ttf(data)



def test_altered_font_binary_cannot_borrow_retained_dejavu_license(tmp_path):
    from scripts import build_versioned_render_baseline as builder
    manifest = _write_bound_artifacts(tmp_path, manifest_fixture())
    font = manifest["records"][0]["fonts"][0]
    # Keep all cmap/name/maxp metadata; change an outline byte and rebind hashes.
    import struct
    data = bytearray(Path(font["path"]).read_bytes())
    for index in range(struct.unpack_from(">H", data, 4)[0]):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + 16 * index)
        if tag == b"glyf":
            data[offset + 10] ^= 1
    path = tmp_path / "DejaVuSans.ttf"
    path.write_bytes(data)
    license_path = tmp_path / "LICENSE_DEJAVU"
    license_path.write_bytes(Path(font["license"]["path"]).read_bytes())
    for record in manifest["records"]:
        record["fonts"][0].update(path=str(path), **builder.ref(path))
        record["fonts"][0]["license"] = {"path": str(license_path), **builder.ref(license_path)}
        record["glyph_proof"]["mapping"][0]["font_sha256"] = builder.ref(path)["sha256"]
    result = builder.validate_baseline_artifacts(manifest, tmp_path / "manifest.json")
    assert result.status == GateStatus.BLOCKED, result.reason
    assert "retained DejaVu font/licence pair" in result.reason
