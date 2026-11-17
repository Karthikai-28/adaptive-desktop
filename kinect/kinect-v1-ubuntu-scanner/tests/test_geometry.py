import numpy as np
import pytest
from kinectscan.geometry import (Intrinsics, depth_to_xyz, median_depth, segment_depth,
    grid_mesh, transform_points, turntable_pose, rotation_axis_angle,
    fit_axis_circle, validate_transform, voxel_average, measurement_report)

@pytest.fixture
def k():
    return Intrinsics(8,6,100,100,3.5,2.5,source="test")

def test_projection_units(k):
    d=np.full((6,8),1000,np.uint16)
    p=depth_to_xyz(d,k)
    assert np.allclose(p[2,3],[-.005,-.005,1.])
    assert np.isclose(np.linalg.norm(p[2,3]-p[2,4]),.01)

@pytest.mark.parametrize("value",[0,10000,65535])
def test_invalid_depth_is_not_origin(k,value):
    d=np.full((6,8),value,np.uint16)
    assert np.isnan(depth_to_xyz(d,k)).all()

@pytest.mark.parametrize("fx",[0,-1,float('nan'),float('inf')])
def test_intrinsics_validation(fx):
    with pytest.raises(ValueError): Intrinsics(640,480,fx,580,320,240)

def test_depth_shape_type(k):
    with pytest.raises(ValueError): depth_to_xyz(np.ones((6,8)),k)
    with pytest.raises(ValueError): depth_to_xyz(np.ones((8,6),np.uint16),k)

def test_median_missing_values():
    frames=[np.array([[1000,0],[1000,1000]],np.uint16),
            np.array([[1002,0],[0,1300]],np.uint16),
            np.array([[998,1000],[1000,700]],np.uint16)]
    out=median_depth(frames,max_std_mm=10)
    assert out.tolist()==[[1000,0],[0,0]]

def test_segmentation_signed_background(k):
    d=np.full((6,8),1000,np.uint16); bg=np.full_like(d,900)
    assert not segment_depth(d,k,background=bg).any()
    bg[:]=1100; bg[0,0]=0
    out=segment_depth(d,k,background=bg)
    assert out[0,0]==0 and np.count_nonzero(out)==47

def test_roi_and_box(k):
    d=np.full((6,8),1000,np.uint16)
    out=segment_depth(d,k,roi=[2,1,6,5],box=[-.02,.02,-.02,.02,.8,1.2])
    assert np.count_nonzero(out)==16

def test_bad_roi_and_range(k):
    d=np.full((6,8),1000,np.uint16)
    with pytest.raises(ValueError): segment_depth(d,k,roi=[-1,0,4,5])
    with pytest.raises(ValueError): segment_depth(d,k,z_min=2,z_max=1)

def test_largest_component(k):
    d=np.zeros((6,8),np.uint16); d[:2,:2]=1000; d[4,6]=1000
    out=segment_depth(d,k,largest_component=True)
    assert np.count_nonzero(out)==4

def test_grid_mesh_plane(k):
    d=np.full((6,8),1000,np.uint16)
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.02)
    assert len(v)==48 and len(t)==70
    normals=np.cross(v[t[:,1]]-v[t[:,0]],v[t[:,2]]-v[t[:,0]])
    assert (normals[:,2]<0).all()

def test_grid_mesh_does_not_bridge_step(k):
    d=np.full((6,8),1000,np.uint16); d[:,4:]=2000
    v,t=grid_mesh(d,k,stride=1,max_edge_m=.04)
    assert np.all(np.ptp(v[t][:,:,2],axis=1)==0)

def test_grid_mesh_does_not_fill_invalid(k):
    d=np.full((6,8),1000,np.uint16); d[:,3:5]=0
    v,t=grid_mesh(d,k,stride=1,max_edge_m=1.)
    assert len(t)>0
    assert (np.ptp(v[t][:,:,0],axis=1)<.02).all()

def test_turntable_inverse_transform():
    c=np.array([.02,.1,1.3]); axis=[0,-1,0]; angle=43
    r=rotation_axis_angle(axis,np.deg2rad(angle))
    original=np.array([[.12,.1,1.25],[-.2,0,1.4]])
    rotated=(original-c)@r.T+c
    assert np.allclose(transform_points(rotated,turntable_pose(angle,c,axis)),original)
    assert np.allclose(turntable_pose(360,c,axis),np.eye(4))

def test_transform_rejects_scale_and_reflection():
    t=np.eye(4); t[0,0]=2
    with pytest.raises(ValueError): validate_transform(t)
    t[0,0]=-1
    with pytest.raises(ValueError): validate_transform(t)

def test_axis_fit():
    theta=np.linspace(0,2*np.pi,12,endpoint=False)
    center=np.array([.1,.2,1.4])
    p=center+np.column_stack((.1*np.cos(theta),np.zeros(12),.1*np.sin(theta)))
    result=fit_axis_circle(p)
    assert np.allclose(result['center_m'],center)
    assert np.allclose(result['axis'],[0,-1,0])
    assert result['rms_residual_mm']<1e-6
    assert result['observed_arc_deg']>=329.9

def test_axis_fit_rejects_line():
    with pytest.raises(ValueError): fit_axis_circle(np.column_stack((np.arange(6),np.zeros(6),np.ones(6))))

def test_voxel_average():
    p=np.array([[.001,0,1],[.003,0,1],[-.001,0,1]])
    fused=voxel_average(p,.01)
    assert len(fused)==2
    assert np.allclose(np.sort(fused[:,0]),[-.001,.002])

def test_measurement_report_is_observed_only():
    p=np.array([[0,0,0],[.4,.3,.2],[.4,0,0],[0,.3,.2]])
    r=measurement_report(p)
    assert np.allclose(r['aabb_extent_mm'],[400,300,200])
    assert r['scope']=='observed_surfaces_only'
    assert 'volume' not in r
