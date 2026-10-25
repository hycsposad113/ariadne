import json

import pytest

from urban_design.judgement.core import ROOT, Registry, validate
from urban_design.judgement.inputs import assemble


def test_climate_harbour_round2_sample_validates_against_current_inputs():
    required_inputs = [
        ROOT / "artifacts/w8/e1-fabric/comparison_table.csv",
        ROOT / "artifacts/w8/utci/utci_stress_hours_comparison.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required_inputs if not path.is_file()]
    if missing:
        pytest.skip(f"climate sample inputs missing: {', '.join(missing)}")

    registry = Registry()
    sample_path = ROOT / "knowledge/judgement/examples/J-CLIMATE-harbour-round2-sample.json"
    sample = json.loads(sample_path.read_text())
    bundle = assemble(None, "judgement-sample-test", "J-CLIMATE", ["harbour_grain"], registry)

    assert validate(sample, bundle, registry.specs["J-CLIMATE"], registry.schema) == []
