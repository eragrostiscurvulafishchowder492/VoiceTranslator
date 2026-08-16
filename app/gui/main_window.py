"""PySide6 主窗口。GUI 线程绝不执行 ML 推理。"""
import json
import queue
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout,
    QWidget, QGridLayout, QButtonGroup,
)

from app.audio import devices as dev
from app.common import get_logger, now_ms
from app.config import AppSettings
from app.diagnostics import gpu as gpu_diag
from app.pipeline.orchestrator import Orchestrator

log = get_logger("gui")


class Bus(QObject):
    """线程安全事件总线（Qt signal）。"""
    ev = Signal(str, object)


class VoiceLabWorker(QThread):
    """Voice Lab 生成线程（不阻塞 GUI）。"""
    done = Signal(str, str, str)   # key, out_path, info
    failed = Signal(str, str)      # key, error

    def __init__(self, engine_name: str, key: str, text: str, style, ref: dict, out_dir: Path):
        super().__init__()
        self.engine_name = engine_name
        self.key = key
        self.text = text
        self.style = style
        self.ref = ref
        self.out_dir = out_dir

    def run(self):
        from app.tts.cosyvoice import CosyVoiceEngine
        from app.tts.fishspeech import FishSpeechEngine
        try:
            if self.engine_name == "fish":
                engine = FishSpeechEngine()
            else:
                engine = CosyVoiceEngine()
            engine.load_reference(self.ref["path"], self.ref.get("text", ""))
            out = self.out_dir / f"voicelab_{self.key}.wav"
            info = engine.synth_to_wav(self.text, self.style, str(out))
            ttfa = getattr(engine, "ttfa_ms", 0)
            gen = getattr(engine, "gen_ms", 0)
            engine.unload()
            self.done.emit(self.key, str(out), f"TTFA={ttfa}ms 生成={gen}ms")
        except Exception as e:
            log.error("voicelab %s failed: %s", self.key, e, exc_info=True)
            self.failed.emit(self.key, str(e))


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.s = settings
        self.setWindowTitle("Real-Time Voice — 实时语音转换")
        self.resize(860, 640)
        self.bus = Bus()
        self.orch: Orchestrator | None = None
        self._devices = dev.refresh_devices()
        self._hotkey_thread: threading.Thread | None = None
        self._hotkey_stop = threading.Event()
        self._voicelab_workers: list[VoiceLabWorker] = []
        self._debug_lines = []
        self._muted = False
        self._build_ui()
        self._apply_settings()
        self._start_hotkeys()

    # ---------------- UI 构建 ----------------
    def _build_ui(self):
        tabs = QTabWidget()
        tabs.addTab(self._build_live_tab(), "Live")
        tabs.addTab(self._build_voice_tab(), "Voice")
        tabs.addTab(self._build_audio_tab(), "Audio")
        tabs.addTab(self._build_asr_tab(), "ASR")
        tabs.addTab(self._build_tts_tab(), "TTS")
        tabs.addTab(self._build_voicelab_tab(), "Voice Lab")
        tabs.addTab(self._build_debug_tab(), "Debug")
        self.tabs = tabs
        self.setCentralWidget(tabs)

    def _build_live_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        g1 = QGroupBox("设备")
        f = QFormLayout(g1)
        self.cb_mic = QComboBox()
        self.cb_out = QComboBox()
        self.cb_mon = QComboBox()
        self.btn_refresh = QPushButton("刷新设备")
        self.btn_refresh.clicked.connect(self._refresh_devices)
        f.addRow("麦克风", self.cb_mic)
        f.addRow("虚拟输出 (VB-CABLE)", self.cb_out)
        f.addRow("监听设备", self.cb_mon)
        f.addRow(self.btn_refresh)
        v.addWidget(g1)
        self.lbl_cable = QLabel()
        self.lbl_cable.setStyleSheet("color: #c77;")
        v.addWidget(self.lbl_cable)

        g2 = QGroupBox("参考声音")
        f2 = QFormLayout(g2)
        self.cb_ref = QComboBox()
        self.btn_import_ref = QPushButton("导入 WAV…")
        self.btn_import_ref.clicked.connect(self._import_reference)
        f2.addRow("Profile", self.cb_ref)
        f2.addRow(self.btn_import_ref)
        self.lbl_ref_quality = QLabel("未加载参考音频")
        f2.addRow(self.lbl_ref_quality)
        v.addWidget(g2)

        g3 = QGroupBox("模式")
        h = QHBoxLayout(g3)
        self.radio_ptt = QRadioButton("Push-to-talk")
        self.radio_always = QRadioButton("Always listening")
        self.btn_mode = QButtonGroup(self)
        self.btn_mode.addButton(self.radio_ptt)
        self.btn_mode.addButton(self.radio_always)
        h.addWidget(self.radio_ptt)
        h.addWidget(self.radio_always)
        v.addWidget(g3)

        g4 = QGroupBox("运行")
        h4 = QHBoxLayout(g4)
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self._toggle_start)
        self.btn_mute = QPushButton("静音 (F9)")
        self.btn_mute.clicked.connect(self._toggle_mute)
        self.btn_clear = QPushButton("清队列 (F10)")
        self.btn_clear.clicked.connect(lambda: self.orch.clear_queue() if self.orch else None)
        self.btn_int = QPushButton("打断 (F11)")
        self.btn_int.clicked.connect(lambda: self.orch.interrupt() if self.orch else None)
        h4.addWidget(self.btn_start)
        h4.addWidget(self.btn_mute)
        h4.addWidget(self.btn_clear)
        h4.addWidget(self.btn_int)
        v.addWidget(g4)

        g5 = QGroupBox("Live")
        v5 = QVBoxLayout(g5)
        self.lbl_partial = QLabel("Partial: ")
        self.lbl_stable = QLabel("Stable: ")
        self.lbl_tts = QLabel("TTS: ")
        self.lbl_lat = QLabel("Latency: --    GPU: --")
        self.lbl_stats = QLabel("")
        v5.addWidget(self.lbl_partial)
        v5.addWidget(self.lbl_stable)
        v5.addWidget(self.lbl_tts)
        v5.addWidget(self.lbl_lat)
        v5.addWidget(self.lbl_stats)
        v.addWidget(g5)
        v.addStretch()
        return w

    def _build_voice_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("目标音色风格 (Target Style)")
        f = QFormLayout(g)
        self.sld_speed = self._slider(0.85, 1.15, 100)
        self.lbl_speed = QLabel("0.95x")
        f.addRow("语速", self._row(self.sld_speed, self.lbl_speed, 0.85, 1.15, self._save_voice))
        self.sld_energy = self._slider(0.3, 1.6, 100)
        self.lbl_energy = QLabel("0.9")
        f.addRow("能量", self._row(self.sld_energy, self.lbl_energy, 0.3, 1.6, self._save_voice))
        self.sld_pitch = self._slider(-3, 3, 10)
        self.lbl_pitch = QLabel("0")
        f.addRow("音高偏移", self._row(self.sld_pitch, self.lbl_pitch, -3, 3, self._save_voice))
        self.cb_emotion = QComboBox()
        self.cb_emotion.addItems(["calm", "neutral", "soft"])
        f.addRow("情感", self.cb_emotion)
        self.cb_textmode = QComboBox()
        self.cb_textmode.addItems(["gaming", "normal"])
        f.addRow("文本模式", self.cb_textmode)
        self.lbl_style_note = QLabel(
            "说明：音色由参考音频决定，音高/能量在安全范围内微调；\n"
            "不建议强行升调（会破坏自然度）。语速非 1.0 时 CosyVoice 切非流式。")
        self.lbl_style_note.setWordWrap(True)
        f.addRow(self.lbl_style_note)
        v.addWidget(g)
        v.addStretch()
        return w

    def _build_audio_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("音频")
        f = QFormLayout(g)
        self.sp_sr = QSpinBox()
        self.sp_sr.setRange(44100, 48000)
        self.sp_sr.setSingleStep(1000)
        f.addRow("输出采样率", self.sp_sr)
        self.sp_block = QSpinBox()
        self.sp_block.setRange(5, 100)
        f.addRow("采集块 (ms)", self.sp_block)
        self.sp_gain = QDoubleSpinBox()
        self.sp_gain.setRange(-12, 24)
        self.sp_gain.setSingleStep(1)
        f.addRow("输入增益 (dB)", self.sp_gain)
        self.chk_monitor = QCheckBox("监听生成的语音（耳机）")
        f.addRow(self.chk_monitor)
        self.lbl_mon_note = QLabel("开启后 TTS 同时输出到 VB-CABLE 与监听设备；监听音频不会回灌 ASR。")
        self.lbl_mon_note.setWordWrap(True)
        f.addRow(self.lbl_mon_note)
        v.addWidget(g)
        v.addStretch()
        return w

    def _build_asr_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("ASR (FunASR streaming)")
        f = QFormLayout(g)
        self.sld_vad = self._slider(0.1, 0.9, 100)
        self.lbl_vad = QLabel("0.5")
        f.addRow("VAD 阈值", self._row(self.sld_vad, self.lbl_vad, 0.1, 0.9, self._save_asr))
        self.sp_stable = QSpinBox()
        self.sp_stable.setRange(1, 10)
        f.addRow("稳定轮数", self.sp_stable)
        self.sp_maxchars = QSpinBox()
        self.sp_maxchars.setRange(4, 60)
        f.addRow("最大片段字数", self.sp_maxchars)
        self.sp_timeout = QSpinBox()
        self.sp_timeout.setRange(300, 5000)
        self.sp_timeout.setSingleStep(100)
        f.addRow("强制 flush 超时 (ms)", self.sp_timeout)
        self.ed_hotwords = QLineEdit()
        f.addRow("热词 (逗号分隔)", self.ed_hotwords)
        self.chk_punc = QCheckBox("段尾标点模型 (ct-punc, 增加延迟)")
        f.addRow(self.chk_punc)
        v.addWidget(g)
        v.addStretch()
        return w

    def _build_tts_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("TTS")
        f = QFormLayout(g)
        self.cb_tts = QComboBox()
        self.cb_tts.addItem("CosyVoice 3", "cosyvoice")
        self.cb_tts.addItem("Fish Speech 1.5", "fish")
        f.addRow("引擎", self.cb_tts)
        self.cb_vram = QComboBox()
        self.cb_vram.addItem("balanced (ASR+TTS 均 GPU)", "balanced")
        self.cb_vram.addItem("asr_cpu (ASR 走 CPU)", "asr_cpu")
        f.addRow("显存模式", self.cb_vram)
        self.btn_switch = QPushButton("应用引擎/显存设置")
        self.btn_switch.clicked.connect(self._apply_engine_settings)
        f.addRow(self.btn_switch)
        self.lbl_tts_note = QLabel(
            "CosyVoice3 0.5B：默认引擎，日语参考→中文输出，streaming。\n"
            "Fish Speech 1.5：对照引擎（非流式，整句生成）。\n"
            "Fish Audio S2 官方要求 ≥24GB 显存，4060 Laptop 不可行。")
        self.lbl_tts_note.setWordWrap(True)
        f.addRow(self.lbl_tts_note)
        v.addWidget(g)
        v.addStretch()
        return w

    def _build_voicelab_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("Voice Lab — A/B 对比")
        f = QFormLayout(g)
        self.ed_vlab = QPlainTextEdit()
        self.ed_vlab.setPlainText("我不知道……应该可以吧。")
        self.ed_vlab.setMaximumHeight(80)
        f.addRow("文本", self.ed_vlab)
        h = QHBoxLayout()
        self.btn_vlab_a = QPushButton("▶ A: CosyVoice 3")
        self.btn_vlab_b = QPushButton("▶ B: Fish Speech")
        self.btn_vlab_a.clicked.connect(lambda: self._voicelab("A", "cosyvoice"))
        self.btn_vlab_b.clicked.connect(lambda: self._voicelab("B", "fish"))
        h.addWidget(self.btn_vlab_a)
        h.addWidget(self.btn_vlab_b)
        f.addRow(h)
        self.lbl_vlab_a = QLabel("A: --")
        self.lbl_vlab_b = QLabel("B: --")
        f.addRow(self.lbl_vlab_a)
        f.addRow(self.lbl_vlab_b)
        v.addWidget(g)
        v.addStretch()
        return w

    def _build_debug_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("诊断")
        f = QFormLayout(g)
        self.lbl_dbg_stats = QLabel("")
        f.addRow(self.lbl_dbg_stats)
        self.btn_diag = QPushButton("运行一键诊断 (GPU/设备)")
        self.btn_diag.clicked.connect(self._run_diag)
        f.addRow(self.btn_diag)
        v.addWidget(g)
        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        v.addWidget(self.txt_log)
        return w

    def _slider(self, lo: float, hi: float, steps: int) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(int(lo * steps), int(hi * steps))
        s.setValue(int(0.5 * steps))
        return s

    def _row(self, slider: QSlider, label: QLabel, lo: float, hi: float, cb) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(slider)
        h.addWidget(label)
        steps_param = (slider.maximum() - slider.minimum()) / (hi - lo)
        slider.valueChanged.connect(
            lambda _v, s=slider, l=label, p=steps_param, c=cb: (
                l.setText(f"{round(s.value() / p, 4)}"), c()))
        return row

    # ---------------- 设置读取/保存 ----------------
    def _apply_settings(self):
        self.sp_sr.setValue(self.s.output_sample_rate)
        self.sp_block.setValue(self.s.input_block_ms)
        self.sp_gain.setValue(self.s.input_gain_db)
        self.chk_monitor.setChecked(self.s.monitor_enabled)
        self.sp_stable.setValue(self.s.stable_rounds)
        self.sp_maxchars.setValue(self.s.max_segment_chars)
        self.sp_timeout.setValue(self.s.flush_timeout_ms)
        self.ed_hotwords.setText(self.s.asr_hotwords)
        self.chk_punc.setChecked(self.s.asr_punc_model)
        self.sld_vad.setValue(int(self.s.vad_threshold * 100))
        self.lbl_vad.setText(f"{self.s.vad_threshold}")
        idx = self.cb_tts.findData(self.s.tts_engine)
        if idx >= 0:
            self.cb_tts.setCurrentIndex(idx)
        idx = self.cb_vram.findData(self.s.vram_mode)
        if idx >= 0:
            self.cb_vram.setCurrentIndex(idx)
        if self.s.listen_mode == "always":
            self.radio_always.setChecked(True)
        else:
            self.radio_ptt.setChecked(True)
        self.sld_speed.setValue(int(self.s.speaking_speed * 100))
        self.lbl_speed.setText(f"{self.s.speaking_speed}x")
        self.sld_energy.setValue(int(self.s.energy * 100))
        self.lbl_energy.setText(f"{self.s.energy}")
        self.sld_pitch.setValue(int(self.s.pitch * 10))
        self.lbl_pitch.setText(f"{self.s.pitch}")
        self.cb_emotion.setCurrentText(self.s.emotion)
        self.cb_textmode.setCurrentText(self.s.text_mode)
        self._refresh_devices()

    def _save_voice(self):
        self.s.speaking_speed = round(self.sld_speed.value() / 100, 3)
        self.s.energy = round(self.sld_energy.value() / 100, 3)
        self.s.pitch = round(self.sld_pitch.value() / 10, 1)
        self.s.emotion = self.cb_emotion.currentText()
        self.s.text_mode = self.cb_textmode.currentText()
        self.s.save()

    def _save_asr(self):
        self.s.vad_threshold = round(self.sld_vad.value() / 100, 2)
        self.s.save()

    def _save_audio(self):
        self.s.output_sample_rate = self.sp_sr.value()
        self.s.input_block_ms = self.sp_block.value()
        self.s.input_gain_db = self.sp_gain.value()
        self.s.monitor_enabled = self.chk_monitor.isChecked()
        self.s.save()

    # ---------------- 设备 ----------------
    def _refresh_devices(self):
        self._devices = dev.refresh_devices()
        self._fill_combo(self.cb_mic, self._devices["inputs"], self.s.mic_device,
                         self._devices["default_in"])
        self._fill_combo(self.cb_out, self._devices["outputs"], self.s.virtual_output,
                         self._devices["default_out"])
        self._fill_combo(self.cb_mon, self._devices["outputs"], self.s.monitor_output, None)
        if not self._devices["cable"]:
            self.lbl_cable.setText(
                "⚠ 未检测到 VB-CABLE。请到 https://vb-audio.com/Cable/ 下载安装（免费），"
                "然后在 Discord/QQ 的麦克风处选择 “CABLE Output”。")
        else:
            self.lbl_cable.setText(
                "✓ VB-CABLE 已安装：输出选 “CABLE Input”，聊天软件麦克风选 “CABLE Output”。")
        self._reload_ref_combo()

    def _fill_combo(self, cb: QComboBox, items: list[dict], preferred: str, default_item):
        cb.blockSignals(True)
        cb.clear()
        sel = 0
        names = []
        for i, d in enumerate(items):
            cb.addItem(d["name"], d["index"])
            names.append(d["name"])
            if d["name"] == preferred:
                sel = i
        if names and sel == 0 and default_item:
            dn = default_item["name"]
            if dn in names:
                sel = names.index(dn)
        if cb.count():
            cb.setCurrentIndex(sel)
        cb.blockSignals(False)

    # ---------------- 参考音频 ----------------
    def _reload_ref_combo(self):
        from app.profiles.reference import ReferenceManager
        mgr = ReferenceManager()
        self.cb_ref.blockSignals(True)
        self.cb_ref.clear()
        profs = mgr.list_profiles()
        sel = 0
        for i, p in enumerate(profs):
            self.cb_ref.addItem(f"{p['name']} ({p['analysis']['overall']})", p["id"])
            if p["id"] == self.s.reference_profile:
                sel = i
        if profs:
            self.cb_ref.setCurrentIndex(sel)
            self._show_ref_quality(profs[sel])
        else:
            self.lbl_ref_quality.setText("未加载参考音频")
        self.cb_ref.blockSignals(False)

    def _show_ref_quality(self, p: dict):
        a = p["analysis"]
        self.lbl_ref_quality.setText(
            f"时长 {a['duration_s']}s · 采样率 {a['sample_rate']} · RMS {a['rms']} · "
            f"削波 {a['clipping_pct']}% · 静音 {a['silence_ratio'] * 100:.0f}% · SNR {a['snr_db']}dB\n"
            f"质量: {a['overall']} — {a['note']}"
            + ("\n⚠ 疑似 BGM" if a.get("bgm_suspected") else ""))

    def _import_reference(self):
        fn, _ = QFileDialog.getOpenFileName(self, "选择参考音频 (5~30s 单人声)", "",
                                            "音频 (*.wav *.mp3 *.flac *.ogg)")
        if not fn:
            return
        from app.profiles.reference import ReferenceManager, analyze_reference
        from app.audio.dsp import AudioProc
        try:
            mgr = ReferenceManager()
            prof = mgr.import_reference(fn)
            self.s.reference_profile = prof["id"]
            self.s.save()
            self._reload_ref_combo()
            self._apply_reference_to_engine()
            QMessageBox.information(self, "参考音频已导入",
                                    f"质量: {prof['analysis']['overall']}\n{prof['analysis']['note']}")
        except Exception as e:
            QMessageBox.critical(self, "导入失败", str(e))

    def _apply_reference_to_engine(self):
        if self.orch and self.orch.tts_queue:
            prof = self.orch.get_active_reference()
            if prof:
                self.orch.tts_queue.engine.load_reference(prof["path"], prof.get("text", ""))

    # ---------------- 运行控制 ----------------
    def _toggle_start(self):
        if self.orch and self.orch.stats.running:
            self.orch.stop()
            self.btn_start.setText("Start")
            return
        self._save_audio()
        self.s.mic_device = self.cb_mic.currentText()
        self.s.virtual_output = self.cb_out.currentText()
        self.s.monitor_output = self.cb_mon.currentText()
        self.s.reference_profile = self.cb_ref.currentData() or self.s.reference_profile
        self.s.listen_mode = "always" if self.radio_always.isChecked() else "ptt"
        self.s.save()
        if self.cb_mic.currentData() is None:
            QMessageBox.warning(self, "未选择麦克风", "请先选择输入设备。")
            return
        if self.cb_out.currentData() is None:
            QMessageBox.warning(self, "未选择输出", "请选择虚拟输出设备 (VB-CABLE)。")
            return
        prof = None
        if self.s.reference_profile:
            from app.profiles.reference import ReferenceManager
            prof = ReferenceManager().get_profile(self.s.reference_profile)
        if not prof:
            QMessageBox.warning(self, "缺少参考音频",
                                "请先导入参考 WAV（5~30s 单人声）。\n这决定克隆出的音色。")
            return
        self.orch = Orchestrator(self.s)
        self._wire_orchestrator_events()
        self.orch.start(self.cb_mic.currentData(), self.cb_out.currentData(),
                        self.cb_mon.currentData() if self.chk_monitor.isChecked() else None)
        self.orch.tts_queue.engine.load_reference(prof["path"], prof.get("text", ""))
        self.btn_start.setText("Stop")

    def _wire_orchestrator_events(self):
        o = self.orch
        o.gui_events["on_text"] = lambda d: self.bus.ev.emit("text", d)
        o.gui_events["on_sentence"] = lambda t: self.bus.ev.emit("sentence", t)
        o.gui_events["on_tts_state"] = lambda st: self.bus.ev.emit("tts_state", st)
        o.gui_events["on_error"] = lambda m: self.bus.ev.emit("error", m)
        o.gui_events["on_tick"] = lambda _x: self.bus.ev.emit("tick", None)
        self.bus.ev.connect(self._on_bus_event)

    def _on_bus_event(self, name: str, payload):
        if name == "text":
            d = payload or {}
            self.lbl_partial.setText(f"Partial: {d.get('partial', '')}")
            self.lbl_stable.setText(f"Stable: {d.get('stable', '')}")
        elif name == "sentence":
            self.lbl_tts.setText(f"TTS: {payload}")
        elif name == "error":
            self._log(f"ERROR: {payload}")
        elif name == "tick":
            self._update_stats()

    def _toggle_mute(self):
        if self.orch:
            self._muted = self.orch.toggle_mute()
        else:
            self._muted = not self._muted
        self.btn_mute.setText(f"{'解除' if self._muted else '静音'} (F9)")

    def _update_stats(self):
        if not self.orch:
            return
        st = self.orch.stats.snapshot()
        self.lbl_lat.setText(
            f"ASR partial {st['asr_partial_ms']}ms · finalize {st['asr_finalize_ms']}ms · "
            f"TTS TTFA {st['tts_ttfa_ms']}ms · 总延迟 {st['total_ms']}ms · "
            f"GPU {st['gpu_vram_mb']}MB")
        self.lbl_stats.setText(
            f"片段 {st['segments']} · 队列 {self.orch.tts_queue.queue_depth() if self.orch.tts_queue else 0} · "
            f"underrun {st['underruns']} · overflow {st['overflows']}")
        self.lbl_dbg_stats.setText(
            f"VRAM(本进程) {gpu_diag.query_vram_mb()}MB · 整卡 {gpu_diag.query_gpu_total_used_mb()}MB · "
            f"线程 {gpu_diag.system_snapshot()['threads']}")

    # ---------------- 引擎切换 ----------------
    def _apply_engine_settings(self):
        eng = self.cb_tts.currentData()
        vram = self.cb_vram.currentData()
        changed = (eng != self.s.tts_engine) or (vram != self.s.vram_mode)
        self.s.tts_engine = eng
        self.s.vram_mode = vram
        self.s.save()
        if self.orch and self.orch.stats.running and changed:
            if vram == "asr_cpu" and self.orch.s.asr_device != "cpu":
                self.orch.stop()
                self.s.asr_device = "cpu"
                self._restart_pipeline()
            else:
                self.orch.switch_tts_engine(eng)
        elif not self.orch:
            self.s.asr_device = "cpu" if vram == "asr_cpu" else "cuda"

    def _restart_pipeline(self):
        self._toggle_start()
        self._toggle_start()

    # ---------------- Voice Lab ----------------
    def _voicelab(self, key: str, engine_name: str):
        text = self.ed_vlab.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "无文本", "请输入要生成的文本。")
            return
        prof = None
        if self.s.reference_profile:
            from app.profiles.reference import ReferenceManager
            prof = ReferenceManager().get_profile(self.s.reference_profile)
        if not prof:
            QMessageBox.warning(self, "缺少参考音频", "请先导入参考音频。")
            return
        from app.tts.base import TTSStyle
        style = TTSStyle(speed=self.s.speaking_speed, emotion=self.s.emotion,
                         energy=self.s.energy, pitch=self.s.pitch)
        out_dir = Path("data") / "voicelab"
        out_dir.mkdir(parents=True, exist_ok=True)
        w = VoiceLabWorker(engine_name, key, text, style, prof, out_dir)
        w.done.connect(lambda k, p, info: self._voicelab_done(k, p, info))
        w.failed.connect(lambda k, e: self._voicelab_failed(k, e))
        self._voicelab_workers.append(w)
        (self.lbl_vlab_a if key == "A" else self.lbl_vlab_b).setText(f"{key}: 生成中…")
        w.start()

    def _voicelab_done(self, key: str, path: str, info: str):
        import subprocess
        lbl = self.lbl_vlab_a if key == "A" else self.lbl_vlab_b
        lbl.setText(f"{key}: {path} ({info})")
        os_start = "start" if key == "A" else "start"
        try:
            subprocess.Popen(["explorer", path.replace("/", "\\")])
        except Exception:
            pass

    def _voicelab_failed(self, key: str, err: str):
        lbl = self.lbl_vlab_a if key == "A" else self.lbl_vlab_b
        lbl.setText(f"{key}: 失败 {err}")
        self._log(f"VoiceLab {key} failed: {err}")

    # ---------------- 热键 ----------------
    def _start_hotkeys(self):
        def run():
            import keyboard
            import time
            mapping = {
                self.s.hotkeys.get("ptt", "F8"): self._hk_ptt_down,
                self.s.hotkeys.get("mute", "F9"): self._hk_mute,
                self.s.hotkeys.get("clear_queue", "F10"): self._hk_clear,
                self.s.hotkeys.get("interrupt", "F11"): self._hk_interrupt,
            }
            for key, fn in mapping.items():
                try:
                    keyboard.add_hotkey(key, fn)
                except Exception as e:
                    log.error("hotkey %s failed: %s", key, e)
            while not self._hotkey_stop.is_set():
                time.sleep(0.3)
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        self._hotkey_thread = threading.Thread(target=run, daemon=True)
        self._hotkey_thread.start()

    def _hk_ptt_down(self):
        if self.orch and self.orch.stats.running and self.radio_ptt.isChecked():
            self.orch.ptt_down()

    def _hk_ptt_up(self):
        if self.orch and self.orch.stats.running and self.radio_ptt.isChecked():
            self.orch.ptt_up()

    def _hk_mute(self):
        if self.orch:
            self._muted = self.orch.toggle_mute()

    def _hk_clear(self):
        if self.orch:
            self.orch.clear_queue()

    def _hk_interrupt(self):
        if self.orch:
            self.orch.interrupt()

    # ---------------- 诊断 ----------------
    def _run_diag(self):
        self._log("=== 一键诊断 ===")
        self._log(gpu_diag.vram_profile_summary())
        self._log(f"设备: {json.dumps(dev.refresh_devices(), ensure_ascii=False)[:500]}")
        self._log("=== 结束 ===")

    def _log(self, msg: str):
        from datetime import datetime
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self._debug_lines.append(line)
        if len(self._debug_lines) > 500:
            self._debug_lines = self._debug_lines[-500:]
        self.txt_log.setPlainText("\n".join(self._debug_lines))

    def closeEvent(self, event):
        self._hotkey_stop.set()
        try:
            if self.orch:
                self.orch.stop()
        except Exception:
            pass
        for w in self._voicelab_workers:
            w.wait(2000)
        super().closeEvent(event)