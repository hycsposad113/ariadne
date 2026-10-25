import hashlib, json, sqlite3, struct, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v4/run-20260915T125400Z"
V3 = ROOT / "artifacts/milestone2-site-proposal-rotterdam-m4h-v3/run-20260915T120300Z"


def payload():
    return json.loads((PACKAGE / "site-proposal.json").read_text(encoding="utf-8"))


def _portable_json(base: Path, relative: str):
    value = json.loads((base / relative).read_text(encoding="utf-8"))
    project_roots = (
        "/Users/jackhsieh/Downloads/TUD/Q5/project",
        str(ROOT),
    )

    def normalize(item):
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, str):
            for root in project_roots:
                item = item.replace(root, "<PROJECT_ROOT>")
        return item

    return normalize(value)


def _assert_proposal_state_equivalent(rebuilt: Path, canonical: Path) -> None:
    def read(database: Path):
        connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        try:
            metadata = dict(connection.execute("SELECT key, value FROM store_metadata"))
            result = {"schema_version": metadata.get("schema_version")}
            result["metadata"] = sorted(
                (key, value) for key, value in metadata.items() if key != "schema_version"
            )
            for table, order in (
                ("state_heads", "entity_id"),
                ("state_versions", "entity_id, revision"),
                ("ledger_events", "sequence"),
            ):
                columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
                if table == "ledger_events":
                    columns = [column for column in columns if column in {
                        "sequence", "event_id", "timestamp", "actor", "action", "target_id",
                        "target_type", "project_id", "prior_status", "changed_refs_json",
                        "reason", "resulting_refs_json", "supersedes", "parent_event_id",
                        "state_revision", "payload_json",
                    }]
                rows = connection.execute(
                    f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order}"
                ).fetchall()
                normalized_rows = []
                for row in rows:
                    values = list(row)
                    if table == "state_versions" and row[1] == "Artifact":
                        payload_index = columns.index("payload_json")
                        artifact = json.loads(values[payload_index])
                        if artifact.get("uri") == "sources/source-records-v4.json":
                            artifact_file = database.parent / artifact["uri"]
                            artifact_bytes = artifact_file.read_bytes()
                            assert artifact.get("size_bytes") == len(artifact_bytes)
                            assert artifact.get("sha256") == "sha256:" + hashlib.sha256(artifact_bytes).hexdigest()
                            artifact["sha256"] = "<checkout-derived-sha256>"
                            values[payload_index] = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
                    normalized_rows.append(tuple(values))
                result[table] = normalized_rows
            if "actor_kind" in {
                row[1] for row in connection.execute("PRAGMA table_info(ledger_events)")
            }:
                assert connection.execute(
                    "SELECT COUNT(*) FROM ledger_events WHERE actor_kind IS NOT NULL OR actor_session_id IS NOT NULL"
                ).fetchone()[0] == 0
            assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            return result
        finally:
            connection.close()

    rebuilt_state = read(rebuilt)
    canonical_state = read(canonical)
    assert rebuilt_state["schema_version"] == "2"
    assert canonical_state["schema_version"] == "1"
    for table in ("state_heads", "state_versions", "ledger_events"):
        assert rebuilt_state[table] == canonical_state[table]


def test_project_runtime_imports_geometry_dependencies():
    result = subprocess.run([sys.executable, "-c", "import pyproj, shapely; print(pyproj.__version__, shapely.__version__)"], cwd=ROOT, text=True, capture_output=True, check=True)
    assert result.stdout.strip().startswith("3.8.")
    assert "2.1." in result.stdout


def test_v4_validates_source_backed_proposed_state():
    from urban_design.site_proposal_rotterdam_v4 import validate_site_proposal_rotterdam_v4
    proposal = validate_site_proposal_rotterdam_v4(payload(), PACKAGE, v3_dir=V3)
    assert proposal.id == "site-proposal-rotterdam-m4h-v4"
    assert proposal.supersedes_proposal_id == "site-proposal-rotterdam-m4h-v3"
    assert proposal.status == "PROPOSED"
    assert proposal.human_decision_status == "HUMAN_DECISION_REQUIRED"


