import json
from pathlib import Path
import struct
import numpy as np
import pytest
from kinectscan.geometry import Intrinsics
from kinectscan.storage import (save_frame,load_frame,write_mesh,write_cloud,new_directory,load_session,write_json)
from kinectscan.synthetic import create_demo
from kinectscan.reconstruct import fuse_known_clouds,reconstruct
from kinectscan.cli import main


def test_frame_roundtrip(tmp_path):
    k=Intrinsics(8,6,100,100,3.5,2.5)
    d=np.full((6,8),1200,np.uint16); p=tmp_path/'frame.npz'
    save_frame(p,d,k,raw=d,timestamp=123,pose=np.eye(4))
    dd,kk,pose=load_frame(p)
    assert np.array_equal(d,dd) and k==kk and np.allclose(pose,np.eye(4))

def test_stl_scale_and_binary_layout(tmp_path):
    v=np.array([[0.,0,0],[.1,0,0],[0,.2,0]]); t=np.array([[0,1,2]])
    p=tmp_path/'test.stl'; write_mesh(p,v,t)
    data=p.read_bytes()
    assert len(data)==134 and struct.unpack('<I',data[80:84])[0]==1
    values=struct.unpack('<12fH',data[84:])
    assert values[6]==100. and values[10]==200.
    assert json.loads(p.with_suffix('.stl.units.json').read_text())['coordinate_units']=='mm'

@pytest.mark.parametrize('ext',['ply','pcd','xyz'])
def test_cloud_exports(tmp_path,ext):
    p=tmp_path/f'cloud.{ext}'; write_cloud(p,np.array([[0,0,1],[1,2,3]]))
    assert 'meters' in p.read_text() and '3.000000000' in p.read_text()

@pytest.mark.parametrize('ext',['obj','ply'])
def test_mesh_exports(tmp_path,ext):
    p=tmp_path/f'mesh.{ext}'
    write_mesh(p,[[0,0,1],[.1,0,1],[0,.1,1]],[[0,1,2]])
    assert 'meters' in p.read_text()

def test_refuse_overwrite(tmp_path):
    (tmp_path/'existing').write_text('x')
    with pytest.raises(FileExistsError): new_directory(tmp_path)

def test_session_refuses_traversal(tmp_path):
    write_json(tmp_path/'session.json',{'schema_version':1,'frames':[{'path':'../secret.npz'}]})
    with pytest.raises(ValueError): load_session(tmp_path)

def test_synthetic_known_fusion(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    report=fuse_known_clouds(tmp_path/'session',tmp_path/'out',.004)
    assert np.allclose(report['aabb_extent_mm'],[400,400,200],atol=15.)
    assert (tmp_path/'out'/'fused_known_points.ply').is_file()

def test_static_mode_refuses_rotating_scene_before_open3d_import(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    with pytest.raises(ValueError,match='stationary'):
        reconstruct(tmp_path/'session',tmp_path/'out','static')

def test_snapshot_cli_without_hardware(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    rc=main(['snapshot','--input',str(tmp_path/'session/frames/000000.npz'),
             '--out',str(tmp_path/'snapshot'),'--stride','1'])
    assert rc==0 and (tmp_path/'snapshot/observed_mesh.stl').is_file()
    rc=main(['measure','--input',str(tmp_path/'snapshot/frame.npz'),
             '--p1','75','60','--p2','85','60','--out',str(tmp_path/'distance.json')])
    assert rc==0
    assert json.loads((tmp_path/'distance.json').read_text())['distance_mm']>0

def test_invalid_measurement_fails(tmp_path):
    create_demo(tmp_path/'session',step_deg=20)
    assert main(['measure','--input',str(tmp_path/'session/frames/000000.npz'),
                 '--p1','0','0','--p2','1','1'])==2
