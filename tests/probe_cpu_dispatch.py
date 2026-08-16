# tests/probe_cpu_dispatch.py — CPU 分派微基准
import time
import torch

x = torch.randn(64, device="cuda")
a = torch.randn(512, 512, device="cuda")
b = torch.randn(512, 512, device="cuda")

N = 200000
t0 = time.perf_counter()
for _ in range(N):
    y = torch.empty(16, device="cuda")
torch.cuda.synchronize()
print(f"torch.empty(16) gpu: {(time.perf_counter() - t0) / N * 1e6:.1f} us/call")

t0 = time.perf_counter()
for _ in range(N):
    y = x * 2
torch.cuda.synchronize()
print(f"mul scalar gpu: {(time.perf_counter() - t0) / N * 1e6:.1f} us/call")

t0 = time.perf_counter()
for _ in range(2000):
    y = a @ b
torch.cuda.synchronize()
print(f"512x512 mm gpu: {(time.perf_counter() - t0) / 2000 * 1e6:.1f} us/call")

xc = torch.randn(64)
t0 = time.perf_counter()
for _ in range(N):
    y = xc * 2
print(f"mul scalar cpu: {(time.perf_counter() - t0) / N * 1e6:.1f} us/call")

import os
os.system("wmic cpu get loadpercentage /value 2>nul | findstr Load")
os.system("powershell -c \"(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples.CookedValue\"")

import torch.utils.benchmark as tbm
m = tbm.Timer("torch.empty(16, device='cuda')", "import torch")
print("benchmark empty:", m.timeit(100000).mean * 1e6, "us")