def test_parent_v3_manifest_preserves_every_parent_byte():
    manifest = json.loads((PACKAGE / "parent-v3-integrity.json").read_text(encoding="utf-8"))
    assert manifest["parent_id"] == "site-proposal-rotterdam-m4h-v3"
    for item in manifest["files"]:
        retained = PACKAGE / item["retained_path"]
        original = V3 / item["relative_path"]
        assert retained.read_bytes() == original.read_bytes()
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == item["sha256"].split(":", 1)[1]


def test_every_boundary_edge_is_bgt_wegdeel_geometry():
    boundary = json.loads((PACKAGE / "boundary-epsg28992-v4.geojson").read_text(encoding="utf-8"))["geometry"]
    evidence = json.loads((PACKAGE / "sources/boundary-relationship-evidence-v4.json").read_text(encoding="utf-8"))
    assert evidence["source_dataset"] == "BGT"
    assert evidence["source_collection"] == "wegdeel"
    assert len(evidence["edges"]) == len(boundary["coordinates"][0]) - 1
    raw = json.loads((PACKAGE / "sources/raw/pdok-bgt-wegdeel-m4h.json").read_text(encoding="utf-8"))
    source = {str(feature["id"]): feature for feature in raw["features"]}
    for index, edge in enumerate(evidence["edges"]):
        assert edge["edge_index"] == index
        assert edge["source_dataset"] == "BGT"
        assert edge["source_collection"] == "wegdeel"
        assert edge["claim_status"] == "SOURCE_GEOMETRY_SEGMENT"
        assert edge["physical_edge_claim"] is True
        assert "OSM" not in json.dumps(edge).upper()
        assert "HUMAN_INTENT" not in json.dumps(edge).upper()
        feature = source[edge["source_feature_id"]]
        segment = edge["source_segment"]
        assert feature["properties"]["functie"] == "rijbaan lokale weg"
        assert feature["geometry"]["type"] == "Polygon"
        assert segment[1] == segment[0] + 1
        coordinates = feature["geometry"]["coordinates"][0]
        assert segment[1] < len(coordinates)


def test_building_crossing_is_zero_including_target_274539331():
    proposal = payload()
    context = proposal["delft_context"]
    assert context["building_crossing_count"] == 0
    assert context["cross_boundary_buildings"] == []
    assert context["bag_building_crossing_count"] == 0
    assert context["bag_cross_boundary_buildings"] == []
    evidence = json.loads((PACKAGE / "sources/boundary-relationship-evidence-v4.json").read_text(encoding="utf-8"))
    assert evidence["bag_building_crossing_count"] == 0
    assert evidence["bag_cross_boundary_buildings"] == []
    display = json.loads((PACKAGE / "display-data-v4.geojson").read_text(encoding="utf-8"))
    assert display["cross_boundary_buildings"] == []
    assert not any((f.get("properties") or {}).get("cross_boundary") for f in display["features"])
    target = [f for f in display["features"] if str(f.get("id")) == "274539331"]
    assert target and not target[0]["properties"].get("cross_boundary", False)


