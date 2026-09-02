"""タブ1: 基本設定。

ジョブ名・材料サイズ・円形切り取り・ウエハ/マスク・PATH 名・
ヘッダコメントを編集する。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QRadioButton, QVBoxLayout, QWidget)

from jdf.validation import LIMITS


class BasicTab(QWidget):
    """タブ1: 基本設定タブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        # ---- ジョブ ----
        job_box = QGroupBox("ジョブ")
        job_form = QFormLayout(job_box)

        self.job_name = QLineEdit()
        self.job_name.setMaxLength(80)
        self.job_name.setPlaceholderText("省略可(空欄ならジョブ名行を出力しない)")
        self.job_name.setToolTip("ジョブ名(JOB 行の前に出力される任意の名前)")
        self.job_name.editingFinished.connect(self._on_job_name)
        job_form.addRow("ジョブ名:", self.job_name)

        self.rb_wafer = QRadioButton("ウエハ (/W)")
        self.rb_mask = QRadioButton("マスク")
        self.rb_wafer.setToolTip("ウエハジョブ: JOB/W を出力")
        self.rb_mask.setToolTip("マスクジョブ: JOB を出力")
        # ラジオボタンの排他グループは親ウィジェット単位のため、
        # 「対象」と「材料サイズ」は別コンテナに分ける
        wafer_w = QWidget()
        wafer_row = QHBoxLayout(wafer_w)
        wafer_row.setContentsMargins(0, 0, 0, 0)
        wafer_row.addWidget(self.rb_wafer)
        wafer_row.addWidget(self.rb_mask)
        wafer_row.addStretch(1)
        self.rb_wafer.toggled.connect(self._on_wafer)
        self.rb_mask.toggled.connect(self._on_wafer)
        job_form.addRow("対象:", wafer_w)

        self.rb_size3 = QRadioButton("3 インチ")
        self.rb_size4 = QRadioButton("4 インチ")
        d1 = LIMITS["job"]["d1"]
        self.rb_size3.setToolTip(f"材料サイズ d1=3 inch(許容範囲 {d1[0]}〜{d1[1]})")
        self.rb_size4.setToolTip(f"材料サイズ d1=4 inch(許容範囲 {d1[0]}〜{d1[1]})")
        size_w = QWidget()
        size_row = QHBoxLayout(size_w)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.addWidget(self.rb_size3)
        size_row.addWidget(self.rb_size4)
        size_row.addStretch(1)
        self.rb_size3.toggled.connect(self._on_size)
        self.rb_size4.toggled.connect(self._on_size)
        job_form.addRow("材料サイズ:", size_w)

        self.circle_d = QDoubleSpinBox()
        self.circle_d.setDecimals(2)
        self.circle_d.setRange(0.0, LIMITS["job"]["d2"][1])
        self.circle_d.setSuffix(" inch")
        self.circle_d.setSpecialValueText("なし (0)")
        self.circle_d.setToolTip(
            "円形切り取り直径 d2 [inch](0=切り取りなし。"
            f"許容範囲 {LIMITS['job']['d2'][0]}〜{LIMITS['job']['d2'][1]} inch)")
        self.circle_d.valueChanged.connect(self._on_circle)
        job_form.addRow("円形切り取り直径 d2:", self.circle_d)

        # ---- PATH ----
        path_box = QGroupBox("PATH")
        path_form = QFormLayout(path_box)
        self.path_name = QLineEdit()
        self.path_name.setMaxLength(6)
        self.path_name.setToolTip(
            "PATH 名(英字始まり6文字以下の大文字英数字。例: PITCH)")
        self.path_name.editingFinished.connect(self._on_path)
        path_form.addRow("PATH 名:", self.path_name)

        # ---- ヘッダコメント ----
        head_box = QGroupBox("ヘッダコメント")
        head_layout = QVBoxLayout(head_box)
        self.header_comments = QPlainTextEdit()
        self.header_comments.setToolTip(
            "ファイル先頭に出力するコメント(1行=1コメント行、';' は自動付与)")
        self.header_comments.textChanged.connect(self._on_header)
        head_layout.addWidget(self.header_comments)

        # ---- 全体 ----
        root = QVBoxLayout(self)
        root.addWidget(job_box)
        root.addWidget(path_box)
        root.addWidget(head_box, 1)
        root.addStretch(0)

        self.reload_from_model()

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        """ctx.deck の内容を UI に反映(通知は発行しない)。"""
        self._loading = True
        try:
            d = self.ctx.deck
            self.job_name.setText(d.job_name)
            self.rb_wafer.setChecked(d.wafer)
            self.rb_mask.setChecked(not d.wafer)
            if d.material_size >= 4.0:
                self.rb_size4.setChecked(True)
            else:
                self.rb_size3.setChecked(True)
            self.circle_d.setValue(d.circle_diameter)
            self.path_name.setText(d.path_name)
            self.header_comments.blockSignals(True)
            self.header_comments.setPlainText("\n".join(d.header_comments))
            self.header_comments.blockSignals(False)
        finally:
            self._loading = False

    # ---------------- UI → モデル ----------------
    def _notify(self):
        if not self._loading:
            self.ctx.notify_changed(self)

    def _on_job_name(self):
        if self._loading:
            return
        self.ctx.deck.job_name = self.job_name.text().strip()
        self._notify()

    def _on_wafer(self, checked):
        if self._loading:
            return
        self.ctx.deck.wafer = self.rb_wafer.isChecked()
        self._notify()

    def _on_size(self, checked):
        if self._loading:
            return
        self.ctx.deck.material_size = 3.0 if self.rb_size3.isChecked() else 4.0
        self._notify()

    def _on_circle(self, value):
        if self._loading:
            return
        self.ctx.deck.circle_diameter = float(value)
        self._notify()

    def _on_path(self):
        if self._loading:
            return
        text = self.path_name.text().strip().upper()
        if text != self.path_name.text():
            self.path_name.setText(text)
        if text and not LIMITS["name_re"].match(text):
            self.path_name.setStyleSheet("background-color: #ffd6d6;")
        else:
            self.path_name.setStyleSheet("")
        self.ctx.deck.path_name = text
        self._notify()

    def _on_header(self):
        if self._loading:
            return
        text = self.header_comments.toPlainText()
        self.ctx.deck.header_comments = [ln for ln in text.splitlines() if ln.strip()]
        self._notify()
