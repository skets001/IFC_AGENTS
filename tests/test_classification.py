import pytest
import ifcopenshell
from pathlib import Path

# from ifc_agent.classification.proxy_extractor import extract_proxies
from ifc_agent.classification.mutator import classify_and_mutate

def test_mutator(tmp_path):
    """Test that we can safely mutate a proxy element in an IFC model to a new structural entity."""
    
    # 1. We mock a simple generic model creation
    f = ifcopenshell.file(schema="IFC4")
    proxy = f.createIfcBuildingElementProxy(ifcopenshell.guid.new(), Name="Unknown Pump Engine")
    
    model_path = tmp_path / "test_model.ifc"
    f.write(str(model_path))
    
    # 2. Assert preconditions
    pre_f = ifcopenshell.open(model_path)
    assert pre_f.by_id(proxy.id()).is_a() == "IfcBuildingElementProxy"
    
    # 3. Simulate Classification Pipeline
    predictions = {
        proxy.GlobalId: "IfcPump"
    }
    
    out_path = tmp_path / "resolved.ifc"
    res = classify_and_mutate(model_path, predictions, output_path=out_path)
    
    # 4. Verify post conditions
    assert res["mutated_count"] == 1
    post_f = ifcopenshell.open(out_path)
    new_ent = post_f.by_id(proxy.id())
    
    assert new_ent.is_a() == "IfcPump"
    assert new_ent.Name == "Unknown Pump Engine"
