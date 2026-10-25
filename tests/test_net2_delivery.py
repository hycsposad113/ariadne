import importlib.util
from pathlib import Path
from shapely.geometry import LineString, box, mapping

spec=importlib.util.spec_from_file_location('net2_delivery',Path(__file__).parents[1]/'scripts/verify_net2_delivery.py')
module=importlib.util.module_from_spec(spec)

def test_link_requires_actual_both_end_contacts_and_clear_land():
    spec.loader.exec_module(module)
    row={'geometry':mapping(LineString([(0,0),(5,0)]))}
    target=LineString([(0,10),(5,10)])
    links=[{'geometry':mapping(LineString([(3,0),(3,10)])),'properties':{'width_m':2}}]
    assert module.has_clear_contact(row,target,links,box(-2,-2,12,12),box(20,20,22,22))
    assert not module.has_clear_contact(row,target,links,box(-2,-2,12,12).difference(box(0,4,10,6)),box(20,20,22,22))
    assert not module.has_clear_contact(row,target,links,box(-2,-2,12,12),box(2,4,4,6))
    links[0]['geometry']=mapping(LineString([(3,0),(3,9)]))
    assert not module.has_clear_contact(row,target,links,box(-2,-2,12,12),box(20,20,22,22))

def test_validation_receipt_compares_serialized_geometry_without_hiding_values():
    spec.loader.exec_module(module)
    fresh={'failure_ids':['FIRE'],'checks':{'FIRE':{'geometry':{'coordinates':((1.,2.),(3.,4.))},'distance_m':41.}}}
    stored={'failure_ids':['FIRE'],'checks':{'FIRE':{'geometry':{'coordinates':[[1.,2.],[3.,4.]]},'distance_m':41.}}}
    assert module.same_serialized_result(fresh,stored)
    stored['checks']['FIRE']['distance_m']=39.
    assert not module.same_serialized_result(fresh,stored)
