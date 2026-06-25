# Product Specification: SpinningWheelSlider Output Quality Control

> **Purpose:** This document is a complete, AI-agent-consumable product specification for the "Spinning Wheel Slider" quality control component and all of its functionalities. An AI agent should be able to read this and understand every behavior, integration point, visual detail, edge case, and contract.

---

## 1. Component Identity

| Attribute | Value |
|---|---|
| **Class Name** | `SpinningWheelSlider` |
| **File** | `ui/widgets/spinning_wheel_slider.py` |
| **Framework** | PyQt5 (`QWidget` subclass) |
| **Type** | Custom draggable rotary/discrete selector widget |
| **Role** | Output video quality / file-size selector |
| **Instances** | Two independent deployments: Main App (single-video export) + Video Merger (multi-video merge) |

---

## 2. Visual Design & Rendering

The widget is rendered as a **compact cylindrical wheel** that looks like a rotating dial with ribs/notches. It is NOT a standard QSlider — it is fully custom-painted via `paintEvent`.

### 2.1 Fixed Size
- Default: `180 × 35` pixels (set in `__init__`).
- Main App overrides to `160 × UI_LAYOUT.BUTTON_HEIGHT` after construction.
- The Merger keeps the default `180 × 35`.

### 2.2 Paint Layers (bottom to top)
1. **Rounded outer rim** — `QLinearGradient` from `#15202b` → `#3e5871` → `#15202b`, corner radius 6, 1px pen `#0d1217`.
2. **Inner face** — `QRadialGradient` from teal-center (`#3a6b6b`) fading to dark edges (`#0f1a0f` → `#080c08`), inset 3px, corner radius 4.
3. **Rotating ribs** — Vertical bars drawn for indices from `range[0]-5` to `range[1]+5`. Each rib's position is computed as `rib_angle = (i - rotation) * (π/5)`. Ribs beyond `|angle| > π/1.8` are culled. Rib opacity = `cos²(angle)`. Rib width = `max(1.0, 5.0 * opacity^2.5)`. Color gradient per rib: dark edges → light center.
4. **Top/bottom shadow gradient** — Linear gradient black(alpha 210) → transparent → black(alpha 210) to give a recessed look.
5. **Label text** — Drawn for each integer index from `range[0]` to `range[1]`. Each label's horizontal position = `cx + sin(angle) * (w * 0.82)`. Scale = `0.50 + 0.60 * (opacity^0.6)`. Vertical "bulge" = `(1 - opacity^0.3) * 12`. Font: Segoe UI Bold, size `int(9 * scale)`. The **selected** label is cyan `#50ffef` (enabled) / gray `#95a5a6` (disabled). Non-selected labels are light blue `#c5dcf2` (enabled) / gray `#7f8c8d` (disabled). Alpha = `255 * opacity^5.0`. A black shadow offset by (+2,+2) is drawn behind each label.
6. **Center indicators** (enabled only): Two red (`#ff4d4d`) tick marks at top (`cx, 3` → `cx, 11`) and bottom (`cx, h-11` → `cx, h-3`), 2px wide, round caps. Plus a radial glow centered on the widget (`#50ffef` at alpha 45 → transparent).

### 2.3 Disabled State
- Cursor: `Qt.ArrowCursor` is NOT explicitly set; the widget simply ignores mouse events when `isEnabled()` returns False (checked at the top of `mousePressEvent`).
- Label colors switch to the gray palette described above.
- Red center ticks and center glow are NOT drawn.

---

## 3. Interaction Model

### 3.1 Drag-to-Spin
- **Press:** `mousePressEvent` sets `_is_dragging = True`, records `_last_mouse_x = event.x()`, stops any running animation, sets cursor to `ClosedHandCursor`.
- **Move:** `mouseMoveEvent` computes `dx = event.x() - _last_mouse_x`, updates `_last_mouse_x`, then sets `rotation = _rotation - (dx * 0.011)`. The sensitivity factor is **0.011** (hardcoded).
- **Release:** `mouseReleaseEvent` clears dragging, restores `OpenHandCursor`, and calls `setValue(target)` where `target = round(clamp(rotation))`. This triggers the snap animation.

### 3.2 Overscroll
- The rotation is allowed to exceed the range by an **overscroll margin of 0.08** (`_overscroll = 0.08`).
- `_clamp_rotation` clamps to `[range[0] - 0.08, range[1] + 0.08]`.
- On release, the value snaps back to the nearest integer within range.

