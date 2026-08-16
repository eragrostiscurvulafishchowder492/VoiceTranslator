"""线程安全 ring buffer（numpy float32）。"""
import threading
import numpy as np


class RingBuffer:
    def __init__(self, capacity: int, channels: int = 1):
        self._buf = np.zeros((capacity, channels), dtype=np.float32)
        self._cap = capacity
        self._ch = channels
        self._head = 0   # 写位置
        self._tail = 0   # 读位置
        self._count = 0
        self._lock = threading.Lock()
        self.overflows = 0

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def push(self, data: np.ndarray) -> None:
        """data: (n,) 或 (n, channels) float32"""
        data = np.ascontiguousarray(data, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        n = data.shape[0]
        if n <= 0:
            return
        with self._lock:
            if n >= self._cap:
                # 超出容量：直接丢弃旧数据
                data = data[-self._cap:]
                n = self._cap
                self._head = (self._tail + self._cap) % self._cap
                self._count = self._cap
                self.overflows += 1
                self._buf[:] = data
                return
            room = self._cap - self._count
            if n > room:
                self._tail = (self._tail + (n - room)) % self._cap
                self._count = self._cap - n + n
                self.overflows += 1
            self._count = min(self._count + n, self._cap)
            self._write(data, self._head)
            self._head = (self._head + n) % self._cap

    def pop(self, n: int) -> np.ndarray:
        with self._lock:
            n = min(n, self._count)
            if n <= 0:
                return np.zeros((0, self._ch), dtype=np.float32)
            out = self._read(n, self._tail)
            self._tail = (self._tail + n) % self._cap
            self._count -= n
            return out

    def peek(self, n: int) -> np.ndarray:
        with self._lock:
            n = min(n, self._count)
            if n <= 0:
                return np.zeros((0, self._ch), dtype=np.float32)
            return self._read(n, self._tail)

    def clear(self) -> None:
        with self._lock:
            self._head = self._tail = self._count = 0

    def _write(self, data: np.ndarray, pos: int) -> None:
        first = min(data.shape[0], self._cap - pos)
        self._buf[pos: pos + first] = data[:first]
        if first < data.shape[0]:
            self._buf[0: data.shape[0] - first] = data[first:]

    def _read(self, n: int, pos: int) -> np.ndarray:
        first = min(n, self._cap - pos)
        out = np.empty((n, self._ch), dtype=np.float32)
        out[:first] = self._buf[pos: pos + first]
        if first < n:
            out[first:] = self._buf[0: n - first]
        return out