"""タブ6: 変調テーブル。

MODULAT テーブルの追加・名前変更・削除と、
選択テーブルの (r, v) ペア編集(QTableWidget)を行う。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from jdf.model import ModulatTable
from jdf.validation import LIMITS


class ModulatTab(QWidget):
    """タブ6: 変調テーブルタブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        # ---- 左: テーブル一覧 ----
        list_box = QGroupBox("変調テーブル一覧")
        list_layout = QVBoxLayout(list_box)
        self.table_list = QListWidget()
        self.table_list.setToolTip("ショットタイム変調テーブル(MODULAT)の一覧")
        self.table_list.currentRowChanged.connect(self._on_table_select)
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("追加")
        self.btn_add.setToolTip("新しい変調テーブルを追加")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_rename = QPushButton("名前変更")
        self.btn_rename.setToolTip("選択中のテーブル名を変更"
                                   "(英字始まり6文字以下の大文字英数字)")
        self.btn_rename.clicked.connect(self._on_rename)
        self.btn_del = QPushButton("削除")
        self.btn_del.setToolTip("選択中のテーブルを削除")
        self.btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_rename)
        btn_row.addWidget(self.btn_del)
        btn_row.addStretch(1)
        list_layout.addWidget(self.table_list)
        list_layout.addLayout(btn_row)

        self.ed_name = QLineEdit()
        self.ed_name.setMaxLength(6)
        self.ed_name.setToolTip("テーブル名(英字始まり6文字以下の大文字英数字)")
        list_layout.addWidget(QLabel("テーブル名:"))
        list_layout.addWidget(self.ed_name)

        # ---- 右: (r, v) ペア ----
        pair_box = QGroupBox("(r, v) ペア")
        pair_layout = QVBoxLayout(pair_box)
        self.pairs = QTableWidget(0, 2)
        self.pairs.setHorizontalHeaderLabels(["r (ショット回数)", "v (変調量 %)"])
        rlim, vlim = LIMITS["modulat"]["r"], LIMITS["modulat"]["v"]
        self.pairs.setToolTip(
            f"r: 範囲 {rlim[0]}〜{rlim[1]}、v: 範囲 {vlim[0]}〜{vlim[1]}")
        self.pairs.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self.pairs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.pairs.itemChanged.connect(self._on_pair_edited)
        pair_btn_row = QHBoxLayout()
        self.btn_add_row = QPushButton("行追加")
        self.btn_add_row.setToolTip("(r, v) ペアを1行追加")
        self.btn_add_row.clicked.connect(self._on_add_row)
        self.btn_del_row = QPushButton("行削除")
        self.btn_del_row.setToolTip("選択行を削除")
        self.btn_del_row.clicked.connect(self._on_del_row)
        pair_btn_row.addWidget(self.btn_add_row)
        pair_btn_row.addWidget(self.btn_del_row)
        pair_btn_row.addStretch(1)
        pair_layout.addWidget(self.pairs)
        pair_layout.addLayout(pair_btn_row)

        root = QHBoxLayout(self)
        root.addWidget(list_box, 1)
        root.addWidget(pair_box, 2)

        self.reload_from_model()

    # ---------------- ヘルパ ----------------
    def _current_table(self) -> ModulatTable | None:
        row = self.table_list.currentRow()
        tables = self.ctx.deck.modulats
        if 0 <= row < len(tables):
            return tables[row]
        return None

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        self._loading = True
        try:
            keep = self.table_list.currentRow()
            self.table_list.blockSignals(True)
            self.table_list.clear()
            for t in self.ctx.deck.modulats:
                QListWidgetItem(f"{t.name}  ({len(t.pairs)} ペア)",
                                self.table_list)
            self.table_list.blockSignals(False)
            if self.ctx.deck.modulats:
                row = min(max(keep, 0), len(self.ctx.deck.modulats) - 1)
                self.table_list.setCurrentRow(row)
            self._load_pairs()
        finally:
            self._loading = False

    def _load_pairs(self):
        t = self._current_table()
        has = t is not None
        for w in (self.pairs, self.btn_add_row, self.btn_del_row,
                  self.ed_name, self.btn_rename, self.btn_del):
            w.setEnabled(has)
        self.pairs.blockSignals(True)
        self.pairs.setRowCount(0)
        if has:
            self.ed_name.setText(t.name)
            self.pairs.setRowCount(len(t.pairs))
            for i, (r, v) in enumerate(t.pairs):
                self.pairs.setItem(i, 0, QTableWidgetItem(str(r)))
                self.pairs.setItem(i, 1, QTableWidgetItem(str(v)))
        else:
            self.ed_name.setText("")
        self.pairs.blockSignals(False)

    # ---------------- UI → モデル ----------------
    def _notify(self):
        if not self._loading:
            self.ctx.notify_changed(self)

    def _on_table_select(self, _row):
        if self._loading:
            return
        self._loading = True
        try:
            self._load_pairs()
        finally:
            self._loading = False

    def _validate_name(self, name: str) -> str | None:
        """テーブル名を検査。問題があればエラーメッセージを返す。"""
        if not name:
            return "テーブル名が空です。"
        if not LIMITS["name_re"].match(name):
            return (f"'{name}' は不正です。英字始まり6文字以下の"
                    "大文字英数字で入力してください。")
        return None

    def _on_add(self):
        if self._loading:
            return
        deck = self.ctx.deck
        if len(deck.modulats) >= LIMITS["deck"]["max_modulats_per_layer"]:
            QMessageBox.warning(self, "テーブル追加",
                                "テーブル数が上限に達しています。")
            return
        existing = {t.name for t in deck.modulats}
        base = "T"
        name = next((f"{base}{i}" for i in range(1, 1000)
                     if f"{base}{i}" not in existing), None)
        if name is None:
            QMessageBox.warning(self, "テーブル追加",
                                "使用可能なテーブル名がありません。")
            return
        t = ModulatTable(name=name, pairs=[(0, 100.0)])
        deck.modulats.append(t)
        self._notify()
        self.reload_from_model()
        self.table_list.setCurrentRow(len(deck.modulats) - 1)

    def _on_rename(self):
        if self._loading:
            return
        t = self._current_table()
        if t is None:
            return
        new = self.ed_name.text().strip().upper()
        if new != self.ed_name.text().strip():
            self.ed_name.setText(new)
        err = self._validate_name(new)
        if err:
            QMessageBox.warning(self, "テーブル名", err)
            self.ed_name.setText(t.name)
            return
        if new != t.name and any(x.name == new for x in self.ctx.deck.modulats):
            QMessageBox.warning(self, "テーブル名",
                                f"テーブル '{new}' は既に存在します。")
            self.ed_name.setText(t.name)
            return
        old = t.name
        t.name = new
        # ASSIGN からの参照も追従
        for a in self.ctx.deck.arrays:
            for cell in a.assigns.values():
                if cell.table == old:
                    cell.table = new
        self._notify()
        self.reload_from_model()

    def _on_delete(self):
        if self._loading:
            return
        t = self._current_table()
        if t is None:
            return
        # ASSIGN からの参照チェック
        refs = []
        for a in self.ctx.deck.arrays:
            if any(c.table == t.name for c in a.assigns.values()):
                refs.append(a.label if a.label is not None else "(番号なし)")
        msg = f"テーブル '{t.name}' を削除しますか?"
        if refs:
            msg += ("\n\n注意: このテーブルは配列 "
                    + ", ".join(str(r) for r in refs)
                    + " の ASSIGN で参照されています。")
        ret = QMessageBox.question(self, "テーブル削除", msg,
                                   QMessageBox.Yes | QMessageBox.No,
                                   QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        self.ctx.deck.modulats.remove(t)
        self._notify()
        self.reload_from_model()

    # ---- (r, v) ペア編集 ----
    def _sync_pairs_from_table(self):
        """QTableWidget の内容を ModulatTable.pairs に反映。"""
        t = self._current_table()
        if t is None:
            return
        rlim, vlim = LIMITS["modulat"]["r"], LIMITS["modulat"]["v"]
        pairs = []
        for i in range(self.pairs.rowCount()):
            ir = self.pairs.item(i, 0)
            iv = self.pairs.item(i, 1)
            try:
                r = int(ir.text()) if ir is not None and ir.text().strip() else 0
                v = float(iv.text()) if iv is not None and iv.text().strip() else 0.0
            except ValueError:
                r, v = 0, 0.0
            r = max(rlim[0], min(rlim[1], r))
            v = max(vlim[0], min(vlim[1], v))
            pairs.append((r, v))
        t.pairs = pairs
        self._notify()

    def _on_pair_edited(self, _item):
        if self._loading:
            return
        self._sync_pairs_from_table()

    def _on_add_row(self):
        if self._loading:
            return
        t = self._current_table()
        if t is None:
            return
        row = self.pairs.rowCount()
        self.pairs.blockSignals(True)
        self.pairs.insertRow(row)
        self.pairs.setItem(row, 0, QTableWidgetItem("0"))
        self.pairs.setItem(row, 1, QTableWidgetItem("100"))
        self.pairs.blockSignals(False)
        self._sync_pairs_from_table()

    def _on_del_row(self):
        if self._loading:
            return
        rows = sorted({i.row() for i in self.pairs.selectedIndexes()},
                      reverse=True)
        if not rows:
            return
        for r in rows:
            self.pairs.removeRow(r)
        self._sync_pairs_from_table()
