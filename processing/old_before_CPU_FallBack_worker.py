import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from PyQt5.QtCore import QThread

class ProcessThread(QThread):
    def __init__(self, input_path, start_time, end_time, original_resolution, is_mobile_format, speed_factor,
                 script_dir, progress_update_signal, status_update_signal, finished_signal, logger,
                 show_teammates_overlay=False, quality_level: int = 2,
                 bg_music_path=None, bg_music_volume=None, bg_music_offset=0.0, original_total_duration=0.0,
                 disable_fades=False, intro_still_sec: float = 0.0, intro_from_midpoint: bool = False, intro_abs_time: float = None):

        super().__init__()
        self.input_path = input_path
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.original_resolution = original_resolution
        self.is_mobile_format = is_mobile_format
        self.speed_factor = speed_factor
        self.show_teammates_overlay = bool(show_teammates_overlay)
        try:
            self.quality_level = int(quality_level)
        except Exception:
            self.quality_level = 2
        try:
            q = self.quality_level
        except Exception:
            q = 2
        self.keep_highest_res = (q >= 4)
        self.lower_quality = (q <= 0)
        if self.keep_highest_res:
            self.target_mb = None
        elif q == 3:
            self.target_mb = 90.0
        elif q == 2:
            self.target_mb = 45.0
        elif q == 1:
            self.target_mb = 25.0
        else:
            self.target_mb = 15.0
        self.script_dir = script_dir
        self.base_dir = os.path.abspath(os.path.join(self.script_dir, os.pardir))
        self.bin_dir = os.path.join(self.base_dir, 'binaries')
        self.progress_update_signal = progress_update_signal
        self.status_update_signal = status_update_signal
        self.finished_signal = finished_signal
        self.logger = logger
        self.bg_music_path = bg_music_path if (bg_music_path and os.path.isfile(bg_music_path)) else None
        try:
            self.bg_music_volume = float(bg_music_volume) if bg_music_volume is not None else None
        except Exception:
            self.bg_music_volume = None
        try:
            self.bg_music_offset = float(bg_music_offset)
        except Exception:
            self.bg_music_offset = 0.0
        try:
            self.original_total_duration = float(original_total_duration)
        except Exception:
            self.original_total_duration = 0.0
        self.disable_fades = bool(disable_fades)
        self.intro_from_midpoint = bool(intro_from_midpoint)
        try:
            self.intro_still_sec = float(intro_still_sec or 0.0)
            self.intro_abs_time = float(intro_abs_time) if intro_abs_time is not None else None
        except Exception:
            self.intro_still_sec = 0.0
        if self.intro_still_sec <= 0.0:
            self.intro_still_sec = 0.0
        self.start_time_corrected = self.start_time / self.speed_factor if self.speed_factor != 1.0 else self.start_time
        user_duration = self.duration / self.speed_factor if self.speed_factor != 1.0 else self.duration
        self.duration_corrected = max(0.0, user_duration)
        self._estimated_total_duration = max(1.0, self.duration_corrected + self.intro_still_sec)

    def _parse_time_to_seconds(self, time_str: str) -> float:
        """Converts HH:MM:SS.ss or MM:SS.ss time string to seconds."""
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                h = int(parts[0])
                m = int(parts[1])
                s = float(parts[2])
                return (h * 3600) + (m * 60) + s
        except Exception:
            try:
                if len(parts) == 2:
                    m = int(parts[0])
                    s = float(parts[1])
                    return (m * 60) + s
                elif len(parts) == 1:
                    return float(parts[0])
            except Exception:
                return 0.0
        return 0.0

    def get_total_frames(self):
        return None
        cmd = [
            ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_frames', '-of', 'json',
            '-read_intervals', f'{self.start_time_corrected}%+{self.duration_corrected}',
            self.input_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
            data = json.loads(result.stdout)
            if 'streams' in data and len(data['streams']) > 0 and 'nb_frames' in data['streams'][0]:
                return int(data['streams'][0]['nb_frames'])
            elif 'format' in data and 'nb_streams' in data['format'] and 'nb_frames' in data['format']:
                return int(data['format']['nb_frames'])
            else:
                return None
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            return None

    def run(self):
        temp_dir = tempfile.gettempdir()
        self.temp_dir = temp_dir
        temp_log_path = os.path.join(temp_dir, f"ffmpeg2pass-{os.getpid()}-{int(time.time())}.log")
        core_path, intro_path, concat_path = None, None, None
        try:
            user_start = float(self.start_time)
            user_end   = float(self.end_time)
            total_orig = float(self.original_total_duration or 0.0)
            FADE_DUR = 1.5
            EPS = 0.01
            if self.disable_fades:
                self.logger.info("Fades disabled. Using exact trim.")
                in_ss = user_start
                in_t = user_end - user_start
                vfade_in_d = 0.0
                vfade_out_d = 0.0
                vfade_out_st = 0.0
                output_clip_duration = in_t
            else:
                self.logger.info("Fades enabled. Calculating padding.")
                if user_start < FADE_DUR - EPS:
                    self.logger.info(f"Start time {user_start}s is too close to 0. Disabling fade-in and start padding.")
                    in_ss = user_start
                    vfade_in_d = 0.0
                else:
                    in_ss = user_start - FADE_DUR
                    vfade_in_d = FADE_DUR
                if total_orig > 0.0 and user_end > (total_orig - FADE_DUR + EPS):
                    self.logger.info(f"End time {user_end}s is too close to total duration {total_orig}s. Disabling fade-out and end padding.")
                    adj_end = total_orig
                    vfade_out_d = 0.0
                else:
                    adj_end = user_end + FADE_DUR
                    vfade_out_d = FADE_DUR
                in_t = max(0.0, adj_end - in_ss)
                output_clip_duration = in_t
                if vfade_out_d > 0.0:
                    vfade_out_st = max(0.0, output_clip_duration - vfade_out_d)
                else:
                    vfade_out_st = output_clip_duration
            output_clip_duration = output_clip_duration / self.speed_factor if self.speed_factor != 1.0 else output_clip_duration
            vfade_in_d   = vfade_in_d / self.speed_factor if self.speed_factor != 1.0 else vfade_in_d
            vfade_out_d  = vfade_out_d / self.speed_factor if self.speed_factor != 1.0 else vfade_out_d
            vfade_out_st = vfade_out_st / self.speed_factor if self.speed_factor != 1.0 else vfade_out_st
            self.duration_corrected = max(0.0, output_clip_duration)
            if self.speed_factor != 1.0:
                self.status_update_signal.emit(f"Adjusting trim times for speed factor {self.speed_factor}x.")
            thumbnail_hold_sec = 0.0
            start_time_corrected = in_ss
            AUDIO_KBPS = 256
            def _probe_src_audio_kbps():
                try:
                    ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                    cmd = [
                        ffprobe_path, "-v", "error",
                        "-select_streams", "a:0",
                        "-show_entries", "stream=bit_rate",
                        "-of", "default=nw=1:nk=1",
                        self.input_path
                    ]
                    r = subprocess.run(
                        cmd, capture_output=True, text=True, check=True,
                        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    )
                    br_bps = float((r.stdout or "0").strip() or 0)
                    if br_bps > 0:
                        return max(8, int(round(br_bps / 1000.0)))
                except Exception:
                    pass
                try:
                    ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                    cmd2 = [
                        ffprobe_path, "-v", "error",
                        "-show_entries", "format=bit_rate",
                        "-of", "default=nw=1:nk=1",
                        self.input_path
                    ]
                    r2 = subprocess.run(
                        cmd2, capture_output=True, text=True, check=True,
                        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                    )
                    br_bps2 = float((r2.stdout or "0").strip() or 0)
                    if br_bps2 > 0:
                        return max(8, int(round(br_bps2 / 1000.0)))
                except Exception:
                    pass
                return None
            _src_kbps = _probe_src_audio_kbps()
            if _src_kbps:
                AUDIO_KBPS = _src_kbps
                self.status_update_signal.emit(f"Audio bitrate: preserving source ~{AUDIO_KBPS} kbps.")
                self.logger.info(f"Audio bitrate probe: {AUDIO_KBPS} kbps")
            else:
                self.status_update_signal.emit(f"Audio bitrate: source unknown, defaulting to {AUDIO_KBPS} kbps.")
            intro_len_for_size = max(0.0, float(self.intro_still_sec)) if self.intro_still_sec > 0.0 else 0.0
            effective_duration = self.duration_corrected + intro_len_for_size
            video_bitrate_kbps = None
            if self.keep_highest_res:
                try:
                    src_bytes = os.path.getsize(self.input_path)
                    target_file_size_bits = max(1, src_bytes) * 8

                    def _probe_audio_kbps():
                        """Probe the audio bitrate of the input using ffprobe located in the Binaries folder."""
                        try:
                            ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                            cmd = [
                                ffprobe_path, "-v", "error",
                                "-select_streams", "a:0",
                                "-show_entries", "stream=bit_rate",
                                "-of", "default=nw=1:nk=1",
                                self.input_path
                            ]
                            r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
                            br = int(float(r.stdout.strip()))
                            return max(8, int(round(br / 1000.0)))
                        except Exception:
                            return None
                    probed = _probe_audio_kbps()
                    if probed:
                        AUDIO_KBPS = probed
                    if effective_duration <= 0:
                        self.finished_signal.emit(False, "Selected video duration is zero.")
                        return
                    audio_bits = AUDIO_KBPS * 1024 * effective_duration
                    video_bits = target_file_size_bits - audio_bits
                    min_video_kbps = 300
                    if video_bits <= 0:
                        video_bitrate_kbps = min_video_kbps
                    else:
                        video_bitrate_kbps = max(min_video_kbps, int(video_bits / (1024 * effective_duration)))
                    self.status_update_signal.emit(
                        f"Maximum quality: matching source size; audio ~{AUDIO_KBPS} kbps; video ~{video_bitrate_kbps} kbps.")
                except Exception as e:
                    self.status_update_signal.emit(f"Maximum quality fallback: {e}. Using VBR target size.")
                    t_mb = self.target_mb if self.target_mb is not None else 52.0
                    target_file_size_bits = t_mb * 8 * 1024 * 1024
                    audio_bits = AUDIO_KBPS * 1024 * effective_duration
                    video_bits = target_file_size_bits - audio_bits
                    if video_bits < 0:
                        self.finished_signal.emit(False, "Video duration is too short for the target file size.")
                        return
                    video_bitrate_kbps = int(video_bits / (1024 * effective_duration))
            else:
                t_mb = self.target_mb if self.target_mb is not None else 52.0
                target_file_size_bits = t_mb * 8 * 1024 * 1024
                if effective_duration <= 0:
                    self.finished_signal.emit(False, "Selected video duration is zero.")
                    return
                audio_bits = AUDIO_KBPS * 1024 * effective_duration
                video_bits = target_file_size_bits - audio_bits
                if video_bits < 0:
                    self.finished_signal.emit(False, "Video duration is too short for the target file size.")
                    return
                video_bitrate_kbps = int(video_bits / (1024 * effective_duration))
                q_desc = {0: "Bad", 1: "Okay", 2: "Standard", 3: "Good"}.get(self.quality_level, "Standard")
                self.status_update_signal.emit(
                    f"{q_desc} quality: target size ~{t_mb:.0f} MB; video bitrate ~{video_bitrate_kbps:.2f} kbps.")
            total_frames = self.get_total_frames()
            if total_frames is None:
                self.status_update_signal.emit("Could not determine total frames. Progress bar might be inaccurate.")
            video_filter_cmd = ""
            healthbar_crop_string = ""
            loot_area_crop_string = ""
            stats_area_crop_string = ""
            HB_UP_1440 = 8
            hb_1440   = (370, 65, 60, max(0, 1325 - HB_UP_1440))
            loot_1440 = (440, 133, 2160, 1288)
            stats_1440 = (280, 31, 2264, 270)
            team_1440  = (160, 190, 74, 26)

            def scale_box(box, s):
                return tuple(int(round(v * s)) for v in box)

            def map_hud_box_to_input(box, in_w, in_h, base_w=2560, base_h=1440):
                w, h, x, y = box
                if x + w > base_w:
                    x = max(0, base_w - w)
                if y + h > base_h:
                    y = max(0, base_h - h)
                v      = in_h / float(base_h)
                safe_w = base_w * v
                pad_x  = max(0.0, (in_w - safe_w) / 2.0)
                w2 = int(round(w * v))
                h2 = int(round(h * v))
                x2 = int(round(pad_x + x * v))
                y2 = int(round(y * v))
                x2 = max(0, min(in_w - w2, x2))
                y2 = max(0, min(in_h - h2, y2))
                return (w2, h2, x2, y2)
            if self.original_resolution == "1920x1080":
                hb    = scale_box(hb_1440, 0.75)
                loot  = scale_box(loot_1440, 0.75)
                stats = scale_box(stats_1440, 0.75)
                team  = scale_box(team_1440, 0.75)
            elif self.original_resolution == "2560x1440":
                hb, loot, stats, team = hb_1440, loot_1440, stats_1440, team_1440
            elif self.original_resolution == "3440x1440":
                hb    = (350, 130,  720, 1260)
                loot  = (664, 135, 2890, 1205)
                stats = (360,  31, 3030,  440)
                team  = (260, 290,  110,   26)
            elif self.original_resolution == "3840x2160":
                hb    = scale_box(hb_1440, 1.5)
                loot  = scale_box(loot_1440, 1.5)
                stats = scale_box(stats_1440, 1.5)
                team  = scale_box(team_1440, 1.5)
            else:
                hb, loot, stats, team = hb_1440, loot_1440, stats_1440, team_1440
            healthbar_crop_string  = f"{hb[0]}:{hb[1]}:{hb[2]}:{hb[3]}"
            loot_area_crop_string  = f"{loot[0]}:{loot[1]}:{loot[2]}:{loot[3]}"
            stats_area_crop_string = f"{stats[0]}:{stats[1]}:{stats[2]}:{stats[3]}"
            team_crop_string       = f"{team[0]}:{team[1]}:{team[2]}:{team[3]}"
            s = 0.75 if self.original_resolution == "1920x1080" else (1.5 if self.original_resolution == "3840x2160" else 1.0)
            healthbar_scaled_width  = int(round(370 * 0.85 * 2 * s))
            healthbar_scaled_height = int(round(65  * 0.85 * 2 * s))
            loot_scaled_width       = int(round(440 * 0.85 * 1.3 * 1.2 * s))
            loot_scaled_height      = int(round(133 * 0.85 * 1.3 * 1.2 * s))
            stats_scaled_width      = int(round(stats[0] * 1.8 * s))
            stats_scaled_height     = int(round(stats[1] * 1.8 * s))
            team_scaled_width       = int(round(team[0]  * 1.32 * s))
            team_scaled_height      = int(round(team[1]  * 1.32 * s))
            if self.original_resolution == "3440x1440":
                healthbar_scaled_width,  healthbar_scaled_height  = 520, 125
                loot_scaled_width,       loot_scaled_height       = 715, 140
                stats_scaled_width,      stats_scaled_height      = 500,  50
                team_scaled_width,       team_scaled_height       = 211, 280
            main_width  = 1150
            main_height = 1920
            if self.is_mobile_format:
                HB_OVERLAY_UP_1440 = 14
                hb_overlay_up = int(round(HB_OVERLAY_UP_1440 * s))
                hb_overlay_y  = max(0, int(round(main_height - healthbar_scaled_height - hb_overlay_up)))
                loot_overlay_x = int(round(main_width - loot_scaled_width - 85))
                loot_overlay_y = int(round(main_height - loot_scaled_height + 70))
                STATS_MARGIN_ABOVE_1440 = 8
                stats_margin = int(round(STATS_MARGIN_ABOVE_1440 * s))
                stats_overlay_x = int(round((main_width - stats_scaled_width) / 2))
                base_y = min(hb_overlay_y, loot_overlay_y)
                stats_overlay_y = max(0, base_y - stats_scaled_height - stats_margin)
                TEAM_LEFT_MARGIN_1440 = 0
                TEAM_TOP_MARGIN_1440  = 0
                team_overlay_x = int(round(TEAM_LEFT_MARGIN_1440 * s))
                team_overlay_y = int(round(TEAM_TOP_MARGIN_1440  * s))
                if self.original_resolution == "3440x1440":
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            "split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=664:135:2890:1205,scale=715:140,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=350:130:720:1260,scale=520:125,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=360:31:3030:440,scale=500:50,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[team]crop=260:290:110:26,scale=211:280,format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=463:1790[t1];"
                            "[t1][healthbar_scaled]overlay=0:H-h-0[t2];"
                            "[t2][stats_scaled]overlay=323:1745[t3];"
                            "[t3][team_scaled]overlay=0:0"
                        )
                    else:
                        video_filter_cmd = (
                            "split=4[main][lootbar][healthbar][stats];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=664:135:2890:1205,scale=715:140,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=350:130:720:1260,scale=520:125,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=360:31:3030:440,scale=500:50,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=463:1790[t1];"
                            "[t1][healthbar_scaled]overlay=0:H-h-0[t2];"
                            "[t2][stats_scaled]overlay=323:1745"
                        )
                elif self.original_resolution == "1920x1080":
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            "split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=330:120:1814:1082,scale=738:263,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=278:49:45:988,scale=690:121,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=210:23:1698:202,scale=497:54,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[team]crop=120:142:56:20,scale=273:324,format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=445:1800[t1];"
                            "[t1][healthbar_scaled]overlay=-100:1795[t2];"
                            "[t2][stats_scaled]overlay=347:1745[t3];"
                            "[t3][team_scaled]overlay=0:0"
                        )
                    else:
                        video_filter_cmd = (
                            "split=4[main][lootbar][healthbar][stats];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=330:120:1814:1082,scale=738:263,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=278:49:45:988,scale=690:121,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=210:23:1698:202,scale=497:54,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=445:1800[t1];"
                            "[t1][healthbar_scaled]overlay=-100:1795[t2];"
                            "[t2][stats_scaled]overlay=347:1745"
                        )
                else:
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            f"split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            f"[lootbar]crop={loot_area_crop_string},scale={loot_scaled_width * 1.2:.0f}:{loot_scaled_height * 1.2:.0f},format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            f"[healthbar]crop={healthbar_crop_string},scale={healthbar_scaled_width * 1.1:.0f}:{healthbar_scaled_height * 1.1:.0f},format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            f"[stats]crop={stats_area_crop_string},scale={stats_scaled_width}:{stats_scaled_height},format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            f"[team]crop={team_crop_string},scale={team_scaled_width}:{team_scaled_height},format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            f"[main_cropped][lootbar_scaled]overlay={loot_overlay_x}:{loot_overlay_y}[t1];"
                            f"[t1][healthbar_scaled]overlay=-100:{hb_overlay_y}[t2];"
                            f"[t2][stats_scaled]overlay={stats_overlay_x}:{stats_overlay_y}[t3];"
                            f"[t3][team_scaled]overlay={team_overlay_x}:{team_overlay_y}"
                        )
                    else:
                        video_filter_cmd = (
                            f"split=4[main][lootbar][healthbar][stats];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            f"[lootbar]crop={loot_area_crop_string},scale={loot_scaled_width * 1.2:.0f}:{loot_scaled_height * 1.2:.0f},format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            f"[healthbar]crop={healthbar_crop_string},scale={healthbar_scaled_width * 1.1:.0f}:{healthbar_scaled_height * 1.1:.0f},format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            f"[stats]crop={stats_area_crop_string},scale={stats_scaled_width}:{stats_scaled_height},format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            f"[main_cropped][lootbar_scaled]overlay={loot_overlay_x}:{loot_overlay_y}[t1];"
                            f"[t1][healthbar_scaled]overlay=-100:{hb_overlay_y}[t2];"
                            f"[t2][stats_scaled]overlay={stats_overlay_x}:{stats_overlay_y}"
                        )
                self.logger.info(f"Mobile portrait mode: loot={loot_area_crop_string}, health={healthbar_crop_string}, "
                                f"stats={stats_area_crop_string}, alpha=0.8, hb_up={hb_overlay_up}px, "
                                f"stats_xy=({stats_overlay_x},{stats_overlay_y})")
                self.status_update_signal.emit("Optimizing for mobile: Applying portrait crop.")
            else:
                original_width, original_height = map(int, self.original_resolution.split('x'))
                if self.keep_highest_res:
                    target_resolution = "scale=iw:ih"
                    self.status_update_signal.emit("Highest Resolution: keeping source resolution.")
                else:
                    if self.quality_level >= 2:
                        target_resolution = "scale='min(1920,iw)':-2"
                        if video_bitrate_kbps < 800 and original_height > 720:
                            target_resolution = "scale='min(1280,iw)':-2"
                            self.status_update_signal.emit("Low bitrate detected. Scaling to 720p.")
                    elif self.quality_level == 1:
                        target_resolution = "scale='min(1280,iw)':-2"
                        self.status_update_signal.emit("Okay Quality: scaling to 720p.")
                    else:
                        target_resolution = "scale='min(960,iw)':-2"
                        self.status_update_signal.emit("Bad Quality: targeting ~15–20MB and smaller resolution.")
                video_filter_cmd = f"fps=60,{target_resolution}"
            if self.speed_factor != 1.0:
                speed_filter = f"setpts=PTS/{self.speed_factor}"
                if video_filter_cmd:
                    video_filter_cmd = f"{video_filter_cmd},{speed_filter}"
                else:
                    video_filter_cmd = speed_filter
                self.status_update_signal.emit(f"Applying speed factor: {self.speed_factor}x to video.")
            audio_filter_cmd = ""
            if self.speed_factor != 1.0:
                s = float(self.speed_factor)
                if 0.5 <= s <= 2.0:
                    audio_filter_cmd = f"atempo={s:.3f}"
                    self.status_update_signal.emit(f"Applying speed factor {self.speed_factor}x to audio (atempo).")
                    self.logger.info(f"Audio atempo: {audio_filter_cmd}")
                else:
                    chain = []
                    s_work = s
                    if s_work >= 1.0:
                        while s_work > 2.0:
                            chain.append(2.0); s_work /= 2.0
                        chain.append(s_work)
                    else:
                        while s_work < 0.5:
                            chain.append(0.5); s_work /= 0.5
                        chain.append(s_work)
                    chain = [min(2.0, max(0.5, round(f, 3))) for f in chain if abs(f - 1.0) > 1e-3]
                    if chain:
                        audio_filter_cmd = ",".join(f"atempo={f}" for f in chain)
                        self.status_update_signal.emit(f"Applying speed factor {self.speed_factor}x to audio (atempo chain).")
                        self.logger.info(f"Audio atempo chain: {audio_filter_cmd}")
                    else:
                        audio_filter_cmd = f"rubberband=tempo={s:.3f}:pitch=1:formant=1:transients=smooth"
                        self.status_update_signal.emit(f"Applying speed factor {self.speed_factor}x to audio (rubberband fallback).")
                        self.logger.info(f"Audio rubberband fallback: tempo={s:.3f} pitch=1 formant=1")
            output_dir = os.path.join(self.base_dir, '!!!_Ouput_Video_Files_!!!')
            os.makedirs(output_dir, exist_ok=True)
            i = 1
            while True:
                output_file_name = f"Fortnite-Video-{i}.mp4"
                output_path = os.path.join(output_dir, output_file_name)
                if not os.path.exists(output_path):
                    break
                i += 1
            ffmpeg_path = os.path.join(self.bin_dir, 'ffmpeg.exe')
            time_regex = re.compile(r'time=(\S+)')
            self.progress_update_signal.emit(0)
            cmd = [
                ffmpeg_path, '-y',
                '-hwaccel', 'auto',
                '-ss', f"{in_ss:.3f}", '-t', f"{in_t:.3f}",
                '-i', self.input_path,
            ]
            have_bg = bool(self.bg_music_path)
            if have_bg:
                cmd += ['-i', self.bg_music_path]
                self.status_update_signal.emit("Background music: mixing enabled.")
            else:
                self.status_update_signal.emit("Background music: disabled or not found.")
            if os.environ.get('VIDEO_FORCE_CPU') == '1':
                if video_bitrate_kbps is None:
                    vcodec = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18']
                else:
                    vcodec = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23']
            else:
                strict_size = (effective_duration <= 20.0)
                if strict_size:
                    vcodec = [
                        '-c:v', 'h264_nvenc',
                        '-rc', 'cbr',
                        '-tune', 'hq',
                        '-b:v', f'{video_bitrate_kbps}k',
                        '-maxrate', f'{video_bitrate_kbps}k',
                        '-bufsize', f'{int(video_bitrate_kbps*1.0)}k',
                        '-g', '60',
                        '-keyint_min', '60',
                        '-forced-idr', '1',
                        '-rc-lookahead', '0',
                        '-bf', '0',
                        '-b_ref_mode', 'disabled'
                    ]
                    rc_label = "NVENC CBR (strict size)"
                else:
                    vcodec = [
                        '-c:v', 'h264_nvenc',
                        '-rc', 'vbr',
                        '-tune', 'hq',
                        '-multipass', '2',
                        '-b:v', f'{video_bitrate_kbps}k',
                        '-maxrate', f'{int(video_bitrate_kbps*1.05)}k',
                        '-bufsize', f'{int(video_bitrate_kbps*1.2)}k',
                        '-g', '60',
                        '-keyint_min', '60',
                        '-forced-idr', '1',
                        '-rc-lookahead', '8',
                        '-bf', '1',
                        '-b_ref_mode', 'disabled'
                    ]
                    rc_label = "NVENC VBR (stabilized)"
            if os.environ.get('VIDEO_FORCE_CPU') == '1':
                self.status_update_signal.emit("Processing video (CPU libx264).")
            else:
                if 'rc_label' not in locals():
                    rc_label = "NVENC constqp (lossless)"
                self.status_update_signal.emit(f"Processing video ({rc_label}).")
            cmd += vcodec
            cmd += [
                '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart',
            ]
            cmd += ['-loglevel', 'info']
            cmd += ['-fflags', '+genpts', '-avoid_negative_ts', 'make_zero', '-muxpreload', '0', '-muxdelay', '0']
            filter_complex_parts = []
            map_args = []
            core_filters = []
            if self.is_mobile_format:
                vcore = f"[0:v]{video_filter_cmd}," if video_filter_cmd else "[0:v]"
                if not getattr(self, "disable_fades", False):
                    vcore += f"fade=t=in:st=0:d={vfade_in_d:.3f},fade=t=out:st={vfade_out_st:.3f}:d={vfade_out_d:.3f},"
                core_filters.append(
                    f"{vcore}format=yuv420p,trim=duration={self.duration_corrected:.6f},setpts=PTS-STARTPTS,setsar=1,"
                    f"fps=60[vcore]"
                )
            else:
                vcore = f"[0:v]{video_filter_cmd}," if video_filter_cmd else "[0:v],"
                if not getattr(self, "disable_fades", False):
                    vcore += f"fade=t=in:st=0:d={vfade_in_d:.3f},fade=t=out:st={vfade_out_st:.3f}:d={vfade_out_d:.3f},"
                core_filters.append(
                    f"{vcore}format=yuv420p,trim=duration={self.duration_corrected:.6f},setpts=PTS-STARTPTS,setsar=1,"
                    f"fps=60[vcore]"
                )
            if have_bg:
                if audio_filter_cmd:
                    core_filters.append(f"[0:a]{audio_filter_cmd},aresample=48000,asetpts=PTS-STARTPTS[a_main_speed_corrected]")
                else:
                    core_filters.append(f"[0:a]anull,aresample=48000,asetpts=PTS-STARTPTS[a_main_speed_corrected]")
                vol = self.bg_music_volume
                try:
                    vol = float(vol) if vol is not None else 0.35
                except Exception:
                    vol = 0.35
                vol = max(0.0, min(1.0, vol))
                mo = max(0.0, float(self.bg_music_offset or 0.0))
                music_needed_duration = self.duration_corrected
                a1_chain = (
                    f"atrim=start={mo:.3f}:duration={music_needed_duration:.3f},"
                    f"asetpts=PTS-STARTPTS,volume={vol:.4f},aresample=48000"
                 )
                if not self.disable_fades:
                     music_fade_out_start = max(0.0, music_needed_duration - 1.5)
                     a1_chain += (
                         f",afade=t=in:st=0:d=1.5"
                         f",afade=t=out:st={music_fade_out_start:.3f}:d=1.5"
                     )
                core_filters.append(f"[1:a]{a1_chain}[a_music_prepared]")
                core_filters.append(
                    "[a_main_speed_corrected][a_music_prepared]"
                    "amix=inputs=2:duration=first:dropout_transition=3,aresample=48000[acore]"
                )
            else:
                if audio_filter_cmd:
                    core_filters.append(f"[0:a]{audio_filter_cmd},aresample=48000,asetpts=PTS-STARTPTS[acore]")
                else:
                    core_filters.append(f"[0:a]anull,aresample=48000,asetpts=PTS-STARTPTS[acore]")
            core_path = os.path.join(temp_dir, f"core-{os.getpid()}-{int(time.time())}.mp4")
            final_output_target_path = output_path
            core_cmd = [
                ffmpeg_path, '-y', '-hwaccel', 'auto',
                '-ss', f"{in_ss:.3f}", '-t', f"{in_t:.3f}",
                '-i', self.input_path,
            ]
            if have_bg:
                core_cmd += ['-i', self.bg_music_path]
            core_cmd += vcodec + [
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k', '-ar', '48000',
                '-filter_complex', ';'.join(core_filters),
                '-map', '[vcore]', '-map', '[acore]', '-shortest',
                core_path
            ]
            self.logger.info(f"STEP 1/3 CORE: {' '.join(map(str, core_cmd))}")
            core_progress_weight = 0.8 if self.intro_still_sec > 0 else 1.0
            proc1 = subprocess.Popen(core_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                                     text=True, creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0),
                                     encoding='utf-8', errors='replace')
            for line in proc1.stdout:
                s = line.strip()
                self.logger.info(s)
                match = time_regex.search(s)
                if match:
                    current_time_str = match.group(1).split('.')[0]
                    current_seconds = self._parse_time_to_seconds(current_time_str)
                    if self.duration_corrected > 0:
                        percent = (current_seconds / self.duration_corrected)
                        progress = int(max(0, min(100 * core_progress_weight, percent * 100 * core_progress_weight)))
                        self.progress_update_signal.emit(progress)
            proc1.wait()
            proc1.wait()
            if proc1.returncode != 0:
                self.logger.warning("GPU (NVENC) encoding failed. Retrying with CPU libx264 fallback...")
                cmd_cpu = []
                skip_next = False
                for a in core_cmd:
                    if skip_next:
                        skip_next = False
                        continue
                    if a == "h264_nvenc":
                        cmd_cpu.append("libx264")
                        continue
                    if a in ["-hwaccel", "auto"]:
                        skip_next = (a == "-hwaccel")
                        continue
                    if a in ["-rc", "cbr", "vbr", "-tune", "hq", "-rc-lookahead", "0", "-bf", "0", "-b_ref_mode", "disabled"]:
                        continue
                    cmd_cpu.append(a)
                cmd_cpu += ["-preset", "medium", "-crf", "23"]
                self.logger.info(f"Retry STEP 1/3 with CPU (libx264): {' '.join(cmd_cpu)}")
                proc1b = subprocess.Popen(
                    cmd_cpu,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0),
                    encoding='utf-8',
                    errors='replace'
                )
                for line in proc1b.stdout:
                    s = line.strip()
                    self.logger.info(s)
                    match = time_regex.search(s)
                    if match:
                        current_time_str = match.group(1).split('.')[0]
                        current_seconds = self._parse_time_to_seconds(current_time_str)
                        if self.duration_corrected > 0:
                            percent = (current_seconds / self.duration_corrected)
                            progress = int(max(0, min(100 * core_progress_weight, percent * 100 * core_progress_weight)))
                            self.progress_update_signal.emit(progress)
                proc1b.wait()
                if proc1b.returncode != 0:
                    self.finished_signal.emit(False, "Core encode failed (STEP 1/3) after GPU and CPU retries.")
                    return
                else:
                    self.logger.info("CPU fallback succeeded after GPU failure.")
            if self.intro_still_sec > 0:
                if self.intro_abs_time is None and self.intro_from_midpoint:
                    mid = (user_start + user_end) / 2.0
                    if total_orig > 0.0:
                        mid = min(max(0.0, mid), max(0.0, total_orig - 0.05))
                    self.intro_abs_time = float(mid)
                    self.logger.info("INTRO: no user pick; using midpoint %.3fs as thumbnail.", self.intro_abs_time)
                if self.intro_abs_time is not None:
                    self.logger.info(
                        "DEBUG: Intro step enabled. still=%.3fs  abs=%.3fs",
                        float(self.intro_still_sec or 0.1), self.intro_abs_time
                    )
                    intro_path = os.path.join(temp_dir, f"intro-{os.getpid()}-{int(time.time())}.mp4")
                    still_len = max(0.01, float(self.intro_still_sec or 0.1))
                    loop_frames = max(1, int(round(still_len * 60)))
                    base_intro_filter = (
                        f"select='eq(n\,0)',format=yuv420p,setsar=1,"
                        f"loop=loop={loop_frames}:size=1:start=0,setpts=N/60/TB,fps=60[vintro];"
                        f"anullsrc=r=48000:cl=stereo,atrim=duration={still_len:.3f},asetpts=PTS-STARTPTS[aintro]"
                    )
                    if self.is_mobile_format:
                        main_width = 1150
                        main_height = 1920
                        intro_filter = (
                            f"[0:v]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,"
                            f"crop={main_width}:{main_height},{base_intro_filter}"
                        )
                        self.logger.info(
                            "INTRO: abs=%.3fs len=%.3fs (portrait crop)", self.intro_abs_time, still_len
                        )
                    else:
                        intro_filter = f"[0:v]{base_intro_filter}"
                        self.logger.info(
                            "INTRO: abs=%.3fs len=%.3fs (keep aspect)", self.intro_abs_time, still_len
                        )
                    
                    if os.environ.get('VIDEO_FORCE_CPU') == '1':
                        vcodec_intro = ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23']
                    else:
                        vcodec_intro = [
                            '-c:v', 'h264_nvenc',
                            '-rc', 'cbr',
                            '-tune', 'hq',
                            '-b:v', f'{video_bitrate_kbps}k',
                            '-maxrate', f'{video_bitrate_kbps}k',
                            '-bufsize', f'{int(video_bitrate_kbps*1.0)}k',
                            '-g', '60',
                            '-keyint_min', '60',
                            '-forced-idr', '1',
                            '-rc-lookahead', '0',
                            '-bf', '0',
                            '-b_ref_mode', 'disabled'
                        ]
                    
                    intro_cmd_base = [
                        ffmpeg_path, "-y", "-hwaccel", "auto",
                        "-ss", f"{self.intro_abs_time:.6f}",
                        "-i", self.input_path,
                        "-t", "0.2",
                    ]
                    intro_cmd = intro_cmd_base + vcodec_intro + [
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        "-c:a", "aac", "-b:a", f'{AUDIO_KBPS}k', '-ar', '48000',
                        "-filter_complex", intro_filter,
                        "-map", "[vintro]", "-map", "[aintro]", "-shortest", intro_path
                    ]
                    
                    self.logger.info("STEP 2/3 INTRO (GPU/Attempt 1): %s", " ".join(intro_cmd))
                    proc2 = subprocess.Popen(
                        intro_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
                        encoding="utf-8", errors="replace"
                    )
                    for line in proc2.stdout:
                        self.logger.info(line.rstrip())
                        self.progress_update_signal.emit(95)
                    proc2.wait()
                    
                    if proc2.returncode != 0:
                        self.logger.warning("Intro GPU (NVENC) encoding failed. Retrying with CPU libx264 fallback...")
                        
                        vcodec_intro_cpu = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23']
                        intro_cmd_cpu = intro_cmd_base + vcodec_intro_cpu + [
                            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                            "-c:a", "aac", "-b:a", f'{AUDIO_KBPS}k', '-ar', '48000',
                            "-filter_complex", intro_filter,
                            "-map", "[vintro]", "-map", "[aintro]", "-shortest", intro_path
                        ]
                        
                        self.logger.info(f"Retry STEP 2/3 with CPU (libx264): {' '.join(intro_cmd_cpu)}")
                        proc2b = subprocess.Popen(
                            intro_cmd_cpu, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
                            encoding="utf-8", errors="replace"
                        )
                        for line in proc2b.stdout:
                            self.logger.info(line.rstrip())
                            self.progress_update_signal.emit(95)
                        proc2b.wait()
                        
                        if proc2b.returncode != 0:
                            self.finished_signal.emit(False, "Intro encode failed (STEP 2/3) after GPU and CPU retries.")
                            return
                        else:
                            self.logger.info("Intro CPU fallback succeeded after GPU failure.")
                else:
                    self.logger.info("Skipping Intro: no absolute time resolved (user pick or midpoint).")
                    intro_path = None
            else:
                self.logger.info("Skipping Intro: disabled (intro_still_sec<=0).")
                intro_path = None
            concat_list_path = os.path.join(temp_dir, f"concat-{os.getpid()}-{int(time.time())}.txt")
            files_to_concat = []
            if intro_path and os.path.exists(intro_path):
                files_to_concat.append(intro_path)
            if core_path and os.path.exists(core_path):
                files_to_concat.append(core_path)
            else:
                self.finished_signal.emit(False, "Core video file is missing for concatenation.")
                return
            if len(files_to_concat) == 1:
                self.logger.info("STEP 3/3 CONCAT: Skipping concat, renaming core file.")
                try:
                    shutil.move(files_to_concat[0], output_path)
                    core_path = None
                    self.progress_update_signal.emit(100)
                    self.logger.info(
                        f"Job SUCCESS | start={self.start_time}s end={self.end_time}s | out='{output_path}'"
                    )
                    self.finished_signal.emit(True, output_path)
                    return
                except Exception as move_err:
                    self.finished_signal.emit(False, f"Failed to move final video: {move_err}")
                    return
            elif len(files_to_concat) > 1:
                with open(concat_list_path, "w", encoding="utf-8") as fcat:
                    for f in files_to_concat:
                        fcat.write(f"file '{f.replace('\\', '/')}'\n")
                concat_cmd = [
                    ffmpeg_path, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy", "-movflags", "+faststart",
                    output_path
                ]
            else:
                 self.finished_signal.emit(False, "No video files found for final step.")
                 return
            self.logger.info(f"STEP 3/3 CONCAT: {' '.join(concat_cmd)}")
            proc3 = subprocess.Popen(
                concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
            )
            for line in proc3.stdout:
                self.logger.info(line.rstrip())
                self.progress_update_signal.emit(99)
            proc3.wait()
            if proc3.returncode != 0:
                self.finished_signal.emit(False, "Concat failed (STEP 3/3).")
                return
            self.progress_update_signal.emit(100)
            self.logger.info(
                f"Job SUCCESS | start={self.start_time}s end={self.end_time}s | out='{output_path}'"
            )
            self.finished_signal.emit(True, output_path)
            return
        except Exception as e:
            self.logger.exception(f"Job FAILURE with exception: {e}")
            self.finished_signal.emit(False, f"An unexpected error occurred: {e}.")
        finally:
            if getattr(self, "_progress_timer", None):
                try:
                    self._progress_timer.stop()
                except Exception:
                    pass
            for p in [core_path, intro_path, concat_path]:
                 if p and os.path.exists(p):
                     try: os.remove(p)
                     except Exception: pass
            for ext in ["", "-0.log", "-1.log", ".log", ".log-0.log", ".log-1.log"]:
                try:
                    os.remove(temp_log_path.replace(".log", ext))
                except Exception:
                    pass