### 3.3 Snap Animation
- Uses `QPropertyAnimation` on the `rotation` property.
- Duration: **150ms**.
- Easing: `QEasingCurve.OutCubic`.
- The animation interpolates from the current rotation to the target integer value.

### 3.4 Value Change Signal
- `valueChanged = pyqtSignal(int)` — emitted whenever the rounded integer value changes during rotation OR when `setValue` is called programmatically.

### 3.5 Enabling/Disabling
- The widget starts **disabled** (`setEnabled(False)` in `__init__`).
- Both host UIs enable it only when a valid video is loaded.

---

## 4. Public API

| Method/Property | Signature | Description |
|---|---|---|
| `valueChanged` | `pyqtSignal(int)` | Emitted on every discrete value change |
| `setValue` | `(val: int, animated: bool = True)` | Set value, optionally animated. Clamps to range. Emits `valueChanged` |
| `value` | `() → int` | Returns current discrete value |
| `setRange` | `(min_val: int, max_val: int)` | Sets the integer range. Updates paint |
| `setLabels` | `(labels: list[str])` | Sets the text labels for each index. Updates paint |
| `rotation` | `pyqtProperty(float)` | The animated rotation property. Setter clamps and updates `_value` |

### Internal State
- `_value: int` — current discrete value
- `_range: tuple[int, int]` — min/max
- `_labels: list[str]` — label text per index
- `_rotation: float` — animated rotation position
- `_anim: QPropertyAnimation` — snap animation
- `_is_dragging: bool`
- `_last_mouse_x: int`
- `_overscroll: float` — 0.08

---

## 5. Deployment Instance A: Main App Quality Slider (Single-Video Export)

**File:** `ui/parts/ui_builder_mixin.py`, method `_init_process_controls()` (lines ~651–677)

### 5.1 Configuration
| Setting | Value |
|---|---|
| Range | `0` to `20` (21 positions) |
| Labels | `["5MB", "10MB", "15MB", ..., "100MB", "ORIGINAL QUALITY"]` — generated as `[f'{5 + i * 5}MB' for i in range(20)] + ['ORIGINAL QUALITY']` |
| Default value | `7` (= 40MB target) |
| Fixed size | `160 × UI_LAYOUT.BUTTON_HEIGHT` |
| Label above slider | `"OUTPUT FILE SIZE"` (bold, 10px) |
| Label below slider | `quality_value_label` — dynamic quality descriptor |

### 5.2 Enable/Disable Logic
- The slider is **disabled** until a valid video file is loaded.
- `_maybe_enable_process()` (line ~285): `self.quality_slider.setEnabled(has_video)` where `has_video = bool(path exists AND positionSlider.maximum() > 0)`.
- `_set_video_controls_enabled(enabled)` (line ~426): Includes `quality_slider` in the list of widgets toggled.

### 5.3 Quality Descriptor Label (`_update_quality_label`, lines ~906–952)

When the slider value changes, a **dynamic text label** below the slider is updated with a human-readable quality prediction:

1. If no video loaded or trim duration ≤ 0: label is cleared.
2. If `idx >= 20`: label = `"Max CQ"` in green (`#2ecc71`).
3. Otherwise:
   - `target_mb = 5 + idx * 5`
   - Compute effective project duration (accounts for trim + speed segments).
   - Compute audio bitrate via `choose_audio_bitrate(192, dur_sec, target_mb)`.
   - Compute video bitrate via `calculate_video_bitrate(...)` using resolution `1080×1920` (portrait) or `1920×1080` (landscape), 60fps.
   - Compute **bits-per-pixel (bpp)** = `video_kbps * 1000 / (width * height * fps)`. In landscape mode, divide by 1.5 (corrective factor).
   - Map bpp to a descriptor from this spectrum:

     | bpp threshold | Descriptor | Color |
     |---|---|---|
     | < 0.02 | Unwatchable | `#e74c3c` (red) |
     | < 0.04 | Pixelated | `#e74c3c` |
     | < 0.06 | Blurry | `#e74c3c` |
     | < 0.10 | Clear | white |
     | < 0.15 | Sharp | `#2ecc71` (green) |
     | < 0.25 | Crisp-Clear | `#2ecc71` |
     | ≥ 0.25 | Lifelike | `#2ecc71` |

   - Each descriptor gets a `+` or `-` suffix based on whether bpp is above or below the midpoint of its threshold band.

