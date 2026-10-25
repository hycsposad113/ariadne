"""Fast geometry checks for E3; these tests never invoke EnergyPlus."""

import unittest

from honeybee.model import Model
from honeybee.boundarycondition import Surface
from honeybee_energy.boundarycondition import Adiabatic
from honeybee_energy.lib.constructionsets import construction_set_by_identifier
from shapely.geometry import box

from scripts.e3_fabric_energy import (
    BuildingInput,
    _building_rooms,
    _set_shared_walls_adiabatic,
)


class FabricEnergyGeometryTests(unittest.TestCase):
    def setUp(self):
        self.buildings = [
            BuildingInput(
                "new-a", box(0, 0, 10, 10), {"id": "new-a"}, "residential",
                "2019::MidriseApartment::Apartment", 1, 3.0, (3.0,), 100.0, 0.0,
            ),
            BuildingInput(
                "new-b", box(10, 0, 20, 10), {"id": "new-b"}, "residential",
                "2019::MidriseApartment::Apartment", 1, 3.0, (3.0,), 100.0, 0.0,
            ),
        ]

    def test_adjacent_buildings_get_adiabatic_shared_wall_and_area(self):
        construction = construction_set_by_identifier("2019::ClimateZone5::Mass")
        rooms, _metadata, room_count = _building_rooms(
            self.buildings, 0.0, 0.0, construction, cooling_enabled=True,
        )

        adjacency = _set_shared_walls_adiabatic(self.buildings, rooms)
        model = Model("Two_Building_Test", rooms=rooms)
        adiabatic_faces = [
            face for room in rooms for face in room.faces
            if isinstance(face.boundary_condition, Adiabatic)
        ]

        self.assertEqual(room_count, 2)
        self.assertEqual(adjacency["shared_footprint_pairs"], 1)
        self.assertEqual(adjacency["adiabatic_wall_surfaces"], 2)
        self.assertEqual(len(adiabatic_faces), 2)
        self.assertTrue(all(face.type.name == "Wall" for face in adiabatic_faces))
        self.assertAlmostEqual(model.floor_area, 200.0, places=6)

    def test_interstory_surfaces_remain_surface_adjacencies(self):
        building = BuildingInput(
            "new-tall", box(0, 0, 10, 10), {"id": "new-tall"}, "residential",
            "2019::MidriseApartment::Apartment", 2, 6.0, (3.0, 3.0), 100.0, 0.0,
        )
        construction = construction_set_by_identifier("2019::ClimateZone5::Mass")
        rooms, _metadata, room_count = _building_rooms(
            [building], 0.0, 0.0, construction, cooling_enabled=True,
        )
        self.assertEqual(room_count, 2)
        self.assertAlmostEqual(Model("Two_Storey_Test", rooms=rooms).floor_area, 200.0, places=6)
        horizontal_surface_faces = [
            face for room in rooms for face in room.faces
            if isinstance(face.boundary_condition, Surface)
            and abs(float(face.geometry.normal.z)) > 0.99
        ]
        self.assertEqual(len(horizontal_surface_faces), 4)


if __name__ == "__main__":
    unittest.main()
