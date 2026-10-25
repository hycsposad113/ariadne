import os
import tempfile

from urban_design.environment import sunlight


def test_radiance_uses_private_per_process_folder_not_shared_tmp():
    folder = sunlight._radiance_sim_folder()
    assert os.path.isdir(folder)
    assert os.path.realpath(folder) != os.path.realpath(tempfile.gettempdir())
    assert os.path.basename(folder).startswith('urban-design-radiance-')
    assert sunlight._radiance_sim_folder() == folder
