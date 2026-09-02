"""タブ3: チップ配列定義。

左に配列定義一覧(QTreeWidget でネスティング階層表示)、
右に選択配列の編集フォーム。追加・削除・循環参照チェックを行う。
起点座標の自動計算モード・太線グリッド設定・配列プリセット(JSON 永続化)を持つ。
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit,
                               QMessageBox, QPushButton, QSpinBox,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from jdf.model import ArrayDef, KIND_ARRAY
from jdf.validation import LIMITS, validate_nesting


def _referenced_labels(deck) -> dict:
    """各配列ラベルがどの配列ラベルから参照されているかを返す {子: {親,...}}。

    親がラベルなしの場合はキー None として集約する。
    """
    refs: dict = {}
    for a in deck.arrays:
        for cell in a.assigns.values():
            if cell.kind == KIND_ARRAY:
                refs.setdefault(cell.number, set()).add(a.label)
    return refs


class ArraysTab(QWidget):
    """タブ3: チップ配列定義タブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        L = LIMITS["array"]

        # ---- 左: 配列一覧ツリー ----
        list_box = QGroupBox("配列定義一覧(ネスティング階層)")
        list_layout = QVBoxLayout(list_box)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["配列", "範囲 (m x n)", "参照元"])
        self.tree.setToolTip(
            "配列定義の一覧。ASSIGN A(a) の参照関係から階層表示します")
        self.tree.currentItemChanged.connect(self._on_tree_select)
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("追加")
        self.btn_add.setToolTip("新しい配列定義を追加")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_del = QPushButton("削除")
        self.btn_del.setToolTip("選択中の配列定義を削除")
        self.btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_del)
        btn_row.addStretch(1)
        list_layout.addWidget(self.tree)
        list_layout.addLayout(btn_row)

        # ---- 右: 編集フォーム ----
        edit_box = QGroupBox("配列の編集")
        form = QFormLayout(edit_box)

        self.chk_label = QCheckBox("ラベルを付ける(ネスティング参照用)")
        self.chk_label.setToolTip("チェックすると配列番号ラベル a を出力し、"
                                  "他配列から ASSIGN A(a) で参照可能になります")
        self.chk_label.toggled.connect(self._on_label_toggled)
        self.sp_label = QSpinBox()
        self.sp_label.setRange(*L["label"])
        self.sp_label.setKeyboardTracking(False)
        self.sp_label.setToolTip(
            f"配列番号ラベル a(範囲 {L['label'][0]}〜{L['label'][1]})")
        self.sp_label.valueChanged.connect(self._on_edit)
        label_row = QHBoxLayout()
        label_row.addWidget(self.chk_label)
        label_row.addWidget(self.sp_label)
        label_row.addStretch(1)
        form.addRow("ラベル:", label_row)

        self.sp_x = self._mk_double(L["x"], "起点 X [μm]")
        self.sp_m = self._mk_int(L["m"], "X方向点数 m")
        self.sp_p = self._mk_double(L["p"], "Xピッチ p [μm]")
        self.sp_y = self._mk_double(L["y"], "起点 Y [μm]")
        self.sp_n = self._mk_int(L["n"], "Y方向点数 n")
        self.sp_q = self._mk_double(L["q"], "Yピッチ q [μm]")
        form.addRow("起点 X:", self.sp_x)
        form.addRow("点数 m:", self.sp_m)
        form.addRow("ピッチ p:", self.sp_p)
        form.addRow("起点 Y:", self.sp_y)
        form.addRow("点数 n:", self.sp_n)
        form.addRow("ピッチ q:", self.sp_q)

        self.ed_comment = QLineEdit()
        self.ed_comment.setMaxLength(80)
        self.ed_comment.setToolTip("ARRAY 行末に出力するコメント")
        self.ed_comment.editingFinished.connect(self._on_edit)
        form.addRow("コメント:", self.ed_comment)

        # ---- 起点座標の自動計算 ----
        self.chk_auto = QCheckBox("起点座標を自動計算(中央揃え)")
        self.chk_auto.setToolTip(
            "ON のとき点数(m,n)・ピッチ(p,q)から起点座標を自動計算し、"
            "配列が材料中心に来るようにします(x=-(m-1)*p/2, y=(n-1)*q/2)。"
            "ON の間は起点 X/Y の直接編集はできません")
        self.chk_auto.toggled.connect(self._on_auto_origin_toggled)
        form.addRow(self.chk_auto)

        # ---- 太線グリッド ----
        self.grid_box = QGroupBox("太線グリッド(マップ表示)")
        grid_form = QFormLayout(self.grid_box)
        self.chk_grid = QCheckBox("太線グリッドを表示")
        self.chk_grid.setToolTip(
            "ON のときマップタブで指定間隔ごとの区切り線を太線で描き、"
            "区間(ショット)番号を外周に表示します。JDF 出力には影響しません")
        self.chk_grid.toggled.connect(self._on_grid_changed)
        grid_form.addRow(self.chk_grid)
        self.sp_grid_x = QSpinBox()
        self.sp_grid_x.setRange(1, 255)
        self.sp_grid_x.setKeyboardTracking(False)
        self.sp_grid_x.setToolTip("X方向の太線間隔 [チップ数] (1以上)")
        self.sp_grid_x.valueChanged.connect(self._on_grid_changed)
        grid_form.addRow("X方向間隔:", self.sp_grid_x)
        self.sp_grid_y = QSpinBox()
        self.sp_grid_y.setRange(1, 255)
        self.sp_grid_y.setKeyboardTracking(False)
        self.sp_grid_y.setToolTip("Y方向の太線間隔 [チップ数] (1以上)")
        self.sp_grid_y.valueChanged.connect(self._on_grid_changed)
        grid_form.addRow("Y方向間隔:", self.sp_grid_y)
        form.addRow(self.grid_box)

        # ---- 配列プリセット ----
        preset_box = QGroupBox("配列プリセット")
        preset_layout = QVBoxLayout(preset_box)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip(
            "保存済みプリセットを選択して現在の配列に適用")
        self.preset_combo.activated.connect(self._on_preset_selected)
        preset_btn_row = QHBoxLayout()
        self.btn_preset_save = QPushButton("現在値を保存")
        self.btn_preset_save.setToolTip(
            "編集中の配列の値(座標・点数・ピッチ・コメント・自動計算・"
            "太線グリッド設定)を名前付きプリセットとして保存")
        self.btn_preset_save.clicked.connect(self._on_preset_save)
        self.btn_preset_del = QPushButton("削除")
        self.btn_preset_del.setToolTip("選択中のプリセットを削除")
        self.btn_preset_del.clicked.connect(self._on_preset_delete)
        preset_btn_row.addWidget(self.btn_preset_save)
        preset_btn_row.addWidget(self.btn_preset_del)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addLayout(preset_btn_row)
        form.addRow(preset_box)
        self._presets: dict = {}
        base = getattr(ctx, "presets_path", None)
        if base:
            preset_dir = os.path.dirname(os.path.abspath(base))
        else:
            preset_dir = os.path.expanduser("~/.jdf_editor")
            os.makedirs(preset_dir, exist_ok=True)
        self._presets_path = os.path.join(preset_dir, "array_presets.json")

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        form.addRow(self.lbl_info)

        # ---- 全体 ----
        root = QHBoxLayout(self)
        root.addWidget(list_box, 3)
        root.addWidget(edit_box, 2)

        self.reload_from_model()
        self._load_presets()

    # ---------------- ヘルパ ----------------
    def _mk_double(self, lim, tip: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(3)
        sp.setRange(lim[0], lim[1])
        sp.setKeyboardTracking(False)
        sp.setToolTip(f"{tip} (範囲 {lim[0]}〜{lim[1]})")
        sp.valueChanged.connect(self._on_edit)
        return sp

    def _mk_int(self, lim, tip: str) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lim[0], lim[1])
        sp.setKeyboardTracking(False)
        sp.setToolTip(f"{tip} (範囲 {lim[0]}〜{lim[1]})")
        sp.valueChanged.connect(self._on_edit)
        return sp

    def _array_title(self, a: ArrayDef) -> str:
        if a.label is not None:
            return f"[{a.label}]"
        idx = self.ctx.deck.arrays.index(a) if a in self.ctx.deck.arrays else 0
        return f"(番号なし #{idx + 1})"

    def _current_array(self) -> ArrayDef | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.UserRole)

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        self._loading = True
        try:
            current = self._current_array()
            self.tree.blockSignals(True)
            self.tree.clear()
            deck = self.ctx.deck
            refs = _referenced_labels(deck)          # {子label: {親label}}
            by_label = {a.label: a for a in deck.arrays if a.label is not None}
            # 親(オブジェクト) -> 子(オブジェクト) の参照関係(同一性ベース)
            children: dict = {}                       # {id(親): [子ArrayDef]}
            referenced: set = set()                   # 参照されている id(子)
            for a in deck.arrays:
                for cell in a.assigns.values():
                    if cell.kind != KIND_ARRAY:
                        continue
                    child = by_label.get(cell.number)
                    if child is None or child is a:
                        continue
                    children.setdefault(id(a), [])
                    if id(child) not in [id(c) for c in children[id(a)]]:
                        children[id(a)].append(child)
                        referenced.add(id(child))

            def make_item(a: ArrayDef) -> QTreeWidgetItem:
                ref_by = sorted(x for x in refs.get(a.label, ())
                                if x is not None) if a.label is not None else []
                ref_txt = (",".join(f"A({x})" for x in ref_by)
                           if ref_by else "-")
                it = QTreeWidgetItem([self._array_title(a),
                                      f"{a.m} x {a.n}", ref_txt])
                it.setData(0, Qt.UserRole, a)
                it.setToolTip(0, f"ARRAY ({a.x},{a.m},{a.p})/({a.y},{a.n},{a.q})")
                return it

            shown: set = set()

            def add_children(parent_item: QTreeWidgetItem, parent: ArrayDef,
                             guard: set):
                for child in children.get(id(parent), []):
                    if id(child) in guard:
                        continue  # 循環対策
                    shown.add(id(child))
                    it = make_item(child)
                    parent_item.addChild(it)
                    add_children(it, child, guard | {id(child)})

            # トップレベル = 他から参照されない配列(出現順)
            for a in deck.arrays:
                if id(a) in referenced:
                    continue  # 誰かの子
                shown.add(id(a))
                it = make_item(a)
                self.tree.addTopLevelItem(it)
                add_children(it, a, {id(a)})

            # 循環などで残った配列も表示(情報欠落防止)
            for a in deck.arrays:
                if id(a) not in shown:
                    shown.add(id(a))
                    self.tree.addTopLevelItem(make_item(a))

            self.tree.expandAll()
            self.tree.blockSignals(False)

            # 選択復元
            if current is not None and current in deck.arrays:
                self._select_array(current)
            elif self.tree.topLevelItemCount() > 0:
                self.tree.setCurrentItem(self.tree.topLevelItem(0))
            self._load_form()
        finally:
            self._loading = False

    def _select_array(self, arr: ArrayDef):
        it = self._find_item(arr)
        if it is not None:
            self.tree.setCurrentItem(it)

    def _find_item(self, arr: ArrayDef) -> QTreeWidgetItem | None:
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it is not None and it.data(0, Qt.UserRole) is arr:
                return it
            if it is not None:
                stack.extend(it.child(i) for i in range(it.childCount()))
        return None

    def _load_form(self):
        """選択中配列をフォームに表示。"""
        a = self._current_array()
        widgets = [self.chk_label, self.sp_label, self.sp_x, self.sp_m,
                   self.sp_p, self.sp_y, self.sp_n, self.sp_q,
                   self.ed_comment, self.btn_del, self.chk_auto,
                   self.grid_box, self.btn_preset_save]
        for w in widgets:
            w.setEnabled(a is not None)
        if a is None:
            self.lbl_info.setText("配列が選択されていません。")
            return
        self.chk_label.setChecked(a.label is not None)
        self.sp_label.setEnabled(a.label is not None)
        if a.label is not None:
            self.sp_label.setValue(a.label)
        self.sp_x.setValue(a.x)
        self.sp_m.setValue(a.m)
        self.sp_p.setValue(a.p)
        self.sp_y.setValue(a.y)
        self.sp_n.setValue(a.n)
        self.sp_q.setValue(a.q)
        self.ed_comment.setText(a.comment)
        # 起点自動計算モード: ON のとき起点 X/Y は読み取り専用
        self.chk_auto.setChecked(a.auto_origin)
        self.sp_x.setEnabled(not a.auto_origin)
        self.sp_y.setEnabled(not a.auto_origin)
        # 太線グリッド設定
        self.chk_grid.setChecked(a.grid_on)
        self.sp_grid_x.setValue(max(1, int(a.grid_x)))
        self.sp_grid_y.setValue(max(1, int(a.grid_y)))
        self.sp_grid_x.setEnabled(a.grid_on)
        self.sp_grid_y.setEnabled(a.grid_on)
        self.lbl_info.setText(
            f"ASSIGN 割付数: {len(a.assigns)} 点"
            "(割付の編集は「チップ割付(マップ)」タブで行います)")

    # ---------------- UI → モデル ----------------
    def _notify(self):
        if not self._loading:
            self.ctx.notify_changed(self)

    def _on_tree_select(self, current, _previous):
        if self._loading:
            return
        self._loading = True
        try:
            self._load_form()
        finally:
            self._loading = False

    def _on_label_toggled(self, checked):
        if self._loading:
            return
        a = self._current_array()
        if a is None:
            return
        self.sp_label.setEnabled(checked)
        if checked:
            # 未使用の最小ラベルを提案
            used = {x.label for x in self.ctx.deck.arrays
                    if x.label is not None and x is not a}
            lo, hi = LIMITS["array"]["label"]
            label = self.sp_label.value()
            if label in used:
                label = next((n for n in range(lo, hi + 1) if n not in used), None)
                if label is None:
                    QMessageBox.warning(self, "ラベル設定",
                                        "使用可能なラベルがありません。")
                    self._loading = True
                    self.chk_label.setChecked(False)
                    self._loading = False
                    self.sp_label.setEnabled(False)
                    return
                self.sp_label.setValue(label)
            a.label = int(label)
        else:
            a.label = None
        self._notify()
        self.reload_from_model()

    def _on_edit(self, *_args):
        if self._loading:
            return
        a = self._current_array()
        if a is None:
            return
        # ラベル変更は循環・重複を validate_nesting で検査してから適用
        new_label = int(self.sp_label.value()) if self.chk_label.isChecked() else None
        old_label = a.label
        old = (a.x, a.m, a.p, a.y, a.n, a.q, a.comment)
        a.label = new_label
        a.x = float(self.sp_x.value())
        a.m = int(self.sp_m.value())
        a.p = float(self.sp_p.value())
        a.y = float(self.sp_y.value())
        a.n = int(self.sp_n.value())
        a.q = float(self.sp_q.value())
        a.comment = self.ed_comment.text().strip()
        # 起点自動計算モード: 点数・ピッチ変更に追随して起点を再計算
        a.apply_auto_origin()
        errors = validate_nesting(self.ctx.deck)
        if errors:
            QMessageBox.warning(
                self, "ネスティングエラー",
                "この設定はネスティング制約に違反するため元に戻します:\n"
                + "\n".join(errors[:5]))
            a.label = old_label
            (a.x, a.m, a.p, a.y, a.n, a.q, a.comment) = old
            self.reload_from_model()
            return
        self._notify()
        # ツリーの表示(ラベル・参照元)を最新化
        self.reload_from_model()

    def _on_auto_origin_toggled(self, checked):
        """起点座標の自動計算モードの ON/OFF。"""
        if self._loading:
            return
        a = self._current_array()
        if a is None:
            return
        a.auto_origin = bool(checked)
        if checked:
            a.apply_auto_origin()
        self.sp_x.setEnabled(not checked)
        self.sp_y.setEnabled(not checked)
        self._notify()
        self.reload_from_model()

    def _on_grid_changed(self, *_args):
        """太線グリッドの ON/OFF・間隔変更。"""
        if self._loading:
            return
        a = self._current_array()
        if a is None:
            return
        a.grid_on = self.chk_grid.isChecked()
        a.grid_x = max(1, int(self.sp_grid_x.value()))
        a.grid_y = max(1, int(self.sp_grid_y.value()))
        self.sp_grid_x.setEnabled(a.grid_on)
        self.sp_grid_y.setEnabled(a.grid_on)
        self._notify()

    # ---------------- 配列プリセット ----------------
    def _load_presets(self):
        """起動時に JSON からプリセットを読み込む。"""
        self._presets = {}
        if os.path.exists(self._presets_path):
            try:
                with open(self._presets_path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._presets = data
            except (OSError, ValueError):
                pass  # 壊れたプリセットファイルは無視
        self._refresh_preset_combo()

    def _save_presets(self):
        try:
            with open(self._presets_path, "w", encoding="utf-8") as f:
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

    def _preset_values(self, a: ArrayDef) -> dict:
        """プリセットに保存する値(label と assigns は含めない)。"""
        return {
            "x": a.x, "m": a.m, "p": a.p,
            "y": a.y, "n": a.n, "q": a.q,
            "comment": a.comment,
            "auto_origin": a.auto_origin,
            "grid_on": a.grid_on, "grid_x": a.grid_x, "grid_y": a.grid_y,
        }

    def _on_preset_selected(self, _idx):
        """選択したプリセットを現在選択中の配列に反映する。"""
        name = self.preset_combo.currentData()
        a = self._current_array()
        if not name or name not in self._presets or a is None:
            return
        d = self._presets[name]
        try:
            a.x = float(d.get("x", a.x))
            a.m = int(d.get("m", a.m))
            a.p = float(d.get("p", a.p))
            a.y = float(d.get("y", a.y))
            a.n = int(d.get("n", a.n))
            a.q = float(d.get("q", a.q))
            a.comment = str(d.get("comment", ""))[:80]
            a.auto_origin = bool(d.get("auto_origin", False))
            a.grid_on = bool(d.get("grid_on", False))
            a.grid_x = max(1, int(d.get("grid_x", 5)))
            a.grid_y = max(1, int(d.get("grid_y", 5)))
        except (TypeError, ValueError):
            QMessageBox.warning(self, "プリセット適用エラー",
                                f"プリセット '{name}' の内容が不正です。")
            return
        a.apply_auto_origin()
        self.reload_from_model()
        self._notify()

    def _on_preset_save(self):
        a = self._current_array()
        if a is None:
            QMessageBox.information(self, "プリセット保存",
                                    "配列が選択されていません。")
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
        self._presets[name] = self._preset_values(a)
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

    def _on_add(self):
        if self._loading:
            return
        deck = self.ctx.deck
        if len(deck.arrays) >= LIMITS["deck"]["max_arrays"]:
            QMessageBox.warning(self, "配列追加",
                                f"配列定義数が上限 "
                                f"{LIMITS['deck']['max_arrays']} に達しています。")
            return
        a = ArrayDef()
        deck.arrays.append(a)
        self._notify()
        self.reload_from_model()
        self._select_array(a)

    def _on_delete(self):
        if self._loading:
            return
        a = self._current_array()
        if a is None:
            return
        deck = self.ctx.deck
        # 他配列からの参照チェック
        ref_set = _referenced_labels(deck).get(a.label, set()) \
            if a.label is not None else set()
        referrers = sorted(x for x in ref_set if x is not None)
        n_unlabeled = sum(1 for x in ref_set if x is None)
        if ref_set:
            names = [f"A({x})" for x in referrers]
            if n_unlabeled:
                names.append(f"ラベルなし配列 {n_unlabeled} 件")
            msg = (f"配列 {a.label} は他の配列 ({', '.join(names)}) から "
                   "ASSIGN A(...) で参照されています。\n"
                   "削除するとネスティングエラーになります。削除しますか?")
            ret = QMessageBox.warning(
                self, "参照中の配列の削除", msg,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        else:
            ret = QMessageBox.question(
                self, "配列削除", "選択中の配列定義を削除しますか?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        deck.arrays.remove(a)
        self._notify()
        self.reload_from_model()
