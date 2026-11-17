"""Executed only when Open3D is installed; absence must be reported, not hidden."""
import pytest
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import reconstruct


def test_open3d_known_pose_tsdf(tmp_path):
    pytest.importorskip('open3d',reason='Open3D unavailable: TSDF hardware-independent test not executed')
    create_demo(tmp_path/'session',step_deg=20)
    result=reconstruct(tmp_path/'session',tmp_path/'mesh','known',voxel_m=.008)
    assert result['frames_integrated']==19
    assert (tmp_path/'mesh/fused_mesh.stl').is_file()
    assert 350 < result['aabb_extent_mm'][0] < 450
