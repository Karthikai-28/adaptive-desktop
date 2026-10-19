#!/usr/bin/env python3
"""Asynchronous GPU metrics sampler for Adaptive Desktop.

Queries NVIDIA GPU state via NVML (libnvidia-ml) or nvidia-smi with zero-overhead
streaming for the GNOME Shell system monitor indicator.
"""
import ctypes
import json
import os
import select
import subprocess
import sys
import time


class GpuSampler:
    def __init__(self):
        self.backend = None
        self.name = ""
        self.driver = ""
        self._init_nvml()
        if not self.backend:
            self._check_nvidia_smi()

    def _init_nvml(self):
        try:
            nvml = ctypes.CDLL("libnvidia-ml.so.1")
            if nvml.nvmlInit() == 0:
                handle = ctypes.c_void_p()
                if nvml.nvmlDeviceGetHandleByIndex(0, ctypes.byref(handle)) == 0:
                    name_buf = ctypes.create_string_buffer(64)
                    nvml.nvmlDeviceGetName(handle, name_buf, 64)
                    driver_buf = ctypes.create_string_buffer(64)
                    try:
                        nvml.nvmlSystemGetDriverVersion(driver_buf, 64)
                        driver = driver_buf.value.decode("utf-8", errors="replace").strip()
                    except Exception:
                        driver = ""
                    self.backend = "nvml"
                    self.nvml = nvml
                    self.handle = handle
                    self.name = name_buf.value.decode("utf-8", errors="replace").strip()
                    self.driver = driver
        except Exception:
            self.backend = None

    def _check_nvidia_smi(self):
        try:
            res = subprocess.run(["which", "nvidia-smi"], capture_output=True, text=True)
            if res.returncode == 0:
                self.backend = "smi"
        except Exception:
            self.backend = None

    def sample(self):
        if self.backend == "nvml":
            try:
                class Memory(ctypes.Structure):
                    _fields_ = [
                        ("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong),
                        ("used", ctypes.c_ulonglong),
                    ]

                class Utilization(ctypes.Structure):
                    _fields_ = [
                        ("gpu", ctypes.c_uint),
                        ("memory", ctypes.c_uint),
                    ]

                mem = Memory()
                util = Utilization()
                temp = ctypes.c_uint()
                clock = ctypes.c_uint()

                self.nvml.nvmlDeviceGetMemoryInfo(self.handle, ctypes.byref(mem))
                self.nvml.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(util))
                self.nvml.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(temp))
                self.nvml.nvmlDeviceGetClockInfo(self.handle, 0, ctypes.byref(clock))

                return {
                    "available": True,
                    "name": self.name,
                    "driver": self.driver,
                    "percent": int(util.gpu),
                    "vramUsedBytes": int(mem.used),
                    "vramTotalBytes": int(mem.total),
                    "vramFreeBytes": int(mem.free),
                    "tempC": int(temp.value),
                    "freqMhz": int(clock.value),
                }
            except Exception:
                pass
        elif self.backend == "smi":
            try:
                out = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,clocks.current.graphics,driver_version",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=2,
                ).strip()
                parts = [p.strip() for p in out.split(",")]
                if len(parts) >= 7:
                    total_mb = int(parts[3])
                    used_mb = int(parts[2])
                    return {
                        "available": True,
                        "name": parts[0],
                        "driver": parts[6],
                        "percent": int(parts[1]),
                        "vramUsedBytes": used_mb * 1024 * 1024,
                        "vramTotalBytes": total_mb * 1024 * 1024,
                        "vramFreeBytes": max(0, total_mb - used_mb) * 1024 * 1024,
                        "tempC": int(parts[4]),
                        "freqMhz": int(parts[5]),
                    }
            except Exception:
                pass

        return {"available": False}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    sampler = GpuSampler()

    if mode == "once":
        sys.stdout.write(json.dumps(sampler.sample()) + "\n")
        sys.stdout.flush()
        return

    if mode == "stream":
        while True:
            # Check for input or EOF on stdin
            try:
                rlist, _, _ = select.select([sys.stdin], [], [], 0)
                if rlist:
                    line = sys.stdin.readline()
                    if not line or line.strip() == "quit":
                        break
            except Exception:
                break

            data = sampler.sample()
            sys.stdout.write(json.dumps(data) + "\n")
            sys.stdout.flush()
            time.sleep(1.0)


if __name__ == "__main__":
    main()