### 5.4 Quality Level → Encoding Parameters

The slider's `value()` (0–20) is passed as `quality_level` to the processing pipeline:

**`processing/config_data.py` → `get_quality_settings(quality_level, target_mb_override)`:**
- `q = int(quality_level)`, fallback to `2` on error.
- If `q >= 20`: `keep_highest_res = True`, uses CQ mode (no target bitrate).
- If `q < 20`: `target_mb = 5 + q * 5` (unless override provided), `keep_highest_res = False`.
- Returns tuple: `(keep_highest_res, target_mb, q)`.

**`processing/encoders.py` → `get_codec_flags(encoder_name, video_bitrate_kbps, duration, fps, quality_level, size_locked)`:**
- For **libx264** (CPU): preset = `'veryfast'` if `q≤0`, `'fast'` if `q≤1`, else `'medium'`. CRF = `23` if `q≤0`, `20` if `q≤1`, else `17`. If bitrate provided, uses VBR with clamped bitrate instead of CRF.
- For **h264_nvenc** (NVIDIA): preset `p7`/multipass `fullres`/lookahead `32`/aq `10` if `q≥2`, else `p6`/`fullres`/`24`/`9`. CQ = `22` if `q≤1`, `15` if `q≥20`, else `19`. If bitrate provided, uses CBR with `-cbr 1 -cbr_padding 1`.
- For **h264_amf** (AMD): quality `'balanced'` if `q≤1`, else `'quality'`.
- For **h264_qsv** (Intel): preset `'balanced'` if `q≤1`, else `'slow'`. Look-ahead depth `60` if `q≤1`, else `100`.

### 5.5 Bitrate Clamping (Hard Limits)
- **Maximum:** `MAX_BITRATE_KBPS = 100000` (100 Mbps) — H.264 Level 5.1 ceiling.
- **Minimum:** `300` kbps.
- VBV buffer: `min(MAX_BITRATE_KBPS, max(kbps, kbps * 2))`.
- Sanity test `assert_bitrate_clamping` verifies: `calculate_video_bitrate(..., target_mb=1)` → 300; `calculate_video_bitrate(..., target_mb=500)` → 50000.

### 5.6 Triggers for Label Update
`_update_quality_label()` is called when:
- Slider value changes (`_on_quality_slider_changed`)
- Boss HP checkbox toggles (`_on_boss_hp_toggled`)
- Granular speed checkbox toggles (`_on_granular_checkbox_toggled`)
- Mobile/portrait checkbox toggles (`_on_mobile_toggled`)
- Video loaded / trim changed (via various hooks)

---

## 6. Deployment Instance B: Video Merger Quality Slider (Multi-Video Merge)

**File:** `utilities/merger_ui_widgets.py`, method `create_quality_column()` (lines 27–49)

### 6.1 Configuration
| Setting | Value |
|---|---|
| Range | `0` to `4` (5 positions) |
| Labels | `["20%", "40%", "60%", "80%", "100%"]` (set directly via `_labels`) |
| Default value | `4` (100%) |
| Enabled | `True` (immediately after creation) |

### 6.2 Per-Level Tooltips
Each position has a descriptive tooltip that updates dynamically via `valueChanged`:

| Value | Label | Tooltip |
|---|---|---|
| 0 | 20% | "20% Quality: Maximum compression. Results in very small file sizes, significantly smaller than all combined videos." |
| 1 | 40% | "40% Quality: High compression. Great for saving space while keeping the video watchable." |
| 2 | 60% | "60% Quality: Balanced. Good reduction in file size with decent visual clarity." |
| 3 | 80% | "80% Quality: High Quality. Slight reduction in quality, results in roughly 80% of original combined sizes." |
| 4 | 100% | "100% Quality: Original Quality. No extra compression, matches the combined original videos exactly." |

### 6.3 Quality Level → Bitrate Multiplier

The slider value (0–4) flows into `MergerEngine.__init__` as `quality_level`. In `utilities/merger_engine.py`, method `_detect_gpu_encoder()`:

**Bitrate Multiplier Map:**
```python
quality_multipliers = {0: 0.20, 1: 0.40, 2: 0.60, 3: 0.80, 4: 1.0}
```
The multiplier scales `target_v_bitrate` (which is the time-weighted average of all input video bitrates).

