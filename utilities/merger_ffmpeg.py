from PyQt5.QtCore import QProcess
from PyQt5.QtWidgets import QMessageBox
import tempfile
from pathlib import Path
import time
import os

from utilities.merger_utils import _human, _get_logger

class FFMpegHandler:
    def __init__(self, parent):
        self.parent = parent
        self.logger = _get_logger()
        self.process = None
        self._temp_dir = None
        self._output_path = ""
        self._cmd = []

    def merge_now(self):
        n = self.parent.listw.count()
        if n < 2:
            QMessageBox.information(self.parent, "Need more videos", "Please add at least 2 videos to merge.")
            return
        last_out_dir = self.parent._cfg.get("last_out_dir", self.parent._last_dir or Path.home().as_posix())
        default_path = str(Path(last_out_dir) / "merged_video.mp4")
        out_path, _ = self.parent.open_save_dialog(default_path)

        if not out_path:
            return
            
        self._temp_dir = tempfile.TemporaryDirectory()
        concat_txt = Path(self._temp_dir.name, "concat_list.txt")
        with concat_txt.open("w", encoding="utf-8") as f:
            for i in range(n):
                it = self.parent.listw.item(i)
                escaped_path = it.data(self.parent.Qt.UserRole).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        self._output_path = out_path
        music_path, music_vol = self.parent.music_handler.get_selected_music()
        music_offset = self.parent.music_offset_input.value()
        base_cmd = [self.parent.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        if music_path:
            self.logger.info("MUSIC: Adding background music. Audio will be re-encoded.")
            base_cmd.extend(["-i", music_path])
            self._cmd = base_cmd + [
                "-filter_complex", f"[0:a]volume=1.0[a0]; [1:a]atrim=start={music_offset:.3f},volume={music_vol:.3f}[a1]; [a0][a1]amix=inputs=2:duration=first[a_out]",
                "-map", "0:v",
                "-map", "[a_out]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_path)
            ]
        else:
            self.logger.info("MUSIC: No background music. Using fast stream copy.")
            self._cmd = base_cmd + [
                "-c", "copy",
                str(out_path)
            ]
        inputs = []
        total_in = 0
        for i in range(n):
            it = self.parent.listw.item(i)
            f = it.data(self.parent.Qt.UserRole)
            try:
                sz = Path(f).stat().st_size
                total_in += sz
                inputs.append({"path": f, "size": _human(sz)})
            except Exception:
                inputs.append({"path": f, "size": "?"})
        self.logger.info("MERGE_START: outputs='%s'", self._output_path)
        self.logger.info("MERGE_INPUTS: %s", inputs)
        self.logger.info("MERGE_CMD: %s", " ".join(self._cmd))
        self.logger.info("MERGE_TOTAL_INPUT_SIZE: %s", _human(total_in))
        self.process = QProcess(self.parent)
        self.process.finished.connect(self._merge_finished)
        self.process.readyReadStandardError.connect(self._process_ffmpeg_output)
        self._merge_started_at = time.time()
        self.parent.set_ui_busy(True)
        self.logger.info("MERGE_EXEC: %s", " ".join(self._cmd))
        self.process.start(self.parent.ffmpeg, self._cmd[1:])

    def _process_ffmpeg_output(self):
        """Extracts and displays the current progress from FFmpeg's stderr output."""
        try:
            output = self.process.readAllStandardError().data().decode().strip()
            last_line = output.split('\r')[-1].split('\n')[-1].strip()
            if last_line and (last_line.startswith("frame=") or last_line.startswith("size=")):
                self.parent.status_updated.emit(last_line)
            self.logger.debug("FFMPEG_OUTPUT: %s", output)
        except Exception:
            pass

    def _merge_finished(self, exit_code, exit_status):
        self.parent.ui_handler._hide_processing_overlay()
        try:
            self.parent.btn_merge.setEnabled(True)
            self.parent.btn_back.setEnabled(True)
            self.parent.listw.setEnabled(True)
            self.parent.btn_merge.setText("Merge Videos")
        except Exception:
            pass
        """Handle the result of the QProcess merge."""
        try:
            stdout = self.process.readAllStandardOutput().data().decode()
        except Exception:
            stdout = ""
        try:
            stderr = self.process.readAllStandardError().data().decode()
        except Exception:
            stderr = ""
        elapsed = None
        try:
            if hasattr(self, "_merge_started_at"):
                elapsed = max(0, time.time() - self._merge_started_at)
        except Exception:
            pass
        concat_txt_path = None
        if self._temp_dir and hasattr(self._temp_dir, 'name'):
            concat_txt_path = Path(self._temp_dir.name) / "concat_list.txt"
        if self._temp_dir:
            try:
                self._temp_dir.cleanup()
                self.logger.info("Cleaned up temporary directory: %s", self._temp_dir.name)
            except Exception as e:
                self.logger.error("Error cleaning up temporary directory: %s", e)
            finally:
                self._temp_dir = None 
        if concat_txt_path and concat_txt_path.exists():
            try:
                os.remove(concat_txt_path)
                self.logger.info("Removed temporary concat list: %s", concat_txt_path)
            except Exception as e:
                 self.logger.error("Error removing concat list %s: %s", concat_txt_path, e)
        self.parent.set_ui_busy(False)
        self.process = None
        if exit_status == QProcess.CrashExit:
             QMessageBox.critical(self.parent, "Merge Failed", "FFmpeg process crashed unexpectedly.")
             return
        if exit_code != 0:
            QMessageBox.critical(
                self.parent,
                "Merge failed",
                "ffmpeg reported an error. This usually means inputs have mismatched codecs.\n"
                "Ensure all videos share the same codec, resolution, and audio format for lossless concatenation.\n\n"
                f"Output:\n{(stdout + stderr)[:4000]}"
            )
            return
        
        self.parent.show_success_dialog(self._output_path)
