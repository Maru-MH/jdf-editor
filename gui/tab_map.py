"""タブ4: チップ割付マップ。

QGraphicsView/QGraphicsScene によるタイル状マップ表示と、
クリック/ドラッグによる ASSIGN 割付・解除を行う。
シーン座標は材料座標(μm)の Y を反転したもの(上が材料 +Y)。

右側パネルに表示中マップの割付集計表を持ち、
変調テーブル未指定/テーブル混在の警告表示にも対応する。
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from PySide6.QtCore import QRectF, QPointF, Qt, QEvent
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from gui import settings as app_settings
from jdf.model import KIND_CHIP, KIND_ARRAY, AssignCell

# ウエハ外形 (SEMI M1): 材料サイズ[inch] -> (直径[μm], オリフラ弦長[μm])
_WAFER_SPEC = {3: (76200.0, 22220.0), 4: (100000.0, 32500.0)}

# タイル描画色
_GRID_COLOR = QColor(200, 200, 200)      # タイル枠線(薄グレー)
_THICK_GRID_COLOR = QColor(178, 178, 178)  # 太線グリッド(強調枠と競合しないよう薄め)
_SHOT_LABEL_COLOR = QColor(90, 90, 90)   # ショット区間番号
_HILITE_COLOR = QColor(230, 85, 0)       # 選択中割付の強調枠(オレンジ系・太線)
_WARN_COLOR = QColor(220, 30, 30)        # 警告セルの枠線(赤)
_WAFER_FILL = QColor(247, 249, 252)      # ウエハ面
_WAFER_LINE = QColor(90, 90, 90)         # ウエハ外周

# 区間番号(ショット番号)の文字高さ = 配列全体の短辺スパン x この比率。
# ピッチに依存しないため、密な配列でも潰れず読めるサイズになる。
_MAP_LABEL_RATIOS = {"small": 0.015, "medium": 0.025, "large": 0.040}

_FNAME_MAX = 30   # チップ名(ファイル名)の最大表示文字数
_COMMENT_MAX = 6  # コメントの最大表示文字数


def _color_for(kind: str, number: int) -> QColor:
    """割付番号から決定的に低彩度パステル色を生成する(彩度 25〜40%)。"""
    h = (int(number) * 2654435761 + (0x9E3779B9 if kind == KIND_ARRAY else 0)) & 0xFFFFFFFF
    hue = h % 360
    sat = 0.25 + ((h >> 8) % 16) / 100.0  # 0.25〜0.40
    return QColor.fromHsvF(hue / 360.0, sat, 0.97)


def _trunc(text: str, limit: int) -> str:
    """表示用文字列を limit 文字に切り詰める(超過時は末尾に …)。"""
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 1)] + "…"


def _wafer_path(diameter: float, flat_len: float) -> QPainterPath:
    """直径 diameter・オリフラ弦長 flat_len のウエハ外形パスを返す。

    中心=原点、オリフラは上側(シーン座標で -Y 側)の弦。
    """
    r = diameter / 2.0
    d = math.sqrt(r * r - (flat_len / 2.0) ** 2)  # 弦の中心までの距離
    alpha = math.degrees(math.asin(d / r))
    path = QPainterPath()
    # 弦の左端 (角度 180-α) から下回り(270°=下)の円弧を描き、
    # closeSubpath で上側の弦に戻る (Qt は正の角度で反時計回り=90°が上)
    path.moveTo(QPointF(-flat_len / 2.0, -d))
    path.arcTo(QRectF(-r, -r, 2.0 * r, 2.0 * r), 180.0 - alpha, 180.0 + 2.0 * alpha)
    path.closeSubpath()
    return path


class _TileLayerItem(QGraphicsItem):
    """配列タイル全体を1アイテムで描画する(255x255 でも重くならないように)。

    個別の QGraphicsRectItem を並べず、paint() で露出範囲のセルのみ描く。
    セルのヒット判定も座標計算で行う。
    """

    def __init__(self, array, tab: "MapTab"):
        super().__init__()
        self._tab = tab
        self._array = None
        self._assigns = {}
        # ピッチ 0 の退化ケースは他方のピッチで代用(描画潰れ防止)
        self._pw = 1.0
        self._qh = 1.0
        self._m = 0
        self._n = 0
        self._left = 0.0   # 列 j=1 のタイル左端 (シーンX)
        self._top = 0.0    # 行 k=1 のタイル上端 (シーンY)
        # 強調する割付 (kind, number) ※テーブルは条件に含めない
        self._hilite: Optional[tuple] = None
        # 警告対象セル {(j, k), ...}
        self._warn_cells = frozenset()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemUsesExtendedStyleOption, True)
        self.setZValue(0.0)
        self.set_array(array)

    # ---------- ジオメトリ ----------
    def set_array(self, array) -> None:
        """表示対象の ArrayDef を設定(assigns は参照を保持)。"""
        self.prepareGeometryChange()
        self._array = array
        if array is None:
            self._assigns = {}
            self._m = self._n = 0
            return
        self._assigns = array.assigns
        self._m = max(0, int(array.m))
        self._n = max(0, int(array.n))
        self._pw = array.p if array.p > 0 else (array.q if array.q > 0 else 1000.0)
        self._qh = array.q if array.q > 0 else (array.p if array.p > 0 else 1000.0)
        self._left = array.x - self._pw / 2.0
        self._top = -array.y - self._qh / 2.0  # シーンY は材料Y の反転

    def set_hilite(self, key: Optional[tuple]) -> None:
        """強調する割付 (kind, number) を設定。None で解除。"""
        if self._hilite != key:
            self._hilite = key
            self.update()

    def set_warn_cells(self, cells) -> None:
        """警告対象セル {(j, k), ...} を設定(赤枠で描画)。"""
        cells = frozenset(cells)
        if self._warn_cells != cells:
            self._warn_cells = cells
            self.update()

    def boundingRect(self) -> QRectF:
        if self._array is None or self._m <= 0 or self._n <= 0:
            return QRectF()
        # 強調枠・警告枠のはみ出し分を少し広げる
        return QRectF(self._left, self._top,
                      self._m * self._pw, self._n * self._qh).adjusted(-3, -3, 3, 3)

    def cell_at(self, sx: float, sy: float) -> Optional[tuple]:
        """シーン座標から配列点 (j, k) を返す。範囲外は None。"""
        if self._array is None or self._m <= 0 or self._n <= 0:
            return None
        j = int(math.floor((sx - self._left) / self._pw)) + 1
        k = int(math.floor((sy - self._top) / self._qh)) + 1
        if 1 <= j <= self._m and 1 <= k <= self._n:
            return (j, k)
        return None

    def cells_in_rect(self, rect: QRectF) -> list:
        """シーン矩形に含まれる配列点 (j, k) のリストを返す。"""
        if self._array is None or self._m <= 0 or self._n <= 0:
            return []
        r = rect.normalized()
        j0 = max(1, int(math.floor((r.left() - self._left) / self._pw)) + 1)
        j1 = min(self._m, int(math.floor((r.right() - self._left) / self._pw)) + 1)
        k0 = max(1, int(math.floor((r.top() - self._top) / self._qh)) + 1)
        k1 = min(self._n, int(math.floor((r.bottom() - self._top) / self._qh)) + 1)
        if j0 > j1 or k0 > k1:
            return []
        return [(j, k) for k in range(k0, k1 + 1) for j in range(j0, j1 + 1)]

    # ---------- 描画 ----------
    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self._array is None or self._m <= 0 or self._n <= 0:
            return
        exposed = option.exposedRect  # アイテム座標=シーン座標
        body = QRectF(self._left, self._top, self._m * self._pw, self._n * self._qh)

        # 未割付の白地
        painter.fillRect(body, Qt.GlobalColor.white)

        # 露出範囲のセル添字
        j0 = max(1, int(math.floor((exposed.left() - self._left) / self._pw)) + 1)
        j1 = min(self._m, int(math.floor((exposed.right() - self._left) / self._pw)) + 1)
        k0 = max(1, int(math.floor((exposed.top() - self._top) / self._qh)) + 1)
        k1 = min(self._n, int(math.floor((exposed.bottom() - self._top) / self._qh)) + 1)

        # 割付済みセルの塗りつぶし(番号ごとの自動パステル色)
        for (j, k), cell in self._assigns.items():
            if j0 <= j <= j1 and k0 <= k <= k1:
                painter.fillRect(
                    QRectF(self._left + (j - 1) * self._pw,
                           self._top + (k - 1) * self._qh,
                           self._pw, self._qh),
                    _color_for(cell.kind, cell.number))

        # グリッド線(露出範囲のみ、コスメティックペンで常に細線)
        pen = QPen(_GRID_COLOR)
        pen.setCosmetic(True)
        painter.setPen(pen)
        lines = []
        for j in range(max(0, j0 - 1), min(self._m, j1) + 1):
            x = self._left + j * self._pw
            lines.append(QPointF(x, body.top()))
            lines.append(QPointF(x, body.bottom()))
        for k in range(max(0, k0 - 1), min(self._n, k1) + 1):
            y = self._top + k * self._qh
            lines.append(QPointF(body.left(), y))
            lines.append(QPointF(body.right(), y))
        painter.drawLines(lines)

        # 太線グリッド(grid_on のとき区切り線を1段太く)
        arr = self._array
        if arr.grid_on:
            tpen = QPen(_THICK_GRID_COLOR)
            tpen.setCosmetic(True)
            tpen.setWidth(2)
            painter.setPen(tpen)
            tlines = []
            cols = arr.thick_columns()
            for j in cols:
                x = self._left + (j - 1) * self._pw  # 列 j のタイル左辺
                tlines.append(QPointF(x, body.top()))
                tlines.append(QPointF(x, body.bottom()))
            if cols and self._m % max(arr.grid_x, 1) == 0:
                # 右辺が間隔の倍数位置に来る場合は右辺にも太線(区間を閉じる)
                x = self._left + self._m * self._pw
                tlines.append(QPointF(x, body.top()))
                tlines.append(QPointF(x, body.bottom()))
            rows = arr.thick_rows()
            for k in rows:
                y = self._top + (k - 1) * self._qh  # 行 k のタイル上辺
                tlines.append(QPointF(body.left(), y))
                tlines.append(QPointF(body.right(), y))
            if rows and self._n % max(arr.grid_y, 1) == 0:
                # 下辺が間隔の倍数位置に来る場合は下辺にも太線
                y = self._top + self._n * self._qh
                tlines.append(QPointF(body.left(), y))
                tlines.append(QPointF(body.right(), y))
            if tlines:
                painter.drawLines(tlines)

        # 警告対象セルを赤枠で描画
        if self._warn_cells:
            wpen = QPen(_WARN_COLOR)
            wpen.setCosmetic(True)
            wpen.setWidth(2)
            painter.setPen(wpen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for (j, k) in self._warn_cells:
                if not (j0 <= j <= j1 and k0 <= k <= k1):
                    continue
                painter.drawRect(QRectF(self._left + (j - 1) * self._pw,
                                        self._top + (k - 1) * self._qh,
                                        self._pw, self._qh))

        # 選択中の割付対象 (kind, number) と一致するセルを強調(テーブルは不問)
        if self._hilite is not None:
            hkind, hnumber = self._hilite
            hpen = QPen(_HILITE_COLOR)
            hpen.setCosmetic(True)
            hpen.setWidth(3)
            painter.setPen(hpen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for (j, k), cell in self._assigns.items():
                if not (j0 <= j <= j1 and k0 <= k <= k1):
                    continue
                if cell.kind == hkind and cell.number == hnumber:
                    painter.drawRect(QRectF(self._left + (j - 1) * self._pw,
                                            self._top + (k - 1) * self._qh,
                                            self._pw, self._qh))


class _MapView(QGraphicsView):
    """ホイールズーム・中ドラッグでパン・クリック割付を行うビュー。"""

    _ZOOM_MIN = 1e-4
    _ZOOM_MAX = 1e2

    def __init__(self, tab: "MapTab", scene: QGraphicsScene):
        super().__init__(scene)
        self._tab = tab
        self._press_scene: Optional[QPointF] = None
        self._press_view = None
        self._dragging = False
        self._rubber: Optional[QGraphicsRectItem] = None
        self._panning = False
        self._pan_last = None
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    # ---------- ズーム ----------
    def wheelEvent(self, event) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 1.0 / 1.25
        cur = self.transform().m11()
        if not (self._ZOOM_MIN <= cur * factor <= self._ZOOM_MAX):
            return
        self.scale(factor, factor)

    # ---------- マウス操作 ----------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = event.position().toPoint()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_scene = self.mapToScene(event.position().toPoint())
            self._press_view = event.position().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            pos = event.position().toPoint()
            delta = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._press_scene is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            pos = event.position().toPoint()
            if not self._dragging:
                d = (pos - self._press_view).manhattanLength()
                if d >= QApplication.startDragDistance():
                    self._dragging = True
            if self._dragging:
                rect = QRectF(self._press_scene, self.mapToScene(pos)).normalized()
                if self._rubber is None:
                    self._rubber = QGraphicsRectItem()
                    pen = QPen(QColor(30, 90, 200))
                    pen.setCosmetic(True)
                    pen.setStyle(Qt.PenStyle.DashLine)
                    self._rubber.setPen(pen)
                    self._rubber.setBrush(QBrush(QColor(30, 90, 200, 40)))
                    self._rubber.setZValue(10.0)
                    self.scene().addItem(self._rubber)
                self._rubber.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._press_scene is not None:
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._dragging:
                rect = QRectF(self._press_scene, scene_pos).normalized()
                self._clear_rubber()
                self._tab.apply_rect(rect)
            else:
                self._tab.apply_point(scene_pos)
            self._press_scene = None
            self._press_view = None
            self._dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._tab.erase_point(self.mapToScene(event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _clear_rubber(self) -> None:
        if self._rubber is not None:
            self.scene().removeItem(self._rubber)
            self._rubber = None

    # ---------- ツールチップ ----------
    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.ToolTip:
            text = self._tab.tooltip_at(self.mapToScene(event.pos()))
            if text:
                QToolTip.showText(event.globalPos(), text, self.viewport())
            else:
                QToolTip.hideText()
            return True
        return super().viewportEvent(event)


class MapTab(QWidget):
    """タブ4: チップ割付マップ。

    ctx は duck-typing で ctx.deck(JobDeck) と
    ctx.notify_changed(source) を持つこと。
    """

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self._updating = False  # reload 中の再帰通知防止ガード
        self._chip_files: dict = {}    # 擬似パターン番号 -> ファイル名
        self._chip_info: dict = {}     # 擬似パターン番号 -> (ファイル名, コメント)
        self._array_comments: dict = {}  # 配列ラベル -> ArrayDef.comment
        self._last_array_index = None  # 警告表示デフォルト適用のための表示中配列

        # --- ツールバー(1段目) ---
        self.array_combo = QComboBox()
        self.array_combo.setMinimumWidth(320)
        self.target_combo = QComboBox()
        self.target_combo.setMinimumWidth(360)  # 番号+ファイル名+コメントが見える幅
        self.table_combo = QComboBox()
        self.erase_check = QCheckBox("消去モード")

        bar = QHBoxLayout()
        bar.addWidget(QLabel("配列定義:"))
        bar.addWidget(self.array_combo, 1)
        bar.addWidget(QLabel("割付対象:"))
        bar.addWidget(self.target_combo)
        bar.addWidget(QLabel("変調テーブル:"))
        bar.addWidget(self.table_combo)
        bar.addWidget(self.erase_check)

        # --- ツールバー(2段目): 番号サイズ / 警告表示 ---
        self.label_size_combo = QComboBox()
        for key in ("large", "medium", "small"):
            self.label_size_combo.addItem(
                app_settings.MAP_LABEL_SIZE_LABELS[key], key)
        self.label_size_combo.setCurrentIndex(1)  # 既定: 中
        self.warn_check = QCheckBox("警告表示")

        hint = QLabel("左クリック: 1点割付 / 左ドラッグ: 矩形一括割付 / "
                      "右クリック: 解除 / ホイール: ズーム / 中ドラッグ: 移動")
        hint.setStyleSheet("color: #666;")

        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("番号サイズ:"))
        bar2.addWidget(self.label_size_combo)
        bar2.addWidget(self.warn_check)
        bar2.addWidget(hint, 1)

        # --- 警告表示ラベル ---
        self.warn_label = QLabel()
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(
            "background-color: #fdecea; color: #b71c1c; "
            "border: 1px solid #e57373; padding: 4px;")
        self.warn_label.hide()

        # --- シーン/ビュー ---
        self.scene = QGraphicsScene(self)
        self.view = _MapView(self, self.scene)
        self._tile: Optional[_TileLayerItem] = None

        # --- 割付集計パネル(右側) ---
        self.summary_table = QTableWidget(0, 5)
        self.summary_table.setHorizontalHeaderLabels(
            ["色", "番号", "チップ名", "コメント", "割付数"])
        self.summary_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setMinimumWidth(280)
        self._col_checks = []
        col_bar = QHBoxLayout()
        col_bar.addWidget(QLabel("表示列:"))
        for i, name in enumerate(("色", "番号", "チップ名", "コメント", "割付数")):
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.toggled.connect(
                lambda checked, col=i: self.summary_table.setColumnHidden(col, not checked))
            self._col_checks.append(cb)
            col_bar.addWidget(cb)
        col_bar.addStretch(1)

        panel = QWidget()
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(4, 0, 0, 0)
        panel_lay.addWidget(QLabel("割付集計"))
        panel_lay.addLayout(col_bar)
        panel_lay.addWidget(self.summary_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([760, 340])

        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addLayout(bar2)
        lay.addWidget(self.warn_label)
        lay.addWidget(splitter, 1)

        self.array_combo.currentIndexChanged.connect(self._on_array_changed)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self.table_combo.currentIndexChanged.connect(self._on_target_changed)
        self.label_size_combo.currentIndexChanged.connect(self._on_label_size_changed)
        self.warn_check.toggled.connect(self._on_warn_toggled)

        self.reload_from_model()

    # ---------- 公開 API ----------
    def reload_from_model(self) -> None:
        """モデル変更を反映し、コンボとシーンを再構築する。"""
        self._rebuild_chip_info()
        self._updating = True
        try:
            prev_array = self.array_combo.currentIndex()
            prev_target = self.target_combo.currentData()
            prev_table = self.table_combo.currentData()
            self._rebuild_array_combo(prev_array)
            self._rebuild_target_combo(prev_target)
            self._rebuild_table_combo(prev_table)
            self._sync_label_size_combo()
        finally:
            self._updating = False
        self._rebuild_scene()

    # ---------- コンボ再構築 ----------
    def _rebuild_array_combo(self, prev_index: int) -> None:
        self.array_combo.blockSignals(True)
        self.array_combo.clear()
        for i, a in enumerate(self.ctx.deck.arrays):
            label = f"label={a.label} " if a.label is not None else ""
            text = (f"配列{i + 1}: {label}"
                    f"({a.x:g},{a.m},{a.p:g})/({a.y:g},{a.n},{a.q:g})")
            self.array_combo.addItem(text, i)
        if self.array_combo.count():
            idx = prev_index if 0 <= prev_index < self.array_combo.count() else 0
            self.array_combo.setCurrentIndex(idx)
        self.array_combo.blockSignals(False)

    def _rebuild_target_combo(self, prev: Optional[tuple]) -> None:
        """割付対象 = 全 LAYER の chips ∪ assigns 使用番号 ∪ label 付き配列。"""
        deck = self.ctx.deck
        p_numbers = set()
        a_numbers = set()
        for layer in deck.layers:
            for chip in layer.chips:
                p_numbers.add(chip.pseudo)
        for arr in deck.arrays:
            for cell in arr.assigns.values():
                if cell.kind == KIND_CHIP:
                    p_numbers.add(cell.number)
                elif cell.kind == KIND_ARRAY:
                    a_numbers.add(cell.number)
        for arr in deck.arrays:
            if arr.label is not None:
                a_numbers.add(arr.label)

        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        restore = 0
        for n in sorted(p_numbers):
            self.target_combo.addItem(self._target_text(KIND_CHIP, n), (KIND_CHIP, n))
            if prev == (KIND_CHIP, n):
                restore = self.target_combo.count() - 1
        for n in sorted(a_numbers):
            self.target_combo.addItem(self._target_text(KIND_ARRAY, n), (KIND_ARRAY, n))
            if prev == (KIND_ARRAY, n):
                restore = self.target_combo.count() - 1
        if self.target_combo.count():
            self.target_combo.setCurrentIndex(restore)
        self.target_combo.blockSignals(False)

    def _target_text(self, kind: str, number: int) -> str:
        """割付対象コンボの表示文字列。

        P: 「P(n)  ファイル名(30字まで)  コメント(6字まで)」
        A: 「A(n)  (配列定義)  配列コメント(6字まで)」
        """
        if kind == KIND_CHIP:
            fname, comment = self._chip_info.get(number, ("", ""))
            parts = [f"P({number})"]
            if fname:
                parts.append(_trunc(fname, _FNAME_MAX))
            if comment:
                parts.append(_trunc(comment, _COMMENT_MAX))
            return "  ".join(parts)
        parts = [f"A({number})", "(配列定義)"]
        comment = self._array_comments.get(number, "")
        if comment:
            parts.append(_trunc(comment, _COMMENT_MAX))
        return "  ".join(parts)

    def _rebuild_table_combo(self, prev: Optional[str]) -> None:
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        self.table_combo.addItem("なし", None)
        restore = 0
        for t in self.ctx.deck.modulats:
            self.table_combo.addItem(t.name, t.name)
            if prev == t.name:
                restore = self.table_combo.count() - 1
        self.table_combo.setCurrentIndex(restore)
        self.table_combo.blockSignals(False)

    def _rebuild_chip_info(self) -> None:
        """擬似パターン番号 -> ファイル名/コメント、配列ラベル -> コメントの逆引き表。"""
        self._chip_files = {}
        self._chip_info = {}
        for layer in self.ctx.deck.layers:
            for chip in layer.chips:
                self._chip_files.setdefault(chip.pseudo, chip.filename)
                self._chip_info.setdefault(chip.pseudo, (chip.filename, chip.comment))
        self._array_comments = {}
        for arr in self.ctx.deck.arrays:
            if arr.label is not None:
                self._array_comments.setdefault(arr.label, arr.comment)

    # ---------- 番号サイズ設定 ----------
    def _sync_label_size_combo(self) -> None:
        """settings.json の map_label_size をコンボに反映する。"""
        key = app_settings.load_settings().get("map_label_size", "medium")
        self.label_size_combo.blockSignals(True)
        idx = self.label_size_combo.findData(key)
        self.label_size_combo.setCurrentIndex(idx if idx >= 0 else 1)
        self.label_size_combo.blockSignals(False)

    def _label_ratio(self) -> float:
        key = self.label_size_combo.currentData()
        return _MAP_LABEL_RATIOS.get(key, _MAP_LABEL_RATIOS["medium"])

    def _on_label_size_changed(self, _index: int) -> None:
        if self._updating:
            return
        key = self.label_size_combo.currentData()
        settings = app_settings.load_settings()
        settings["map_label_size"] = key
        app_settings.save_settings(settings)
        self._rebuild_scene()

    # ---------- シーン再構築 ----------
    def _current_array(self):
        idx = self.array_combo.currentData()
        arrays = self.ctx.deck.arrays
        if idx is None or not (0 <= idx < len(arrays)):
            return None
        return arrays[idx]

    def _current_target(self) -> Optional[tuple]:
        """選択中の割付対象 (kind, number)。未選択なら None。"""
        return self.target_combo.currentData()

    def _current_table(self) -> Optional[str]:
        return self.table_combo.currentData()

    def _rebuild_scene(self) -> None:
        self.scene.clear()
        self._tile = None

        # ウエハ外周(オリフラ付き円)
        size = int(round(self.ctx.deck.material_size))
        if size in _WAFER_SPEC:
            dia, flat = _WAFER_SPEC[size]
            # 下地の塗り(タイルの下)
            wafer_fill = QGraphicsPathItem(_wafer_path(dia, flat))
            wafer_fill.setBrush(QBrush(_WAFER_FILL))
            wafer_fill.setPen(QPen(Qt.PenStyle.NoPen))
            wafer_fill.setZValue(-1.0)
            self.scene.addItem(wafer_fill)
            # 外周線(タイルの上に描画して常に見えるようにする)
            wafer_line = QGraphicsPathItem(_wafer_path(dia, flat))
            wafer_line.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            pen = QPen(_WAFER_LINE)
            pen.setCosmetic(True)
            pen.setWidth(2)
            wafer_line.setPen(pen)
            wafer_line.setZValue(1.0)
            self.scene.addItem(wafer_line)

        # 配列切替時は警告表示のデフォルトを適用
        # (無ラベル配列=ON、ラベル付き配列=OFF。切替後はユーザーが変更可能)
        idx = self.array_combo.currentData()
        if idx != self._last_array_index:
            self._last_array_index = idx
            arr_for_default = self._current_array()
            default_on = arr_for_default is not None and arr_for_default.label is None
            self.warn_check.blockSignals(True)
            self.warn_check.setChecked(default_on)
            self.warn_check.blockSignals(False)

        # タイル
        arr = self._current_array()
        if arr is not None:
            self._tile = _TileLayerItem(arr, self)
            self.scene.addItem(self._tile)
            self._update_hilite()
            self._add_shot_labels(arr)

        self._refresh_warnings()
        self._refresh_summary()

        # 全体が入るように初期表示
        bounds = self.scene.itemsBoundingRect()
        if not bounds.isEmpty():
            margin = max(bounds.width(), bounds.height()) * 0.05 + 100.0
            bounds = bounds.adjusted(-margin, -margin, margin, margin)
            self.scene.setSceneRect(bounds)
            self.view.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    # ---------- 警告 ----------
    def _compute_warnings(self, arr):
        """表示中マップの警告を検出する。

        戻り値: (メッセージリスト, 警告セル {(j, k), ...})
          a) 変調テーブル未指定の割付セル(cell.table is None)
          b) 同一 (kind, number) に異なるテーブルが混在
        """
        messages = []
        warn_cells = set()
        if arr is None or not arr.assigns:
            return messages, warn_cells
        none_cells = [jk for jk, c in arr.assigns.items() if c.table is None]
        if none_cells:
            messages.append(
                f"変調テーブル未指定の割付が {len(none_cells)} セルあります")
            warn_cells.update(none_cells)
        tables = defaultdict(set)
        for c in arr.assigns.values():
            tables[(c.kind, c.number)].add(c.table)
        for (kind, number), ts in sorted(tables.items()):
            if len(ts) > 1:
                names = ", ".join(sorted(t for t in ts if t) or ["(なし)"])
                if None in ts:
                    names = ("(なし), " + names) if names else "(なし)"
                messages.append(f"{kind}({number}) に複数のテーブル({names})が混在しています")
                warn_cells.update(
                    jk for jk, c in arr.assigns.items()
                    if c.kind == kind and c.number == number)
        return messages, warn_cells

    def _refresh_warnings(self) -> None:
        """警告ラベルとタイルの赤枠を最新状態にする。"""
        arr = self._current_array()
        messages, warn_cells = self._compute_warnings(arr)
        if messages and self.warn_check.isChecked():
            self.warn_label.setText("警告: " + " / ".join(messages))
            self.warn_label.show()
        else:
            self.warn_label.hide()
            warn_cells = set()
        if self._tile is not None:
            self._tile.set_warn_cells(warn_cells)

    def _on_warn_toggled(self, _checked: bool) -> None:
        self._refresh_warnings()

    # ---------- 割付集計表 ----------
    def _refresh_summary(self) -> None:
        """表示中マップの直接の割付対象を (kind, number, table) ごとに集計する。"""
        arr = self._current_array()
        counts = defaultdict(int)
        if arr is not None:
            for c in arr.assigns.values():
                counts[(c.kind, c.number, c.table)] += 1
        rows = sorted(counts.items(),
                      key=lambda kv: (0 if kv[0][0] == KIND_CHIP else 1,
                                      kv[0][1], kv[0][2] or ""))
        self.summary_table.setRowCount(len(rows))
        for r, ((kind, number, table), count) in enumerate(rows):
            color_item = QTableWidgetItem()
            color_item.setBackground(QBrush(_color_for(kind, number)))
            self.summary_table.setItem(r, 0, color_item)

            text = f"{kind}({number})"
            if table:
                text += f" [{table}]"
            self.summary_table.setItem(r, 1, QTableWidgetItem(text))

            if kind == KIND_CHIP:
                fname, comment = self._chip_info.get(number, ("", ""))
                name_text = _trunc(fname, _FNAME_MAX) if fname else ""
            else:
                name_text = "(配列定義)"
                comment = self._array_comments.get(number, "")
            self.summary_table.setItem(r, 2, QTableWidgetItem(name_text))
            self.summary_table.setItem(
                r, 3, QTableWidgetItem(_trunc(comment, _COMMENT_MAX)))

            count_item = QTableWidgetItem(str(count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.summary_table.setItem(r, 4, count_item)
        self.summary_table.resizeColumnsToContents()
        self.summary_table.setColumnWidth(0, 28)

    # ---------- ショット区間番号 ----------
    def _add_shot_labels(self, arr) -> None:
        """grid_on の配列について、太線区間(ショット)番号をマップ外周に配置する。

        X方向の区間番号は各区間の中央・上辺のすぐ外側、
        Y方向の区間番号は各区間の中央・左辺のすぐ外側に描く。
        文字高さは配列全体の短辺スパンに対する比率で決める(ピッチ非依存)。
        シーン座標は Y 反転済み(上が材料 +Y)。
        """
        t = self._tile
        if t is None or not arr.grid_on or t._m <= 0 or t._n <= 0:
            return
        span = min(t._m * t._pw, t._n * t._qh)  # 配列全体の短辺スパン
        h = span * self._label_ratio()
        gap = h * 0.35

        def _put(text: str, cx: float, cy: float, halign: int, valign: int):
            """(cx, cy) をアンカーにテキストを配置。

            halign/valign: 0=左/上端合わせ, 1=中央, 2=右/下端合わせ。
            """
            it = QGraphicsSimpleTextItem(text)
            it.setBrush(QBrush(_SHOT_LABEL_COLOR))
            br = it.boundingRect()
            s = h / max(br.height(), 1.0)
            it.setScale(s)
            w, hh = br.width() * s, br.height() * s
            it.setPos(cx - w * halign / 2.0, cy - hh * valign / 2.0)
            it.setZValue(0.6)
            self.scene.addItem(it)

        cols = arr.thick_columns()
        for i, j in enumerate(cols):
            x0 = t._left + (j - 1) * t._pw
            if i + 1 < len(cols):
                x1 = t._left + (cols[i + 1] - 1) * t._pw
            else:
                x1 = t._left + t._m * t._pw
            # 区間番号(1,2,3,...)を区間中央・上辺のすぐ外側に
            _put(str(i + 1), (x0 + x1) / 2.0, t._top - gap, 1, 2)
        rows = arr.thick_rows()
        for i, k in enumerate(rows):
            y0 = t._top + (k - 1) * t._qh
            if i + 1 < len(rows):
                y1 = t._top + (rows[i + 1] - 1) * t._qh
            else:
                y1 = t._top + t._n * t._qh
            # 区間番号を区間中央・左辺のすぐ外側に
            _put(str(i + 1), t._left - gap, (y0 + y1) / 2.0, 2, 1)

    # ---------- コンボ通知 ----------
    def _on_array_changed(self, _index: int) -> None:
        if not self._updating:
            self._rebuild_scene()

    def _on_target_changed(self, _index: int) -> None:
        if not self._updating:
            self._update_hilite()

    def _update_hilite(self) -> None:
        if self._tile is None:
            return
        # 強調は (kind, number) の一致のみで判定(テーブルは条件に含めない)
        self._tile.set_hilite(self._current_target())

    # ---------- 割付・解除操作(ビューから呼ばれる) ----------
    def apply_point(self, scene_pos: QPointF) -> None:
        """1点の割付(消去モード時は解除)。"""
        if self._tile is None:
            return
        cell = self._tile.cell_at(scene_pos.x(), scene_pos.y())
        if cell is None:
            return
        self._apply_cells([cell], self.erase_check.isChecked())

    def apply_rect(self, rect: QRectF) -> None:
        """ラバーバンド矩形内の一括割付(消去モード時は一括解除)。"""
        if self._tile is None:
            return
        cells = self._tile.cells_in_rect(rect)
        if cells:
            self._apply_cells(cells, self.erase_check.isChecked())

    def erase_point(self, scene_pos: QPointF) -> None:
        """右クリックによる1点解除。"""
        if self._tile is None:
            return
        cell = self._tile.cell_at(scene_pos.x(), scene_pos.y())
        if cell is not None:
            self._apply_cells([cell], True)

    def _apply_cells(self, cells: list, erase: bool) -> None:
        arr = self._current_array()
        if arr is None:
            return
        changed = 0
        if erase:
            for jk in cells:
                if arr.assigns.pop(jk, None) is not None:
                    changed += 1
        else:
            target = self._current_target()
            if target is None:
                return
            kind, number = target
            table = self._current_table()
            for jk in cells:
                old = arr.assigns.get(jk)
                if old is None or old.key() != (kind, number, table):
                    arr.assigns[jk] = AssignCell(kind, number, table)
                    changed += 1
        if changed:
            if self._tile is not None:
                self._tile.update()
            self._refresh_warnings()
            self._refresh_summary()
            self.ctx.notify_changed(self)

    # ---------- ツールチップ ----------
    def tooltip_at(self, scene_pos: QPointF) -> str:
        """シーン座標のセルのツールチップ文字列を返す。"""
        if self._tile is None:
            return ""
        jk = self._tile.cell_at(scene_pos.x(), scene_pos.y())
        if jk is None:
            return ""
        j, k = jk
        arr = self._current_array()
        cell = arr.assigns.get(jk) if arr is not None else None
        # grid_on の配列ではショット番号を追記
        shot_part = ""
        if arr is not None:
            shot = arr.shot_of(j, k)
            if shot is not None:
                shot_part = f" / ショット({shot[0]},{shot[1]})"
        head = f"({j},{k})"
        if cell is None:
            return f"{head} 未割付{shot_part}"
        if cell.kind == KIND_CHIP:
            fname = self._chip_files.get(cell.number, "")
            body = f"P({cell.number})" + (f" '{fname}'" if fname else "")
        else:
            body = f"A({cell.number}) (配列定義)"
        body += f" / テーブル: {cell.table if cell.table else 'なし'}"
        return f"{head} {body}{shot_part}"