**CRF Map (used when no target bitrate is available):**
```python
crf_map = {4: 22, 3: 26, 2: 30, 1: 34, 0: 40}
```

### 6.4 Encoder Selection by Quality Level

| Encoder | Quality < 4 | Quality ≥ 4 |
|---|---|---|
| h264_nvenc | preset `p6`, aq-strength `9`, lookahead `48` | preset `p7`, aq-strength `10`, lookahead `64` |
| h264_amf | quality `quality` (same for all) | quality `quality` |
| h264_qsv | preset `slow` (same for all) | preset `slow` |
| libx264 (CPU fallback) | preset `medium` (same for all) | preset `medium` |

### 6.5 Bitrate Clamping in MergerEngine
- `H264_LEVEL_51_MAX_BPS = 100_000_000` (100 Mbps)
- `H264_LEVEL_51_MIN_BPS = 300_000` (300 kbps)
- `_video_bitrate_args(multiplier)` computes `requested = target_v_bitrate * multiplier`, then `effective = clamp(requested, MIN, MAX)`. If clamped, logs the change.
- Buffer size = `clamp(effective, effective * 2, MAX)`.
- Sanity test `assert_merger_hardware_encoder_stress_contract`: With `target_v_bitrate=250_000_000` and multiplier `1.0`, the effective bitrate is clamped to `50000000` (50M).
- Sanity test `assert_merger_quality_file_sizes_contract`: With `target_v_bitrate=50_000_000`, level 0 produces multiplier 0.20 → effective `10000000` (10M); level 4 produces multiplier 1.0 → `50000000` (50M).

---

## 7. Persistence & Recovery

### 7.1 Main App
- The quality slider value is saved to recovery state via `_save_recovery_state()` whenever the value changes (`_on_quality_slider_changed` calls it).
- It is part of the main app's session config and restored on relaunch.

### 7.2 Merger
- **Recovery Manager** (`system/recovery_manager.py`): The quality level is saved every 5 seconds in `_save_recovery_state()` under `volatile_settings.quality_level`. On restore (`_restore_recovery_state`, triggered by `FVS_RESTORE_SESSION=1` env var), `self.quality_slider.setValue(v.get("quality_level", 7))` is called. **Note:** The fallback default in the restore path is `7`, but the merger slider's range is only 0–4, so the value will be clamped to 4 by `setValue`.
- **Config persistence** (`merger_window_logic.py`): The quality level is saved/loaded as part of the merger's JSON config.

---

## 8. Edge Cases & Safety Contracts

### 8.1 Value Clamping
- `setValue` always clamps: `val = max(range[0], min(range[1], int(val)))`.
- The `rotation` setter independently clamps the rotation float with overscroll, then derives the integer value.
- A new `valueChanged` signal is only emitted when the **integer** value actually changes (not on every rotation tick).

### 8.2 Disabled Widget Ignores Input
- `mousePressEvent` returns immediately if `not self.isEnabled()`.
- This prevents value changes when no video is loaded.

### 8.3 Animation Safety
- `setValue(animated=True)` stops any running animation before starting a new one.
- `mousePressEvent` also stops the animation to allow manual dragging.
- If `animated=False`, the rotation is set directly without animation.

### 8.4 Label Bounds Safety
- In `paintEvent`, label text access is guarded: `txt = self._labels[i] if i < len(self._labels) else str(i)`.
- This prevents index errors if labels list is shorter than the range.

### 8.5 GPU Encoder Detection Failure
- If GPU is requested but no hardware encoder is found, `MergerEngine._detect_gpu_encoder()` raises `RuntimeError("GPU encoding was requested, but no H.264 hardware encoder was exposed.")`.
- The merger catches this and reports failure to the user (CPU fallback is disabled in strict GPU mode).

### 8.6 Sanity Test Contracts (Must Not Break)
These tests in `sanity_tests/` define inviolable behavior contracts:

| Test | Contract |
|---|---|
| `test_merger_quality_levels.py` | `assert_merger_quality_file_sizes_contract` — level 0 → 10M, level 4 → 50M with 50M input |
| `test_merger_20_hardware_encoder_stress.py` | `assert_merger_hardware_encoder_stress_contract` — 250M input clamps to 50M |
| `test_main_20_bitrate_clamping.py` | `assert_bitrate_clamping` — target_mb=1 → 300kbps; target_mb=500 → 50000kbps |
| `test_core_17_config_missing_uses_safe_defaults_dryrun.py` | Missing config → safe defaults (quality level falls back gracefully) |
| `test_core_18_config_bad_types_auto_clamped_dryrun.py` | Bad config types → auto-clamped (quality level int-cast with fallback) |

