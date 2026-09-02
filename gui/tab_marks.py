"""タブ2: グローバルマーク。

GLMPOS P/Q/R/S の座標入力、GLMP w/l、名前付きプリセット(JSON 永続化)、
ウエハ円+4マーク位置の模式図(QGraphicsView)。
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFormLayout,
                               QGraphicsEllipseItem, QGraphicsScene,
                               QGraphicsView, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from jdf.validation import LIMITS

_MARKS = ("P", "Q", "R", "S")


class _MarksView(QGraphicsView):
    """ウエハ円とグローバルマーク P/Q/R/S の位置模式図。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setToolTip("ウエハ上のグローバルマーク位置模式図(上が+Y)")
        self.setMinimumSize(280, 280)
        self._marks = {}
        self._diameter = 76200.0  # 3インチ
        self._rebuild()

    def set_marks(self, glmpos: dict, diameter: float):
        """マーク座標とウエハ直径 [μm] を更新。"""
        self._marks = {k: (float(v[0]), float(v[1])) for k, v in glmpos.items()}
        self._diameter = diameter
        self._rebuild()

    def _rebuild(self):
        s = self._scene
        s.clear()
        r = self._diameter / 2.0
        pad = self._diameter * 0.12
        # ウエハ円(シーン座標は Y 反転に注意: μm の +Y を上にするため -y)
        s.addEllipse(-r, -r, 2 * r, 2 * r,
                     QPen(QColor("#5577aa"), 0), QColor("#eef4fb"))
        # 十字中心線
        pen_axis = QPen(QColor("#b0c4de"), 0, Qt.DashLine)
        s.addLine(-r, 0, r, 0, pen_axis)
        s.addLine(0, -r, 0, r, pen_axis)
        # マーク(小円+ラベル)
        mr = self._diameter * 0.03
        pen_mark = QPen(QColor("#cc3333"), 0)
        for name, (x, y) in self._marks.items():
            item = QGraphicsEllipseItem(x - mr, -(y) - mr, 2 * mr, 2 * mr)
            item.setPen(pen_mark)
            item.setBrush(QColor("#ff6666"))
            s.addItem(item)
            txt = s.addSimpleText(name)
            br = txt.boundingRect()
            # マークの外側方向にラベルを配置(文字幅≈ウエハ直径の 1/20)
            dx = 1 if x >= 0 else -1
            dy = 1 if y >= 0 else -1
            txt.setScale(2 * r / 20.0 / max(br.width(), 1.0))
            txt.setPos(x + dx * mr * 1.8 - br.width() * txt.scale() / 2,
                       -(y) + dy * mr * 1.8 - br.height() * txt.scale() / 2)
        s.setSceneRect(-r - pad, -r - pad, 2 * (r + pad), 2 * (r + pad))
        self.fitInView(s.sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scene.sceneRect().isValid():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)


