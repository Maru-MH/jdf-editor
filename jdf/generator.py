"""JDF テキスト生成。JobDeck から JDF コマンド列を生成する。

出力は人間が読みやすいよう整形する(セクション区切り・タブ桁揃え・字下げ)。
整形は見た目のみで、コマンドの語順・パラメータ等の出力仕様は変更しない。
整形で挿入されるセパレータ/セクション名コメントは JOB より後ろにのみ
現れるため、再インポート時に header_comments へ混入せず冪等性が保たれる。
"""
from __future__ import annotations

from .model import JobDeck, ArrayDef

# セクション区切り行: ';' + ハイフン50個
SEPARATOR = ";" + "-" * 50

# インラインコメントの桁揃え: タブ幅8でカラム48(0始まり)以上の直近タブストップ
_TAB_WIDTH = 8
_COMMENT_COLUMN = 48


def fmt_num(v) -> str:
    """数値フォーマット: 整数値は整数表記、小数は末尾ゼロを落とす。

    例: 36000.0 -> "36000"、1.0099 -> "1.0099"、1.0 -> "1"
    """
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(f)


def _assign_rects(cells) -> list:
    """配列点集合 {(j,k)} を矩形範囲 (j1, j2, k1, k2) のリストにまとめる。

    行(k)ごとに j の連続ランを抽出し、上下行で同一 j ランが連続するものを
    縦に結合して矩形化する。返却は (k, j) 順。
    """
    rows: dict = {}
    for (j, k) in cells:
        rows.setdefault(k, []).append(j)
    active: dict = {}  # (j1, j2) -> [k_start, k_end]
    done: list = []    # (j1, j2, k1, k2)
    for k in sorted(rows):
        js = sorted(rows[k])
        runs = []
        s = p = js[0]
        for j in js[1:]:
            if j == p + 1:
                p = j
            else:
                runs.append((s, p))
                s = p = j
        runs.append((s, p))
        cur = set(runs)
        # 今行で途切れたランを確定
        for key in sorted(set(active) - cur):
            k1, k2 = active.pop(key)
            done.append((key[0], key[1], k1, k2))
        for (a, b) in runs:
            if (a, b) not in active:
                active[(a, b)] = [k, k]
            elif active[(a, b)][1] == k - 1:
                active[(a, b)][1] = k
            else:
                # 同一 j ランだが行が非連続: 旧ランを確定して新規開始
                k1, k2 = active[(a, b)]
                done.append((a, b, k1, k2))
                active[(a, b)] = [k, k]
    for (a, b), (k1, k2) in active.items():
        done.append((a, b, k1, k2))
    done.sort(key=lambda r: (r[2], r[0]))
    return done


def _fmt_range(a: int, b: int) -> str:
    return str(a) if a == b else f"{a}-{b}"


