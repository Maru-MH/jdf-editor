"""タブ7: プレビュー・入出力。

生成 JDF のプレビュー表示、バリデーション警告、
JDF 保存/インポート、プロジェクト(JSON)保存/読込を行う。
"""
from __future__ import annotations

import json

from PySide6.QtGui import QFontDatabase, QFontMetricsF
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from jdf import (JobDeck, ParseError, generate_jdf, parse_jdf, validate_deck,
                 validate_nesting)


class PreviewTab(QWidget):
    """タブ7: プレビュー・入出力タブ。"""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._loading = False

        # ---- プレビュー ----
        preview_box = QGroupBox("JDF プレビュー")
        preview_layout = QVBoxLayout(preview_box)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.preview.setFont(fixed_font)
        # タブ桁揃え(タブ幅8)が正しく見えるよう、スペース8文字分を明示設定
        self.preview.setTabStopDistance(
            QFontMetricsF(fixed_font).horizontalAdvance(" ") * 8)
        self.preview.setToolTip("generate_jdf による JDF テキストのプレビュー")
        self.btn_regen = QPushButton("再生成")
        self.btn_regen.setToolTip("現在のモデルから JDF テキストを再生成")
        self.btn_regen.clicked.connect(self.reload_from_model)
        preview_layout.addWidget(self.preview, 1)
        preview_layout.addWidget(self.btn_regen)

        # ---- 警告 ----
        warn_box = QGroupBox("バリデーション警告")
        warn_layout = QVBoxLayout(warn_box)
        self.warnings = QPlainTextEdit()
        self.warnings.setReadOnly(True)
        self.warnings.setFont(QFontDatabase.systemFont(
            QFontDatabase.FixedFont))
        self.warnings.setMaximumBlockCount(1000)
        self.warnings.setToolTip("validate_deck / validate_nesting の警告一覧")
        warn_layout.addWidget(self.warnings)
        self.lbl_status = QLabel("")
        warn_layout.addWidget(self.lbl_status)

        # ---- 入出力ボタン ----
        io_box = QGroupBox("入出力")
        io_layout = QHBoxLayout(io_box)
        self.btn_save_jdf = QPushButton("JDF 保存…")
        self.btn_save_jdf.setToolTip("生成した JDF をファイルに保存 (.jdf)")
        self.btn_save_jdf.clicked.connect(self._on_save_jdf)
        self.btn_import_jdf = QPushButton("JDF インポート…")
        self.btn_import_jdf.setToolTip("既存の JDF ファイルを読み込んでモデルに変換")
        self.btn_import_jdf.clicked.connect(self._on_import_jdf)
        self.btn_save_proj = QPushButton("プロジェクト保存…")
        self.btn_save_proj.setToolTip(
            "モデルを JSON で保存 (.jdfproj.json)")
        self.btn_save_proj.clicked.connect(self._on_save_project)
        self.btn_load_proj = QPushButton("プロジェクト読込…")
        self.btn_load_proj.setToolTip(
            "保存済みプロジェクト JSON を読み込み (.jdfproj.json)")
        self.btn_load_proj.clicked.connect(self._on_load_project)
        io_layout.addWidget(self.btn_save_jdf)
        io_layout.addWidget(self.btn_import_jdf)
        io_layout.addWidget(self.btn_save_proj)
        io_layout.addWidget(self.btn_load_proj)
        io_layout.addStretch(1)

        # ---- 全体 ----
        right = QVBoxLayout()
        right.addWidget(warn_box, 1)
        right.addWidget(io_box)
        root = QHBoxLayout(self)
        root.addWidget(preview_box, 3)
        root.addLayout(right, 2)

        self.reload_from_model()

    # ---------------- モデル → UI ----------------
    def reload_from_model(self):
        """JDF テキストとバリデーション警告を再生成して表示。"""
        self._loading = True
        try:
            deck = self.ctx.deck
            try:
                text = generate_jdf(deck)
            except Exception as e:  # 生成失敗も画面に出す
                text = f"; JDF 生成中にエラーが発生しました: {e}"
            self.preview.setPlainText(text)

            messages = []
            try:
                messages.extend(validate_deck(deck))
                messages.extend(validate_nesting(deck))
            except Exception as e:
                messages.append(f"バリデーション中にエラー: {e}")
            if messages:
                self.warnings.setPlainText("\n".join(messages))
                self.lbl_status.setText(f"警告/エラー: {len(messages)} 件")
            else:
                self.warnings.setPlainText("(警告なし)")
                self.lbl_status.setText("バリデーション OK")
        finally:
            self._loading = False

    # ---------------- 入出力 ----------------
    def _on_save_jdf(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "JDF 保存", "", "JDF ファイル (*.jdf);;すべてのファイル (*)")
        if not path:
            return
        try:
            text = generate_jdf(self.ctx.deck)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "JDF 保存",
                                    f"保存しました:\n{path}")
        except OSError as e:
            QMessageBox.critical(self, "JDF 保存エラー",
                                 f"保存に失敗しました:\n{e}")

    def _on_import_jdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "JDF インポート", "",
            "JDF ファイル (*.jdf *.JDF);;すべてのファイル (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            deck = parse_jdf(text)
        except ParseError as e:
            QMessageBox.critical(self, "JDF インポートエラー",
                                 f"JDF の解析に失敗しました:\n{e}")
            return
        except OSError as e:
            QMessageBox.critical(self, "JDF インポートエラー",
                                 f"ファイルの読み込みに失敗しました:\n{e}")
            return
        self.ctx.deck = deck
        self.ctx.notify_changed(self)
        self.reload_from_model()
        QMessageBox.information(self, "JDF インポート",
                                f"インポートしました:\n{path}")

    def _on_save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "プロジェクト保存", "",
            "JDF プロジェクト (*.jdfproj.json);;すべてのファイル (*)")
        if not path:
            return
        if not path.endswith(".jdfproj.json"):
            path += ".jdfproj.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.ctx.deck.to_dict(), f,
                          ensure_ascii=False, indent=2)
            QMessageBox.information(self, "プロジェクト保存",
                                    f"保存しました:\n{path}")
        except (OSError, TypeError, ValueError) as e:
            QMessageBox.critical(self, "プロジェクト保存エラー",
                                 f"保存に失敗しました:\n{e}")

    def _on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "プロジェクト読込", "",
            "JDF プロジェクト (*.jdfproj.json);;すべてのファイル (*)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            deck = JobDeck.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError) as e:
            QMessageBox.critical(self, "プロジェクト読込エラー",
                                 f"プロジェクトの読み込みに失敗しました:\n{e}")
            return
        self.ctx.deck = deck
        self.ctx.notify_changed(self)
        self.reload_from_model()
        QMessageBox.information(self, "プロジェクト読込",
                                f"読み込みました:\n{path}")