class MarksTab(QWidget):
    """タブ2: グローバルマークタブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        xlim = LIMITS["glmpos"]["x"]
        ylim = LIMITS["glmpos"]["y"]
        wlim = LIMITS["glmp"]["w"]
        llim = LIMITS["glmp"]["l"]

        # ---- GLMPOS ----
        glmpos_box = QGroupBox("GLMPOS (グローバルマーク座標)")
        glmpos_form = QFormLayout(glmpos_box)
        self.spins = {}  # {name: (x_spin, y_spin)}
        for name in _MARKS:
            sx = self._make_spin(xlim, "μm")
            sy = self._make_spin(ylim, "μm")
            sx.setToolTip(f"マーク {name} の X 座標 [μm] (範囲 {xlim[0]}〜{xlim[1]})")
            sy.setToolTip(f"マーク {name} の Y 座標 [μm] (範囲 {ylim[0]}〜{ylim[1]})")
            sx.valueChanged.connect(self._on_glmpos)
            sy.valueChanged.connect(self._on_glmpos)
            self.spins[name] = (sx, sy)
            row = QHBoxLayout()
            row.addWidget(QLabel("X:"))
            row.addWidget(sx)
            row.addWidget(QLabel("Y:"))
            row.addWidget(sy)
            glmpos_form.addRow(f"マーク {name}:", row)

        # ---- GLMP ----
        glmp_box = QGroupBox("GLMP (マーク寸法)")
        glmp_form = QFormLayout(glmp_box)
        self.glmp_w = self._make_spin(wlim, "μm")
        self.glmp_w.setToolTip(f"マーク幅 w [μm] (範囲 {wlim[0]}〜{wlim[1]})")
        self.glmp_l = self._make_spin(llim, "μm")
        self.glmp_l.setToolTip(
            f"マーク長 l [μm] (範囲 w/2〜{llim[1]})。w=0 なら GLMP 行を出力しない")
        self.glmp_w.valueChanged.connect(self._on_glmp)
        self.glmp_l.valueChanged.connect(self._on_glmp)
        glmp_form.addRow("w:", self.glmp_w)
        glmp_form.addRow("l:", self.glmp_l)

        # ---- プリセット ----
        preset_box = QGroupBox("GLMPOS プリセット")
        preset_layout = QVBoxLayout(preset_box)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip("保存済みプリセットを選択して適用")
        self.preset_combo.activated.connect(self._on_preset_selected)
        btn_row = QHBoxLayout()
        self.btn_save = QPushButton("現在値を保存")
        self.btn_save.setToolTip("現在の GLMPOS/GLMP 値を名前付きプリセットとして保存")
        self.btn_save.clicked.connect(self._on_preset_save)
        self.btn_del = QPushButton("削除")
        self.btn_del.setToolTip("選択中のプリセットを削除")
        self.btn_del.clicked.connect(self._on_preset_delete)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_del)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addLayout(btn_row)
        self._presets = {}

        # ---- 模式図 ----
        view_box = QGroupBox("模式図")
        view_layout = QVBoxLayout(view_box)
        self.view = _MarksView()
        view_layout.addWidget(self.view)

        # ---- 全体レイアウト ----
        left = QVBoxLayout()
        left.addWidget(glmpos_box)
        left.addWidget(glmp_box)
        left.addWidget(preset_box)
        left.addStretch(1)
        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addWidget(view_box, 1)

        self._load_presets()
        self.reload_from_model()

    # ---------------- ヘルパ ----------------
    @staticmethod
    def _make_spin(lim, unit: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(lim[0], lim[1])
        sp.setSuffix(f" {unit}")
        sp.setKeyboardTracking(False)
        return sp

    def _wafer_diameter(self) -> float:
        """材料サイズに応じたウエハ直径 [μm] (SEMI M1)。"""
        return 100000.0 if self.ctx.deck.material_size >= 4.0 else 76200.0

    def _update_view(self):
        self.view.set_marks(self.ctx.deck.glmpos, self._wafer_diameter())

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        self._loading = True
        try:
            d = self.ctx.deck
            for name in _MARKS:
                sx, sy = self.spins[name]
                sx.setValue(float(d.glmpos[name][0]))
                sy.setValue(float(d.glmpos[name][1]))
            if d.glmp:
                self.glmp_w.setValue(float(d.glmp[0]))
                self.glmp_l.setValue(float(d.glmp[1]))
            else:
                self.glmp_w.setValue(0.0)
                self.glmp_l.setValue(0.0)
            self._update_view()
        finally:
            self._loading = False

    # ---------------- UI → モデル ----------------
    def _notify(self):
        if not self._loading:
            self.ctx.notify_changed(self)

    def _on_glmpos(self, _value):
        if self._loading:
            return
        g = self.ctx.deck.glmpos
        for name in _MARKS:
            sx, sy = self.spins[name]
            g[name] = [float(sx.value()), float(sy.value())]
        self._update_view()
        self._notify()

    def _on_glmp(self, _value):
        if self._loading:
            return
        w = float(self.glmp_w.value())
        l = float(self.glmp_l.value())
        self.ctx.deck.glmp = [w, l] if w > 0 else None
        self._notify()

    # ---------------- プリセット ----------------
    def _load_presets(self):
        """起動時に JSON からプリセットを読み込む。"""
        self._presets = {}
        path = self.ctx.presets_path
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._presets = data
            except (OSError, ValueError):
                pass  # 壊れたプリセットファイルは無視
        self._refresh_preset_combo()

    def _save_presets(self):
        try:
            with open(self.ctx.presets_path, "w", encoding="utf-8") as f:
                json.dump(self._presets, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "プリセット保存エラー",
                                f"プリセットの保存に失敗しました:\n{e}")

    def _refresh_preset_combo(self, select: str | None = None):
        combo = self.preset_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(プリセット選択)", None)
        for name in sorted(self._presets):
            combo.addItem(name, name)
        if select is not None:
            idx = combo.findText(select)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _current_values(self) -> dict:
        d = self.ctx.deck
        return {
            "glmpos": {k: list(v) for k, v in d.glmpos.items()},
            "glmp": list(d.glmp) if d.glmp else None,
        }

    def _on_preset_selected(self, _idx):
        name = self.preset_combo.currentData()
        if not name or name not in self._presets:
            return
        data = self._presets[name]
        d = self.ctx.deck
        for k in _MARKS:
            if k in data.get("glmpos", {}):
                d.glmpos[k] = [float(data["glmpos"][k][0]),
                               float(data["glmpos"][k][1])]
        glmp = data.get("glmp")
        d.glmp = [float(glmp[0]), float(glmp[1])] if glmp else None
        self.reload_from_model()
        self._notify()

    def _on_preset_save(self):
        name, ok = QInputDialog.getText(
            self, "プリセット保存", "プリセット名を入力してください:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self._presets:
            ret = QMessageBox.question(
                self, "上書き確認",
                f"プリセット '{name}' は既に存在します。上書きしますか?")
            if ret != QMessageBox.Yes:
                return
        self._presets[name] = self._current_values()
        self._save_presets()
        self._refresh_preset_combo(select=name)

    def _on_preset_delete(self):
        name = self.preset_combo.currentData()
        if not name or name not in self._presets:
            QMessageBox.information(self, "プリセット削除",
                                    "削除するプリセットを選択してください。")
            return
        ret = QMessageBox.question(
            self, "削除確認", f"プリセット '{name}' を削除しますか?")
        if ret != QMessageBox.Yes:
            return
        del self._presets[name]
        self._save_presets()
        self._refresh_preset_combo()
