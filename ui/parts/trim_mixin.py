from PyQt5.QtWidgets import QStyle

class TrimMixin:
        def _update_trim_inputs(self):
            """Update spinbox limits based on the original duration."""
            if not hasattr(self, "start_minute_input"): return
            total_seconds = int(self.original_duration)
            max_m = total_seconds // 60
            max_s = total_seconds % 60
            self.start_minute_input.setRange(0, max_m)
            self.start_second_input.setRange(0, 59)
            self.end_minute_input.setRange(0, max_m)
            self.end_second_input.setRange(0, 59)
            self.start_minute_input.setValue(0)
            self.start_second_input.setValue(0)
            self.end_minute_input.setValue(max_m)
            self.end_second_input.setValue(max_s)
            self.trim_start = 0.0
            self.trim_end = self.original_duration
            self.positionSlider.set_trim_times(self.trim_start, self.trim_end)

        def set_start_time(self):
            pos_ms = self.vlc_player.get_time()
            pos_s = pos_ms / 1000.0
            if self.original_duration and pos_s >= self.original_duration:
                pos_s = max(0.0, self.original_duration - 0.1)
            self.trim_start = pos_s
            self.logger.info("TRIM: start set at %.3fs", self.trim_start)
            self._update_trim_widgets_from_trim_times()
            self.positionSlider.set_trim_times(self.trim_start, self.trim_end)

        def set_end_time(self):
            dur = float(self.original_duration or 0.0)
            pos_ms = self.vlc_player.get_time()
            pos_s = pos_ms / 1000.0
            if dur > 0.0:
                pos_s = max(0.0, min(pos_s, dur))
                eps = max(0.01, min(0.2, dur * 0.001))
                if self.trim_start is None:
                    self.trim_start = 0.0
                pos_s = min(dur, max(pos_s, self.trim_start + eps))
                if pos_s >= dur and self.trim_start >= dur - eps:
                    self.trim_start = max(0.0, dur - eps)
                    pos_s = dur
            self.trim_end = pos_s
            self._update_trim_widgets_from_trim_times()
            self.positionSlider.set_trim_times(self.trim_start, self.trim_end)
            if self.vlc_player.is_playing():
                self.vlc_player.pause()
                self.playPauseButton.setText("Play")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        def _update_trim_widgets_from_trim_times(self):
            if self.trim_start is not None:
                start_total = int(round(self.trim_start))
                sm = start_total // 60
                ss = start_total % 60
                self.start_minute_input.setValue(sm)
                self.start_second_input.setValue(ss)
            if self.trim_end is not None:
                end_total = int(round(self.trim_end))
                em = end_total // 60
                es = end_total % 60
                self.end_minute_input.setValue(em)
                self.end_second_input.setValue(es)