---

## 9. Data Flow Summary (End-to-End)

```
User drags SpinningWheelSlider
    ↓
valueChanged(int) emitted
    ↓
┌─────────────────────────────────────────────────────┐
│ MAIN APP PATH:                                       │
│  _on_quality_slider_changed()                        │
│    → _update_quality_label() (bpp descriptor)        │
│    → _save_recovery_state()                          │
│  On PROCESS click:                                   │
│    quality_level = slider.value()                    │
│    → config_data.get_quality_settings(level)         │
│      → (keep_highest_res, target_mb, q)             │
│    → media_utils.calculate_video_bitrate(...)        │
│      → video_bitrate_kbps (clamped 300–50000)        │
│    → encoders.EncoderManager.get_codec_flags(...)    │
│      → FFmpeg flags (CRF or VBR + preset + AQ)       │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│ MERGER PATH:                                         │
│  tooltip updated via valueChanged                    │
│  On MERGE click:                                     │
│    quality = slider.value() (0–4)                    │
│    → MergerEngine(..., quality_level=quality)        │
│    → _detect_gpu_encoder():                          │
│      multiplier = {0:0.2, 1:0.4, 2:0.6, 3:0.8, 4:1} │
│      crf = {0:40, 1:34, 2:30, 3:26, 4:22}           │
│      effective_bitrate = clamp(target * mult)        │
│      → FFmpeg flags per detected encoder             │
└─────────────────────────────────────────────────────┘
```

---

## 10. Non-Functional Requirements

| Requirement | Specification |
|---|---|
| **Animation latency** | 150ms snap, `OutCubic` easing |
| **Drag sensitivity** | 0.011 radians per pixel of horizontal mouse movement |
| **Overscroll** | 0.08 units beyond range bounds, rubber-bands back on release |
| **Paint performance** | Single `paintEvent`, antialiased, clips to inner rect for labels. No double-buffering needed (Qt handles widget backing store). |
| **Thread safety** | Widget is UI-thread only. `valueChanged` signal is used to communicate to UI consumers. Encoding runs on `QThread` (MergerEngine) or background threads. |
| **DPI scaling** | Font sizes are fixed pixel sizes. Widget uses fixed dimensions. Qt's high-DPI scaling applies automatically. |
| **Color contrast** | Selected label `#50ffef` on dark background meets WCAG AA. Disabled labels use muted grays. |

---

## 11. AI Agent Implementation Checklist

If an AI agent is asked to **modify** or **rebuild** this component, it must satisfy ALL of the following:

- [ ] The widget must be a `QWidget` subclass with a `valueChanged = pyqtSignal(int)` signal.
- [ ] Drag interaction uses horizontal mouse delta with sensitivity `0.011`.
- [ ] Snap-back animation is `QPropertyAnimation` on a `rotation` float property, 150ms, `OutCubic`.
- [ ] Overscroll margin of `0.08` is respected and clamped.
- [ ] `valueChanged` fires only on integer value change, not on every rotation sub-step.
- [ ] `setValue` supports both animated and non-animated modes.
- [ ] `mousePressEvent` returns early when disabled.
- [ ] Paint renders: rim gradient, radial inner face, rotating ribs, shadow, labels with perspective scaling, center ticks (enabled only), center glow (enabled only).
- [ ] Label access is bounds-checked (`i < len(self._labels)`).
- [ ] Main App instance: range 0–20, MB labels + "ORIGINAL QUALITY", default 7, bpp descriptor label.
- [ ] Merger instance: range 0–4, percentage labels, default 4, per-level tooltips.
- [ ] Merger bitrate multipliers: `{0: 0.20, 1: 0.40, 2: 0.60, 3: 0.80, 4: 1.0}`.
- [ ] Merger CRF map: `{4: 22, 3: 26, 2: 30, 1: 34, 0: 40}`.
- [ ] Bitrate clamping: min 300 kbps, max 100 Mbps (H.264 L5.1).
- [ ] All 5 sanity tests listed in §8.6 must pass unchanged.
- [ ] Recovery/persistence saves and restores the quality level.
- [ ] The quality descriptor label spectrum (Unwatchable → Lifelike) is preserved in the main app.

---

*End of Specification*