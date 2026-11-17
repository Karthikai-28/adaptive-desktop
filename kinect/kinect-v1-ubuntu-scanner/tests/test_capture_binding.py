import ctypes as ct
import numpy as np
from kinectscan import capture

class Fn:
    def __init__(self,f): self.f=f
    def __call__(self,*args): return self.f(*args)

class FakeLib:
    def __init__(self):
        self.data=np.full((480,640),1234,np.uint16)
        self.data[0,0]=10000
        self.freenect_sync_get_depth=Fn(self.read)
        self.freenect_sync_stop=Fn(lambda: None)
        self.freenect_sync_camera_to_world=Fn(self.project)
    def read(self,ptr,stamp,index,fmt):
        assert fmt==5
        ct.cast(ptr,ct.POINTER(ct.c_void_p))[0]=self.data.ctypes.data
        ct.cast(stamp,ct.POINTER(ct.c_uint32))[0]=77
        return 0
    def project(self,u,v,z,x,y,index):
        ct.cast(x,ct.POINTER(ct.c_double))[0]=(u-320)*z/580.
        ct.cast(y,ct.POINTER(ct.c_double))[0]=(v-240)*z/581.
        return 0

def test_native_binding_copy_and_factory_intrinsics(monkeypatch):
    fake=FakeLib()
    monkeypatch.setattr(capture,'library_path',lambda:'fake')
    monkeypatch.setattr(capture.ct,'CDLL',lambda name:fake)
    device=capture._Native(0)
    depth,stamp=device.read()
    assert stamp==77 and depth[0,0]==0
    fake.data[1,1]=900
    assert depth[1,1]==1234
    k=device.intrinsics()
    assert np.allclose([k.fx,k.fy,k.cx,k.cy],[580,581,320,240])

def test_missing_library(monkeypatch):
    monkeypatch.setattr(capture,'library_path',lambda:None)
    import pytest
    with pytest.raises(RuntimeError,match='not found'): capture._Native(0)