def test_display_and_svg_contract_remains_v3_style_order():
    display = json.loads((PACKAGE / "display-data-v4.geojson").read_text(encoding="utf-8"))
    expected = ["background/land", "water", "public/open", "context buildings", "site buildings", "roads/walk paths", "rail", "labels/markers", "boundary"]
    assert display["classification_priority"] == expected
    assert sum((f.get("properties") or {}).get("display_layer") == "water" for f in display["features"]) <= 1
    text = (PACKAGE / "map-preview-v4.svg").read_text(encoding="utf-8")
    ids = [f'id="{value}"' for value in expected if False]
    required = ['layer-background', 'layer-water', 'layer-public-space', 'layer-context-buildings', 'layer-site-buildings', 'layer-roads', 'layer-rail', 'layer-markers', 'layer-boundary']
    positions = [text.index(f'id="{value}"') for value in required]
    assert positions == sorted(positions)
    assert '#f1f4f5' in text and '#d62728' in text and 'stroke-width="1.4"' in text
    assert 'fill="none"' in text and 'site-proposal-rotterdam-m4h-v4' in text
    assert 'REJECTED_BY_HUMAN_FEEDBACK' in text
    assert 'HUMAN_INTENT_ALIGNMENT_REVIEW' not in text and 'OSM road geometry' not in text


def test_png_is_1240x850_and_nonblank():
    raw = (PACKAGE / "map-preview-v4.png").read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", raw[16:24]) == (1240, 850)
    assert b"IDAT" in raw
    assert any(byte not in (0, 255) for byte in raw[32:])


def test_state_is_proposed_only_and_project_is_unadopted():
    con = sqlite3.connect(PACKAGE / "proposal-state.sqlite3")
    try:
        projects = [json.loads(row[0]) for row in con.execute("select payload_json from state_versions where entity_type='Project'")]
        assert any(item.get("id") == "rotterdam-m4h-pilot-project" and item.get("site_id") is None for item in projects)
        sites = [json.loads(row[0]) for row in con.execute("select payload_json from state_versions where entity_type in ('Site','SiteModel')")]
        assert any(item.get("version") == "v4" and str(item.get("status", "")).upper() == "PROPOSED" for item in sites)
        bad = con.execute("select action from ledger_events where lower(action) like '%approve%' or lower(action) like '%accept%' or lower(action) like '%freeze%'").fetchall()
        assert not bad
    finally:
        con.close()


def test_offline_rebuild_matches_canonical_artifacts_across_store_schema(tmp_path):
    from scripts.create_site_proposal_rotterdam_v4 import build_rotterdam_v4
    out = tmp_path / "rebuild"
    rebuilt = build_rotterdam_v4(out, v3_dir=V3, bgt_source=PACKAGE / "sources/raw/pdok-bgt-wegdeel-m4h.json", bag_source=PACKAGE / "sources/raw/pdok-bag-pand-m4h.json", offline=True)
    assert rebuilt.boundary_sha256 == payload()["boundary_sha256"]
    assert rebuilt.geometry_sha256 == payload()["geometry_sha256"]
    canonical_files = {p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*") if p.is_file()}
    rebuilt_files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert rebuilt_files == canonical_files
    for name in sorted(canonical_files):
        if name == "proposal-state.sqlite3":
            _assert_proposal_state_equivalent(out / name, PACKAGE / name)
        elif name in {"sources/human-feedback-evidence.json", "sources/source-records-v4.json"}:
            rebuilt_json = _portable_json(out, name)
            canonical_json = _portable_json(PACKAGE, name)
            if name == "sources/source-records-v4.json":
                record_id = "source-human-feedback-v4"
                rebuilt_record = next(row for row in rebuilt_json["records"] if row["id"] == record_id)
                canonical_record = next(row for row in canonical_json["records"] if row["id"] == record_id)
                for base, record in ((out, rebuilt_record), (PACKAGE, canonical_record)):
                    retained = (base / record["artifact_path"]).read_bytes()
                    assert record["artifact_size_bytes"] == len(retained)
                    assert record["artifact_sha256"] == "sha256:" + hashlib.sha256(retained).hexdigest()
                for record in (rebuilt_record, canonical_record):
                    record["artifact_size_bytes"] = "<checkout-dependent-size>"
                    record["artifact_sha256"] = "<checkout-dependent-sha256>"
            assert rebuilt_json == canonical_json
        else:
            assert (out / name).read_bytes() == (PACKAGE / name).read_bytes()
