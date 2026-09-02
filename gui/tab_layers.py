"""タブ5: LAYER 設定。

LAYER の追加・削除・切替、SCALE / EOS / SHOT / RESIST / STDCUR、
チップ(P コマンド)一覧と各チップの SPPRM 展開式詳細を編集する。
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from jdf.model import ChipDef, Layer
from jdf.validation import LIMITS

_SPPRM_NAMES = ("m1", "m2", "w", "p", "sc", "ss")
_SPPRM_TIPS = (
    "展開最小寸法 m1 [μm](EOS モードで上限が異なる)",
    "展開最大寸法 m2 [μm](空欄可)",
    "展開ビームショットの重ね w(空欄可)",
    "ピッチ p(空欄可)",
    "展開セルサイズ比 sc (0.5〜1.2、空欄可)",
    "展開ビームショットサイズ ss (1〜5、空欄可)",
)


class LayersTab(QWidget):
    """タブ5: LAYER 設定タブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        # ---- LAYER 切替 ----
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("LAYER:"))
        self.layer_combo = QComboBox()
        self.layer_combo.setToolTip("編集する LAYER を選択")
        self.layer_combo.currentIndexChanged.connect(self._on_layer_switch)
        top_row.addWidget(self.layer_combo, 1)
        self.btn_layer_up = QPushButton("↑前へ")
        self.btn_layer_up.setToolTip("選択中の LAYER を並び順で1つ前へ移動")
        self.btn_layer_up.clicked.connect(lambda: self._on_move_layer(-1))
        self.btn_layer_down = QPushButton("↓後へ")
        self.btn_layer_down.setToolTip("選択中の LAYER を並び順で1つ後へ移動")
        self.btn_layer_down.clicked.connect(lambda: self._on_move_layer(+1))
        top_row.addWidget(self.btn_layer_up)
        top_row.addWidget(self.btn_layer_down)
        self.btn_add_layer = QPushButton("LAYER 追加")
        self.btn_add_layer.setToolTip("新しい LAYER を追加(番号は最大値+1)")
        self.btn_add_layer.clicked.connect(self._on_add_layer)
        self.btn_del_layer = QPushButton("LAYER 削除")
        self.btn_del_layer.setToolTip("選択中の LAYER を削除")
        self.btn_del_layer.clicked.connect(self._on_del_layer)
        top_row.addWidget(self.btn_add_layer)
        top_row.addWidget(self.btn_del_layer)

        # ---- レイヤーパラメータ ----
        param_box = QGroupBox("レイヤーパラメータ")
        form = QFormLayout(param_box)

        sc = LIMITS["scale"]
        self.chk_scale = QCheckBox("SCALE を有効にする")
        self.chk_scale.setToolTip("チェックすると SCALE sx,sy を出力")
        self.chk_scale.toggled.connect(self._on_param_changed)
        self.sp_sx = self._mk_double(sc["sx"], 4, "SCALE sx(補正倍率 X)")
        self.sp_sy = self._mk_double(sc["sy"], 4, "SCALE sy(補正倍率 Y)")
        scale_row = QHBoxLayout()
        scale_row.addWidget(self.chk_scale)
        scale_row.addWidget(QLabel("sx:"))
        scale_row.addWidget(self.sp_sx)
        scale_row.addWidget(QLabel("sy:"))
        scale_row.addWidget(self.sp_sy)
        scale_row.addStretch(1)
        form.addRow("SCALE:", scale_row)

        self.sp_eos_mode = QSpinBox()
        self.sp_eos_mode.setRange(*LIMITS["eos"]["mode"])
        self.sp_eos_mode.setKeyboardTracking(False)
        self.sp_eos_mode.setToolTip(
            f"EOS モード (範囲 {LIMITS['eos']['mode'][0]}〜"
            f"{LIMITS['eos']['mode'][1]})")
        self.sp_eos_mode.valueChanged.connect(self._on_param_changed)
        self.ed_eos_cond = QLineEdit()
        self.ed_eos_cond.setMaxLength(LIMITS["eos"]["cond_len"])
        self.ed_eos_cond.setToolTip("EOS 条件名(63文字以下)")
        self.ed_eos_cond.editingFinished.connect(self._on_param_changed)
        eos_row = QHBoxLayout()
        eos_row.addWidget(self.sp_eos_mode)
        eos_row.addWidget(QLabel("条件:"))
        eos_row.addWidget(self.ed_eos_cond, 1)
        form.addRow("EOS:", eos_row)

        self.sp_shot = QSpinBox()
        self.sp_shot.setRange(*LIMITS["shot"]["s"])
        self.sp_shot.setKeyboardTracking(False)
        self.sp_shot.setToolTip(
            f"SHOT A の間引き s (範囲 {LIMITS['shot']['s'][0]}〜"
            f"{LIMITS['shot']['s'][1]})")
        self.sp_shot.valueChanged.connect(self._on_param_changed)
        form.addRow("SHOT 間引き s:", self.sp_shot)

        rlim1, rlim2 = LIMITS["resist"]["s1"], LIMITS["resist"]["s2"]
        self.sp_resist1 = self._mk_double(rlim1, 3, "RESIST s1 [nC/cm2 相当]")
        self.sp_resist2 = self._mk_double(rlim2, 3, "RESIST s2 [nC/cm2 相当]")
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("s1:"))
        res_row.addWidget(self.sp_resist1)
        res_row.addWidget(QLabel("s2:"))
        res_row.addWidget(self.sp_resist2)
        res_row.addStretch(1)
        form.addRow("RESIST:", res_row)

        clim = LIMITS["stdcur"]["c"]
        self.sp_stdcur = self._mk_double(clim, 3, "標準電流 STDCUR [nA]")
        self.sp_stdcur.setSuffix(" nA")
        form.addRow("STDCUR:", self.sp_stdcur)

        # ---- レイヤーパラメータ プリセット ----
        preset_box = QGroupBox("レイヤーパラメータ プリセット")
        preset_layout = QVBoxLayout(preset_box)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip(
            "保存済みプリセットを選択し、「適用」で現在の LAYER に反映\n"
            "(SCALE/EOS/SHOT/RESIST/STDCUR のセット。チップ一覧は含まない)")
        preset_btn_row = QHBoxLayout()
        self.btn_preset_apply = QPushButton("適用")
        self.btn_preset_apply.setToolTip("選択中のプリセットを現在の LAYER に適用")
        self.btn_preset_apply.clicked.connect(self._on_preset_apply)
        self.btn_preset_save = QPushButton("現在値を保存")
        self.btn_preset_save.setToolTip(
            "現在の LAYER のパラメータを名前付きプリセットとして保存")
        self.btn_preset_save.clicked.connect(self._on_preset_save)
        self.btn_preset_del = QPushButton("削除")
        self.btn_preset_del.setToolTip("選択中のプリセットを削除")
        self.btn_preset_del.clicked.connect(self._on_preset_delete)
        preset_btn_row.addWidget(self.btn_preset_apply)
        preset_btn_row.addWidget(self.btn_preset_save)
        preset_btn_row.addWidget(self.btn_preset_del)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addLayout(preset_btn_row)
        self._presets = {}

        # ---- チップ一覧 ----
        chip_box = QGroupBox("チップ一覧 (P コマンド)")
        chip_layout = QVBoxLayout(chip_box)
        self.chip_list = QListWidget()
        self.chip_list.setToolTip("この LAYER のチップ(P コマンド)一覧")
        self.chip_list.currentRowChanged.connect(self._on_chip_select)
        chip_btn_row = QHBoxLayout()
        self.btn_add_chip = QPushButton("チップ追加")
        self.btn_add_chip.setToolTip("擬似パターン番号とファイル名を指定してチップを追加")
        self.btn_add_chip.clicked.connect(self._on_add_chip)
        self.btn_del_chip = QPushButton("チップ削除")
        self.btn_del_chip.setToolTip("選択中のチップを削除")
        self.btn_del_chip.clicked.connect(self._on_del_chip)
        chip_btn_row.addWidget(self.btn_add_chip)
        chip_btn_row.addWidget(self.btn_del_chip)
        self.btn_chip_up = QPushButton("↑")
        self.btn_chip_up.setToolTip("選択中のチップを一覧内で1つ上へ移動")
        self.btn_chip_up.clicked.connect(lambda: self._on_move_chip(-1))
        self.btn_chip_down = QPushButton("↓")
        self.btn_chip_down.setToolTip("選択中のチップを一覧内で1つ下へ移動")
        self.btn_chip_down.clicked.connect(lambda: self._on_move_chip(+1))
        chip_btn_row.addWidget(self.btn_chip_up)
        chip_btn_row.addWidget(self.btn_chip_down)
        chip_btn_row.addStretch(1)
        chip_layout.addWidget(self.chip_list)
        chip_layout.addLayout(chip_btn_row)

        # ---- チップ詳細 ----
        detail_box = QGroupBox("チップ詳細 / 展開式 (SPPRM)")
        detail_box.setCheckable(False)
        detail = QFormLayout(detail_box)

        self.sp_pseudo = QSpinBox()
        self.sp_pseudo.setRange(*LIMITS["layer"]["pseudo"])
        self.sp_pseudo.setKeyboardTracking(False)
        self.sp_pseudo.setToolTip(
            f"擬似パターン番号 (範囲 {LIMITS['layer']['pseudo'][0]}〜"
            f"{LIMITS['layer']['pseudo'][1]})")
        self.sp_pseudo.valueChanged.connect(self._on_chip_edited)
        detail.addRow("擬似パターン番号:", self.sp_pseudo)

        self.ed_filename = QLineEdit()
        self.ed_filename.setMaxLength(LIMITS["layer"]["filename_len"])
        self.ed_filename.setToolTip("パターンデータファイル名(63文字以下)")
        self.ed_filename.editingFinished.connect(self._on_chip_edited)
        detail.addRow("ファイル名:", self.ed_filename)

        spprm_grid = QGridLayout()
        self.spprm_edits = []
        for i, (name, tip) in enumerate(zip(_SPPRM_NAMES, _SPPRM_TIPS)):
            ed = QLineEdit()
            ed.setMaxLength(16)
            ed.setPlaceholderText("空欄可")
            ed.setToolTip(tip)
            ed.editingFinished.connect(self._on_chip_edited)
            self.spprm_edits.append(ed)
            spprm_grid.addWidget(QLabel(name + ":"), i // 3, (i % 3) * 2)
            spprm_grid.addWidget(ed, i // 3, (i % 3) * 2 + 1)
        detail.addRow("SPPRM:", spprm_grid)
        self.lbl_spprm_note = QLabel("6フィールド全て空欄なら SPPRM 行は出力されません。")
        self.lbl_spprm_note.setWordWrap(True)
        detail.addRow(self.lbl_spprm_note)

        # ---- SPPRM 一括入力 ----
        batch_box = QGroupBox("SPPRM 一括入力 (この LAYER の全チップ)")
        batch_layout = QVBoxLayout(batch_box)
        batch_grid = QGridLayout()
        self.batch_spprm_edits = []
        for i, (name, tip) in enumerate(zip(_SPPRM_NAMES, _SPPRM_TIPS)):
            ed = QLineEdit()
            ed.setMaxLength(16)
            ed.setPlaceholderText("空欄可")
            ed.setToolTip(tip)
            self.batch_spprm_edits.append(ed)
            batch_grid.addWidget(QLabel(name + ":"), i // 3, (i % 3) * 2)
            batch_grid.addWidget(ed, i // 3, (i % 3) * 2 + 1)
        batch_layout.addLayout(batch_grid)
        batch_btn_row = QHBoxLayout()
        self.btn_spprm_apply_all = QPushButton("全チップに適用")
        self.btn_spprm_apply_all.setToolTip(
            "入力した SPPRM をこの LAYER の全チップに一括設定")
        self.btn_spprm_apply_all.clicked.connect(self._on_spprm_apply_all)
        self.btn_spprm_clear_all = QPushButton("全チップのSPPRMをクリア")
        self.btn_spprm_clear_all.setToolTip(
            "この LAYER の全チップの SPPRM を削除(行を出力しない)")
        self.btn_spprm_clear_all.clicked.connect(self._on_spprm_clear_all)
        batch_btn_row.addWidget(self.btn_spprm_apply_all)
        batch_btn_row.addWidget(self.btn_spprm_clear_all)
        batch_btn_row.addStretch(1)
        batch_layout.addLayout(batch_btn_row)

        # ---- 全体 ----
        right = QVBoxLayout()
        right.addWidget(param_box)
        right.addWidget(preset_box)
        right.addWidget(detail_box)
        right.addWidget(batch_box)
        right.addStretch(1)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addLayout(top_row)
        left.addWidget(chip_box, 1)
        root.addLayout(left, 1)
        root.addLayout(right, 1)

        self._load_presets()
        self.reload_from_model()

    # ---------------- ヘルパ ----------------
    def _mk_double(self, lim, decimals: int, tip: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(decimals)
        sp.setRange(lim[0], lim[1])
        sp.setKeyboardTracking(False)
        sp.setToolTip(f"{tip} (範囲 {lim[0]}〜{lim[1]})")
        sp.valueChanged.connect(self._on_param_changed)
        return sp

    def _current_layer(self) -> Layer | None:
        idx = self.layer_combo.currentIndex()
        layers = self.ctx.deck.layers
        if 0 <= idx < len(layers):
            return layers[idx]
        return None

    def _current_chip(self) -> ChipDef | None:
        layer = self._current_layer()
        row = self.chip_list.currentRow()
        if layer is not None and 0 <= row < len(layer.chips):
            return layer.chips[row]
        return None

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        self._loading = True
        try:
            keep_num = None
            cur = self._current_layer()
            if cur is not None:
                keep_num = cur.number
            self.layer_combo.blockSignals(True)
            self.layer_combo.clear()
            for layer in self.ctx.deck.layers:
                self.layer_combo.addItem(
                    f"LAYER {layer.number}  (P {len(layer.chips)} 個)")
            self.layer_combo.blockSignals(False)
            idx = 0
            if keep_num is not None:
                for i, layer in enumerate(self.ctx.deck.layers):
                    if layer.number == keep_num:
                        idx = i
                        break
            if self.ctx.deck.layers:
                self.layer_combo.setCurrentIndex(idx)
            self._load_layer()
        finally:
            self._loading = False

    def _load_layer(self):
        layer = self._current_layer()
        has = layer is not None
        for w in (self.chk_scale, self.sp_sx, self.sp_sy, self.sp_eos_mode,
                  self.ed_eos_cond, self.sp_shot, self.sp_resist1,
                  self.sp_resist2, self.sp_stdcur, self.chip_list,
                  self.btn_add_chip, self.btn_del_chip, self.btn_del_layer,
                  self.btn_layer_up, self.btn_layer_down,
                  self.btn_chip_up, self.btn_chip_down,
                  self.btn_preset_apply, self.btn_preset_save,
                  self.btn_spprm_apply_all, self.btn_spprm_clear_all):
            w.setEnabled(has)
        self.chip_list.blockSignals(True)
        self.chip_list.clear()
        if has:
            self.chk_scale.setChecked(layer.scale is not None)
            if layer.scale is not None:
                self.sp_sx.setValue(float(layer.scale[0]))
                self.sp_sy.setValue(float(layer.scale[1]))
            self.sp_sx.setEnabled(layer.scale is not None)
            self.sp_sy.setEnabled(layer.scale is not None)
            self.sp_eos_mode.setValue(layer.eos_mode)
            self.ed_eos_cond.setText(layer.eos_cond)
            self.sp_shot.setValue(layer.shot_s)
            self.sp_resist1.setValue(layer.resist1)
            self.sp_resist2.setValue(layer.resist2)
            self.sp_stdcur.setValue(layer.stdcur)
            for chip in layer.chips:
                QListWidgetItem(self._chip_text(chip), self.chip_list)
            if layer.chips:
                self.chip_list.setCurrentRow(0)
        self.chip_list.blockSignals(False)
        self._load_chip_detail()

    @staticmethod
    def _chip_text(chip: ChipDef) -> str:
        sp = " [SPPRM]" if chip.spprm else ""
        return f"P({chip.pseudo}) '{chip.filename}'{sp}"

    def _load_chip_detail(self):
        chip = self._current_chip()
        has = chip is not None
        for w in [self.sp_pseudo, self.ed_filename] + self.spprm_edits:
            w.setEnabled(has)
        if not has:
            for ed in self.spprm_edits:
                ed.setText("")
            self.ed_filename.setText("")
            return
        self.sp_pseudo.setValue(chip.pseudo)
        self.ed_filename.setText(chip.filename)
        fields = list(chip.spprm)[:6] + [""] * 6 if chip.spprm else [""] * 6
        for ed, val in zip(self.spprm_edits, fields):
            ed.setText(val)

    # ---------------- UI → モデル ----------------
    def _notify(self):
        if not self._loading:
            self.ctx.notify_changed(self)

    def _on_layer_switch(self, _idx):
        if self._loading:
            return
        self._loading = True
        try:
            self._load_layer()
        finally:
            self._loading = False

    def _on_param_changed(self, *_args):
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            return
        if self.chk_scale.isChecked():
            layer.scale = [float(self.sp_sx.value()), float(self.sp_sy.value())]
        else:
            layer.scale = None
        self.sp_sx.setEnabled(self.chk_scale.isChecked())
        self.sp_sy.setEnabled(self.chk_scale.isChecked())
        layer.eos_mode = int(self.sp_eos_mode.value())
        layer.eos_cond = self.ed_eos_cond.text().strip()
        layer.shot_s = int(self.sp_shot.value())
        layer.resist1 = float(self.sp_resist1.value())
        layer.resist2 = float(self.sp_resist2.value())
        layer.stdcur = float(self.sp_stdcur.value())
        self._notify()

    def _on_add_layer(self):
        if self._loading:
            return
        deck = self.ctx.deck
        numbers = {l.number for l in deck.layers}
        lo, hi = LIMITS["layer"]["n"]
        n = max(numbers) + 1 if numbers else lo
        if n > hi:
            n = next((x for x in range(lo, hi + 1) if x not in numbers), None)
        if n is None:
            QMessageBox.warning(self, "LAYER 追加",
                                "使用可能な LAYER 番号がありません。")
            return
        deck.layers.append(Layer(number=n))
        self._notify()
        self.reload_from_model()
        self.layer_combo.setCurrentIndex(len(deck.layers) - 1)

    def _on_del_layer(self):
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            return
        ret = QMessageBox.question(
            self, "LAYER 削除",
            f"LAYER {layer.number} (チップ {len(layer.chips)} 個) を削除しますか?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self.ctx.deck.layers.remove(layer)
        self._notify()
        self.reload_from_model()

    def _on_chip_select(self, _row):
        if self._loading:
            return
        self._loading = True
        try:
            self._load_chip_detail()
        finally:
            self._loading = False

    def _on_chip_edited(self, *_args):
        if self._loading:
            return
        layer = self._current_layer()
        chip = self._current_chip()
        if layer is None or chip is None:
            return
        new_pseudo = int(self.sp_pseudo.value())
        used = {c.pseudo for c in layer.chips if c is not chip}
        if new_pseudo in used:
            QMessageBox.warning(
                self, "擬似パターン番号",
                f"P({new_pseudo}) はこの LAYER で既に使用されています。")
            self._loading = True
            self.sp_pseudo.setValue(chip.pseudo)
            self._loading = False
            return
        chip.pseudo = new_pseudo
        chip.filename = self.ed_filename.text().strip()
        fields = [ed.text().strip() for ed in self.spprm_edits]
        chip.spprm = fields if any(fields) else None
        # 一覧表示を更新
        row = self.chip_list.currentRow()
        self.chip_list.blockSignals(True)
        item = self.chip_list.item(row)
        if item is not None:
            item.setText(self._chip_text(chip))
        self.chip_list.blockSignals(False)
        self._notify()

    def _on_add_chip(self):
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            QMessageBox.information(self, "チップ追加",
                                    "先に LAYER を追加してください。")
            return
        if len(layer.chips) >= LIMITS["layer"]["max_chips"]:
            QMessageBox.warning(
                self, "チップ追加",
                f"1 LAYER あたりのチップ数上限 "
                f"{LIMITS['layer']['max_chips']} に達しています。")
            return
        used = {c.pseudo for c in layer.chips}
        lo, hi = LIMITS["layer"]["pseudo"]
        pseudo = next((n for n in range(lo, hi + 1) if n not in used), None)
        if pseudo is None:
            QMessageBox.warning(self, "チップ追加",
                                "使用可能な擬似パターン番号がありません。")
            return
        chip = ChipDef(pseudo=pseudo, filename="")
        layer.chips.append(chip)
        self._notify()
        self.reload_from_model()
        self.chip_list.setCurrentRow(len(layer.chips) - 1)

    def _on_del_chip(self):
        if self._loading:
            return
        layer = self._current_layer()
        chip = self._current_chip()
        if layer is None or chip is None:
            return
        # 配列から参照されている場合は警告
        refs = []
        for a in self.ctx.deck.arrays:
            if any(c.kind == "P" and c.number == chip.pseudo
                   for c in a.assigns.values()):
                refs.append(a.label if a.label is not None else "(番号なし)")
        msg = f"P({chip.pseudo}) '{chip.filename}' を削除しますか?"
        if refs:
            msg += ("\n\n注意: このチップは配列 "
                    + ", ".join(str(r) for r in refs)
                    + " の ASSIGN で参照されています。")
        ret = QMessageBox.question(self, "チップ削除", msg,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        layer.chips.remove(chip)
        self._notify()
        self.reload_from_model()

    # ---------------- 順番入れ替え ----------------
    def _on_move_layer(self, delta: int):
        """選択中の LAYER を deck.layers 内で ±1 移動する。"""
        if self._loading:
            return
        layers = self.ctx.deck.layers
        idx = self.layer_combo.currentIndex()
        new_idx = idx + delta
        if not (0 <= idx < len(layers)) or not (0 <= new_idx < len(layers)):
            return
        layers[idx], layers[new_idx] = layers[new_idx], layers[idx]
        self._notify()
        # reload は選択中 LAYER(number ベース)を維持するので移動先に追従する
        self.reload_from_model()
        self.layer_combo.setCurrentIndex(new_idx)

    def _on_move_chip(self, delta: int):
        """選択中のチップを layer.chips 内で ±1 移動する。"""
        if self._loading:
            return
        layer = self._current_layer()
        row = self.chip_list.currentRow()
        new_row = row + delta
        if layer is None or not (0 <= row < len(layer.chips)) \
                or not (0 <= new_row < len(layer.chips)):
            return
        layer.chips[row], layer.chips[new_row] = \
            layer.chips[new_row], layer.chips[row]
        self._notify()
        self.reload_from_model()
        # reload で選択が先頭に戻るため、移動先の行を選び直す
        self.chip_list.setCurrentRow(new_row)

    # ---------------- SPPRM 一括入力 ----------------
    def _refresh_chip_list_texts(self, layer: Layer):
        """チップ一覧の表示テキスト(SPPRM 有無の印)だけを更新する。"""
        self.chip_list.blockSignals(True)
        for row, chip in enumerate(layer.chips):
            item = self.chip_list.item(row)
            if item is not None:
                item.setText(self._chip_text(chip))
        self.chip_list.blockSignals(False)

    def _on_spprm_apply_all(self):
        """入力した SPPRM を現在の LAYER の全チップに一括設定する。"""
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            return
        if not layer.chips:
            QMessageBox.information(self, "SPPRM 一括入力",
                                    "この LAYER にはチップがありません。")
            return
        fields = [ed.text().strip() for ed in self.batch_spprm_edits]
        spprm = fields if any(fields) else None
        if spprm is None:
            ret = QMessageBox.question(
                self, "SPPRM 一括入力",
                "6フィールド全て空欄です。全チップの SPPRM をクリアしますか?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        for chip in layer.chips:
            chip.spprm = list(spprm) if spprm else None
        self._refresh_chip_list_texts(layer)
        self._loading = True
        try:
            self._load_chip_detail()  # 選択中チップの詳細表示に反映
        finally:
            self._loading = False
        self._notify()

    def _on_spprm_clear_all(self):
        """現在の LAYER の全チップの SPPRM をクリアする。"""
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            return
        if not any(chip.spprm for chip in layer.chips):
            return
        ret = QMessageBox.question(
            self, "SPPRM クリア",
            f"この LAYER の全チップ ({len(layer.chips)} 個) の SPPRM を"
            "クリアしますか?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        for chip in layer.chips:
            chip.spprm = None
        self._refresh_chip_list_texts(layer)
        self._loading = True
        try:
            self._load_chip_detail()
        finally:
            self._loading = False
        self._notify()

    # ---------------- レイヤーパラメータ プリセット ----------------
    @property
    def _layer_presets_path(self) -> str:
        """layer_presets.json の保存先(GLMPOS プリセットと同じディレクトリ)。"""
        return os.path.join(os.path.dirname(self.ctx.presets_path),
                            "layer_presets.json")

    def _load_presets(self):
        """起動時に JSON からプリセットを読み込む。"""
        self._presets = {}
        path = self._layer_presets_path
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
            with open(self._layer_presets_path, "w", encoding="utf-8") as f:
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

    @staticmethod
    def _layer_param_values(layer: Layer) -> dict:
        """プリセット対象のパラメータ一式を辞書化(チップ一覧は含めない)。"""
        return {
            "scale": list(layer.scale) if layer.scale is not None else None,
            "eos_mode": int(layer.eos_mode),
            "eos_cond": layer.eos_cond,
            "shot_s": int(layer.shot_s),
            "resist1": float(layer.resist1),
            "resist2": float(layer.resist2),
            "stdcur": float(layer.stdcur),
        }

    def _apply_param_values(self, layer: Layer, data: dict):
        """プリセット辞書の値を Layer に反映する。"""
        scale = data.get("scale")
        layer.scale = [float(scale[0]), float(scale[1])] if scale else None
        layer.eos_mode = int(data.get("eos_mode", layer.eos_mode))
        layer.eos_cond = str(data.get("eos_cond", layer.eos_cond))
        layer.shot_s = int(data.get("shot_s", layer.shot_s))
        layer.resist1 = float(data.get("resist1", layer.resist1))
        layer.resist2 = float(data.get("resist2", layer.resist2))
        layer.stdcur = float(data.get("stdcur", layer.stdcur))

    def _on_preset_apply(self):
        """選択中のプリセットを現在の LAYER に適用する。"""
        if self._loading:
            return
        name = self.preset_combo.currentData()
        if not name or name not in self._presets:
            QMessageBox.information(self, "プリセット適用",
                                    "適用するプリセットを選択してください。")
            return
        layer = self._current_layer()
        if layer is None:
            QMessageBox.information(self, "プリセット適用",
                                    "先に LAYER を追加してください。")
            return
        self._apply_param_values(layer, self._presets[name])
        self.reload_from_model()
        self._notify()

    def _on_preset_save(self):
        """現在の LAYER のパラメータを名前付きプリセットとして保存する。"""
        if self._loading:
            return
        layer = self._current_layer()
        if layer is None:
            QMessageBox.information(self, "プリセット保存",
                                    "先に LAYER を追加してください。")
            return
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
        self._presets[name] = self._layer_param_values(layer)
        self._save_presets()
        self._refresh_preset_combo(select=name)

    def _on_preset_delete(self):
        """選択中のプリセットを削除する。"""
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
