import sys
import ffmpeg
import numpy as np
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt, QTimer

class TransparentRLEPlayer(QWidget):
    def __init__(self, video_path):
        super().__init__()
        # 纯透明窗口，无色键
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.video_path = video_path
        self.width, self.height = self._get_video_size()
        self.resize(self.width, self.height)

        # 开启 ffmpeg 管道解码 ARGB/BGRA 流
        self.process = (
            ffmpeg
            .input(self.video_path)
            .video
            .output('pipe:', format='rawvideo', pix_fmt='rgba')
            .run_async(pipe_stdout=True, quiet=True)
        )

        self.frame_bytes = self.width * self.height * 4
        self.current_rgba = None

        # 帧率控制 30fps
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.read_frame)
        self.timer.start(33)

    def _get_video_size(self):
        """获取视频宽高"""
        probe = ffmpeg.probe(self.video_path)
        video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        return int(video_stream['width']), int(video_stream['height'])

    def read_frame(self):
        """逐帧读取 RGBA 原始数据"""
        raw = self.process.stdout.read(self.frame_bytes)
        if len(raw) != self.frame_bytes:
            # 视频循环：重启管道
            self.process.terminate()
            self.process = (
                ffmpeg
                .input(self.video_path)
                .video
                .output('pipe:', format='rawvideo', pix_fmt='rgba')
                .run_async(pipe_stdout=True, quiet=True)
            )
            return

        # 转为 numpy RGBA 数组
        frame = np.frombuffer(raw, np.uint8).reshape((self.height, self.width, 4))
        self.current_rgba = frame
        self.update()

    def paintEvent(self, event):
        if self.current_rgba is None:
            return
        h, w, _ = self.current_rgba.shape
        img = QImage(
            self.current_rgba.data,
            w, h,
            w * 4,
            QImage.Format_RGBA8888
        )
        painter = QPainter(self)
        painter.drawImage(0, 0, img)

    def closeEvent(self, event):
        self.process.terminate()
        self.timer.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    # 替换为你的视频路径（ARGB 格式 RLE-MOV 也能正常跑）
    player = TransparentRLEPlayer(r"E:\mp4\reconstructed\1.mov")
    player.show()
    sys.exit(app.exec())