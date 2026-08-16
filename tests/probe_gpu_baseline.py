# tests/probe_gpu_baseline.py — GPU 原始能力基准：大 GEMM / 小 GEMM 串行 / 大 GEMM 串行
import time
import torch

dev = torch.device("cuda")

def bench(name, fn, n=50):
    for _ in range(5):
        fn()
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / n * 1000
    print(f"{name}: {dt:.2f} ms/iter")
    return dt

a = torch.randn(4096, 4096, device=dev, dtype=torch.float16)
b = torch.randn(4096, 4096, device=dev, dtype=torch.float16)
bench("4096x4096 fp16 mm", lambda: a @ b)

a32 = a.float()
b32 = b.float()
bench("4096x4096 fp32 mm", lambda: a32 @ b32)

w = torch.randn(896, 4864, device=dev, dtype=torch.float16)
x = torch.randn(1, 1, 896, device=dev, dtype=torch.float16)
bench("tiny 1x896x4864 mm", lambda: x @ w, n=200)

# 串行 150 个小核
def tiny_chain():
    y = x
    for _ in range(150):
        y = y @ w
    return y
bench("150 tiny mm chain", tiny_chain, n=20)

# 大量小 kernel 模拟 transformer 步进
def kernel_spray():
    y = x
    for _ in range(300):
        y = y * 1.0001 + 1e-7
    return y
bench("300 tiny elementwise", kernel_spray, n=20)

print("clock_rate:", torch.cuda.clock_rate() if hasattr(torch.cuda, "clock_rate") else "n/a")
print("gpu name:", torch.cuda.get_device_name(0))
print("cap:", torch.cuda.get_device_capability(0))