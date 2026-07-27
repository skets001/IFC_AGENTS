import pytest
import ifcopenshell
from pathlib import Path

from ifc_agent.enrichment.injector import evaluate_and_inject
from ifcopenshell.util.element import get_psets

def test_enrichment_mutation(tmp_path):
    """Test that inferred values are perfectly pushed into standard Property sets safely without breaking."""
    
    # Core element
    f = ifcopenshell.file(schema="IFC4")
    pump = f.createIfcPump(ifcopenshell.guid.new(), Name="DAIKIN-332-AHU-Pump")
    model_path = tmp_path / "mock.ifc"
    f.write(str(model_path))

    injection_map = {
        pump.GlobalId: {
            "Manufacturer": "Daikin",
            "ModelReference": "332-AHU"
        }
    }
    
    out_path = tmp_path / "enriched.ifc"
    
    res = evaluate_and_inject(model_path, injection_map, output_path=out_path)
    assert res["elements_mutated"] == 1
    assert res["properties_added"] == 2
    
    post_f = ifcopenshell.open(str(out_path))
    mod_pump = post_f.by_guid(pump.GlobalId)
    
    psets = get_psets(mod_pump)
    assert "Pset_ManufacturerTypeInformation" in psets
    assert psets["Pset_ManufacturerTypeInformation"]["Manufacturer"] == "Daikin"
    assert psets["Pset_ManufacturerTypeInformation"]["ModelReference"] == "332-AHU"
