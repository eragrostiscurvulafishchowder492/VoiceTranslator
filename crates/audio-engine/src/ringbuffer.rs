//! SPSC 环形缓冲：音频回调 ↔ 工作线程。f32 以位模式存 AtomicU32，无锁。
pub struct RingBuffer {
    buf: Box<[std::sync::atomic::AtomicU32]>,
    cap: usize,
    head: std::sync::atomic::AtomicUsize,
    tail: std::sync::atomic::AtomicUsize,
    overflows: std::sync::atomic::AtomicU64,
    underruns: std::sync::atomic::AtomicU64,
}

impl RingBuffer {
    pub fn new(cap_pow2: usize) -> Self {
        let cap = cap_pow2.max(2).next_power_of_two();
        Self {
            buf: (0..cap)
                .map(|_| std::sync::atomic::AtomicU32::new(0))
                .collect(),
            cap,
            head: std::sync::atomic::AtomicUsize::new(0),
            tail: std::sync::atomic::AtomicUsize::new(0),
            overflows: std::sync::atomic::AtomicU64::new(0),
            underruns: std::sync::atomic::AtomicU64::new(0),
        }
    }

    fn len_of(&self, head: usize, tail: usize) -> usize {
        head.wrapping_sub(tail) & (self.cap - 1)
    }

    /// 生产端（回调线程）。溢出时丢弃（记录 overflow）。
    pub fn push(&self, data: &[f32]) {
        use std::sync::atomic::Ordering;
        let mut head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        for &s in data {
            if self.len_of(head, tail) >= self.cap - 1 {
                self.overflows.fetch_add(1, Ordering::Relaxed);
                return; // 丢整块，保持实时性
            }
            self.buf[head].store(s.to_bits(), Ordering::Relaxed);
            head = (head + 1) & (self.cap - 1);
        }
        self.head.store(head, Ordering::Release);
    }

    /// 消费端（工作线程）。空时返回 0 并记录 underrun。
    pub fn pop(&self, out: &mut [f32]) -> usize {
        use std::sync::atomic::Ordering;
        let mut tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);
        let avail = self.len_of(head, tail);
        if avail == 0 {
            self.underruns.fetch_add(1, Ordering::Relaxed);
            return 0;
        }
        let n = out.len().min(avail);
        for slot in out.iter_mut().take(n) {
            *slot = f32::from_bits(self.buf[tail].load(Ordering::Relaxed));
            tail = (tail + 1) & (self.cap - 1);
        }
        self.tail.store(tail, Ordering::Release);
        n
    }

    pub fn available(&self) -> usize {
        use std::sync::atomic::Ordering;
        let head = self.head.load(Ordering::Acquire);
        let tail = self.tail.load(Ordering::Acquire);
        self.len_of(head, tail)
    }

    pub fn stats(&self) -> (u64, u64) {
        (
            self.overflows.load(std::sync::atomic::Ordering::Relaxed),
            self.underruns.load(std::sync::atomic::Ordering::Relaxed),
        )
    }
}