def _tab_pad(code: str) -> str:
    """コード部(半角ASCII前提)の後ろに付けるタブ列を返す。

    タブ幅8として、コメント開始位置がカラム48(0始まり)以上の
    直近のタブストップに来るまで '\\t' を挿入する(最低1個)。
    例: コード長20 -> 4個(カラム48)、コード長50 -> 1個(カラム56)。
    """
    col = len(code)
    n = 0
    while True:
        n += 1
        col = (col // _TAB_WIDTH + 1) * _TAB_WIDTH
        if col >= _COMMENT_COLUMN:
            return "\t" * n


def _with_comment(code: str, comment: str) -> str:
    """コード部にタブ桁揃えのインラインコメントを付ける。コメント無しならそのまま。"""
    if not comment:
        return code
    return f"{code}{_tab_pad(code)}; {comment}"


def _section(title: str) -> list:
    """セクション見出し: 空行 + セパレータ + セクション名コメント + セパレータ。"""
    return ["", SEPARATOR, f"; {title}", SEPARATOR]


def _assign_lines(arr: ArrayDef) -> list:
    """1配列の ASSIGN 行群を生成。(kind, number, table) でグループ化。"""
    groups: dict = {}
    for (j, k), cell in arr.assigns.items():
        groups.setdefault(cell.key(), []).append((j, k))
    lines = []
    for key in sorted(groups, key=lambda t: (t[0], t[1])):
        kind, number, table = key
        for (j1, j2, k1, k2) in _assign_rects(groups[key]):
            js = _fmt_range(j1, j2)
            ks = _fmt_range(k1, k2)
            if table:
                lines.append(f"ASSIGN {kind}({number})-> (({js},{ks}),{table})")
            else:
                lines.append(f"ASSIGN {kind}({number})-> ({js},{ks})")
    return lines


def _array_lines(arr: ArrayDef) -> list:
    """1配列のブロック。ASSIGN は8スペース字下げ、AEND は字下げなし。"""
    head = f"{arr.label}: " if arr.label is not None else ""
    code = (f"{head}ARRAY ({fmt_num(arr.x)},{arr.m},{fmt_num(arr.p)})"
            f"/({fmt_num(arr.y)},{arr.n},{fmt_num(arr.q)})")
    lines = [_with_comment(code, arr.comment)]
    lines.extend("        " + al for al in _assign_lines(arr))
    lines.append("AEND")
    return lines


def _layer_lines(deck: JobDeck, layer) -> list:
    """1レイヤーの内容。SPPRM は8スペース字下げ。"""
    lines = [_with_comment(f"LAYER {layer.number}", layer.comment)]
    for chip in layer.chips:
        code = f"P({chip.pseudo}) '{chip.filename}'"
        lines.append(_with_comment(code, chip.comment))
        if chip.spprm is not None:
            sp = list(chip.spprm)[:6] + [""] * 6
            lines.append("        SPPRM " + ",".join(sp[:6]))
    if layer.scale is not None:
        lines.append(f"SCALE {fmt_num(layer.scale[0])},{fmt_num(layer.scale[1])}")
    if layer.eos_cond:
        lines.append(f"EOS {layer.eos_mode},'{layer.eos_cond}'")
    lines.append(f"SHOT A,{layer.shot_s}")
    lines.append(f"RESIST {fmt_num(layer.resist1)},{fmt_num(layer.resist2)}")
    lines.append(f"STDCUR {fmt_num(layer.stdcur)}")
    # MODULAT は各レイヤー末尾にグローバルテーブルを全て出力
    for t in deck.modulats:
        pairs = ",".join(f"({r},{fmt_num(v)})" for r, v in t.pairs)
        lines.append(_with_comment(f"{t.name}: MODULAT({pairs})", t.comment))
    return lines


def generate_jdf(deck: JobDeck) -> str:
    """JobDeck から整形済み JDF テキストを生成する。末尾改行あり。"""
    lines: list = []
    # ヘッダコメント・ジョブ名・JOB (JOB より前に装飾は置かない: 冪等性維持)
    for c in deck.header_comments:
        lines.append(";" + c)
    if deck.job_name:
        lines.append(deck.job_name)
    w = "/W" if deck.wafer else ""
    lines.append(f"JOB{w} ,{fmt_num(deck.material_size)},{fmt_num(deck.circle_diameter)}")
    # グローバルマーク
    lines.extend(_section("グローバルマーク (GLMPOS/GLMP/PATH)"))
    g = deck.glmpos
    lines.append("GLMPOS " + ",".join(
        f"{k}=({fmt_num(g[k][0])},{fmt_num(g[k][1])})" for k in ("P", "Q", "R", "S")))
    if deck.glmp:
        lines.append(f"GLMP {fmt_num(deck.glmp[0])},{fmt_num(deck.glmp[1])}")
    lines.append(f"PATH {deck.path_name}" if deck.path_name else "PATH")
    # チップ配列 (無ラベル) → パターン配列 (ラベル付き)。モデル内の順序は維持
    lines.extend(_section("チップ配列 (ARRAY)"))
    pattern_section_done = False
    first_in_section = True
    for arr in deck.arrays:
        if arr.label is not None and not pattern_section_done:
            lines.extend(_section("パターン配列 (ネスティング用)"))
            pattern_section_done = True
            first_in_section = True
        if not first_in_section:
            lines.append("")  # 配列ブロック間の空行
        lines.extend(_array_lines(arr))
        first_in_section = False
    lines.append("PEND")
    # レイヤー部
    for layer in deck.layers:
        lines.extend(_section(f"LAYER {layer.number}"))
        lines.extend(_layer_lines(deck, layer))
    # 終端
    lines.extend(["", SEPARATOR, "END"])
    return "\n".join(lines) + "\n"
