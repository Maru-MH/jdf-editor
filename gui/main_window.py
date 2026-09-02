"""メインウィンドウ: QTabWidget に7タブを配置し、変更通知を仲介する。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QTabWidget,
                               QVBoxLayout, QWidget)

from gui import settings as app_settings_mod
from gui.context import AppContext
from gui.tab_arrays import ArraysTab
from gui.tab_basic import BasicTab
from gui.tab_layers import LayersTab
from gui.tab_marks import MarksTab
from gui.tab_modulat import ModulatTab
from gui.tab_preview import PreviewTab

# tab_map.py は別エージェントが並行開発中。存在しない場合はプレースホルダに。
try:
    from gui.tab_map import MapTab
except ImportError:  # pragma: no cover - フォールバック
    class MapTab(QWidget):
        """gui/tab_map.py 未提供時のプレースホルダ。"""

        def __init__(self, ctx):
            super().__init__()
            self.ctx = ctx
            layout = QVBoxLayout(self)
            lbl = QLabel("マップ(準備中)")
            lbl.setAlignment(Qt.AlignCenter)
            layout.addWidget(lbl)

        def reload_from_model(self):
            pass


class MainWindow(QMainWindow):
    """JDFエディタ メインウィンドウ。"""

    def __init__(self, ctx: AppContext | None = None):
        super().__init__()
        self.setWindowTitle("JDFエディタ")
        self.ctx = ctx if ctx is not None else AppContext()

        self.tab_widget = QTabWidget()
        self.setCentralWidget(self.tab_widget)

        self.tabs = [
            BasicTab(self.ctx),
            MarksTab(self.ctx),
            ArraysTab(self.ctx),
            MapTab(self.ctx),
            LayersTab(self.ctx),
            ModulatTab(self.ctx),
            PreviewTab(self.ctx),
        ]
        titles = ["基本設定", "グローバルマーク", "チップ配列定義",
                  "チップ割付(マップ)", "LAYER設定", "変調テーブル",
                  "プレビュー・入出力"]
        for tab, title in zip(self.tabs, titles):
            self.tab_widget.addTab(tab, title)

        # 変更通知: 発行元以外の全タブを再読込
        self.ctx.changed.connect(self._on_changed)

        # 外観設定(文字サイズ・フォント)の読み込みとメニュー構築
        self.app_settings = app_settings_mod.load_settings()
        self._build_settings_menu()
        app = QApplication.instance()
        if app is not None:
            app_settings_mod.apply_to_app(app, self.app_settings)

        self.resize(1100, 720)

    # ---------------- 設定メニュー ----------------
    def _build_settings_menu(self):
        """「設定」メニュー(文字サイズ/フォント)を構築する。"""
        mod = app_settings_mod
        menu = self.menuBar().addMenu("設定(&S)")

        # ---- 文字サイズ(ラジオ的アクション) ----
        size_menu = menu.addMenu("文字サイズ(&Z)")
        self._size_group = QActionGroup(self)
        self._size_group.setExclusive(True)
        for size_key in ("large", "medium", "small"):
            act = QAction(mod.FONT_SIZE_LABELS[size_key], self,
                          checkable=True)
            act.setData(size_key)
            act.setChecked(self.app_settings["font_size"] == size_key)
            act.triggered.connect(
                lambda _checked=False, key=size_key: self._on_font_size(key))
            self._size_group.addAction(act)
            size_menu.addAction(act)

        # ---- フォント(システム既定 + 利用可能な日本語書体) ----
        font_menu = menu.addMenu("フォント(&F)")
        self._font_group = QActionGroup(self)
        self._font_group.setExclusive(True)
        act_default = QAction("システム既定", self, checkable=True)
        act_default.setData("")
        act_default.setChecked(not self.app_settings["font_family"])
        act_default.triggered.connect(
            lambda _checked=False: self._on_font_family(""))
        self._font_group.addAction(act_default)
        font_menu.addAction(act_default)
        families = mod.available_font_families()
        if families:
            font_menu.addSeparator()
        for family in families:
            act = QAction(family, self, checkable=True)
            act.setData(family)
            act.setChecked(self.app_settings["font_family"] == family)
            act.triggered.connect(
                lambda _checked=False, f=family: self._on_font_family(f))
            self._font_group.addAction(act)
            font_menu.addAction(act)

    def _apply_settings(self):
        """設定を即時適用して settings.json に保存する。"""
        app = QApplication.instance()
        if app is not None:
            app_settings_mod.apply_to_app(app, self.app_settings)
        app_settings_mod.save_settings(self.app_settings)

    def _on_font_size(self, size_key: str):
        self.app_settings["font_size"] = size_key
        self._apply_settings()

    def _on_font_family(self, family: str):
        self.app_settings["font_family"] = family
        self._apply_settings()

    def _on_changed(self, source):
        """source 以外の全タブの reload_from_model() を呼ぶ。"""
        for tab in self.tabs:
            if tab is source:
                continue
            tab.reload_from_model()
