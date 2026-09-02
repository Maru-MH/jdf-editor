"""JDF インポート。JDF テキストを JobDeck に変換する。

解析で得られた非致命の警告は deck.parse_warnings (list[str]) に格納する。
"""
from __future__ import annotations

import re

from .model import (JobDeck, ArrayDef, AssignCell, ChipDef, Layer,
                    ModulatTable, KIND_CHIP, KIND_ARRAY)


class ParseError(ValueError):
    """JDF 解析の致命的エラー(JOB/END 欠如など)。"""


_NUM = r"[-+]?\d+(?:\.\d+)?"
# 既知コマンド集合(実装対象)
_KNOWN = {"JOB", "GLMPOS", "GLMP", "PATH", "ARRAY", "ASSIGN", "AEND",
          "PEND", "LAYER", "P", "SPPRM", "SCALE", "EOS", "SHOT",
          "RESIST", "STDCUR", "MODULAT", "END"}
# 裸パラメータ行の先頭文字候補
_BARE_START = set("0123456789'(-+")


def _split_comment(line: str):
    """クォート外の最初の ';' でコード部とコメント部に分割。"""
    inq = False
    for i, ch in enumerate(line):
        if ch == "'":
            inq = not inq
        elif ch == ";" and not inq:
            return line[:i], line[i + 1:]
    return line, None


def _split_top(text: str) -> list:
    """括弧・クォートを考慮してトップレベルのカンマで分割。"""
    parts, depth, inq, buf = [], 0, False, []
    for ch in text:
        if ch == "'":
            inq = not inq
            buf.append(ch)
            continue
        if inq:
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _num(s: str):
    """数値文字列を int または float に。"""
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return float(s)


_DECORATION = set("-=* 　")


def _clean_comment(comment):
    """インラインコメントを整形して返す。

    ハイフン・等号・アスタリスク・空白のみの装飾的コメント
    (人手の区切り線 `;------` など)は内容を持たないため None を返す。
    """
    if comment is None:
        return None
    c = comment.strip()
    if not c or all(ch in _DECORATION for ch in c):
        return None
    return c


def _split_label(code: str):
    """先頭ラベル `a:` / `name:` / `'name':` を分離。(label, rest)"""
    m = re.match(r"^(\d+)\s*:\s*(.*)$", code, re.S)
    if m:
        return int(m.group(1)), m.group(2)
    m = re.match(r"^'([^']+)'\s*:\s*(.*)$", code, re.S)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^([A-Za-z][A-Za-z0-9]{0,5})\s*:\s*(.*)$", code, re.S)
    if m:
        return m.group(1), m.group(2)
    return None, code


def _command_word(code: str):
    """コマンド語と残りを返す。コマンド形式でなければ (None, code)。"""
    m = re.match(r"^([A-Za-z]+)\s*(.*)$", code, re.S)
    if not m:
        return None, code
    return m.group(1).upper(), m.group(2)


def _logical_lines(text: str) -> list:
    """物理行を前処理して (行番号, コード, コメント) のリストにする。

    - 行頭 `-` は直前論理行への継続として結合
    - クォート外 `;` 以降をコメント分離
    """
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        raw = raw.rstrip()
        if raw.startswith("-") and out:
            # 継続行: 直前のコード部に連結
            prev_no, prev_code, prev_com = out[-1]
            cont, com = _split_comment(raw[1:])
            out[-1] = (prev_no, prev_code.rstrip() + cont.strip(),
                       prev_com if prev_com is not None else com)
            continue
        code, com = _split_comment(raw)
        # コメント本文は ';' 直後の文字列を保持(前後空白は各ハンドラで調整)
        out.append((lineno, code.strip(), com))
    return out


def _expand_spec(spec: str, upper: int) -> list:
    """配列点指定 `a` / `a-b` / `*` を整数リストに展開。"""
    spec = spec.strip()
    if spec == "*":
        return list(range(1, upper + 1))
    m = re.match(r"^(\d+)\s*-\s*(\d+)$", spec)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return list(range(min(a, b), max(a, b) + 1))
    if spec.isdigit():
        return [int(spec)]
    return []


def _parse_job(code: str, deck: JobDeck):
    """JOB 行を解析。code は 'JOB...' 全体。"""
    m = re.match(r"^JOB\s*(/W)?\s*(.*)$", code, re.S)
    rest = m.group(2)
    deck.wafer = bool(m.group(1))
    parts = _split_top(rest)
    # 先頭はジョブ名(空可)
    name = parts[0].strip().strip("'").strip() if parts else ""
    if name and not deck.job_name:
        deck.job_name = name
    if len(parts) >= 2 and parts[1].strip():
        try:
            deck.material_size = _num(parts[1])
        except ValueError:
            pass
    if len(parts) >= 3 and parts[2].strip():
        d2 = parts[2].strip().rstrip("MmIi")  # 単位サフィックス除去
        try:
            deck.circle_diameter = _num(d2)
        except ValueError:
            pass


def _parse_glmpos(params: str, deck: JobDeck, warnings: list, lineno: int):
    pat = re.compile(rf"([PQRS])\s*=\s*\(\s*({_NUM})\s*,\s*({_NUM})\s*\)")
    found = pat.findall(params)
    if not found:
        warnings.append(f"{lineno}行: GLMPOS 解釈不能: {params!r}")
    for letter, x, y in found:
        deck.glmpos[letter] = [_num(x), _num(y)]


def _parse_array(label, params: str, comment, warnings: list, lineno: int) -> ArrayDef:
    m = re.search(
        rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*,\s*({_NUM})[^)]*\)"
        rf"\s*/\s*"
        rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*,\s*({_NUM})[^)]*\)",
        params)
    if not m:
        warnings.append(f"{lineno}行: ARRAY パラメータ解釈不能: {params!r}")
        return ArrayDef()
    x, mm, p, y, n, q = m.groups()
    arr = ArrayDef(
        label=label if isinstance(label, int) else None,
        x=_num(x), m=int(float(mm)), p=_num(p),
        y=_num(y), n=int(float(n)), q=_num(q))
    c = _clean_comment(comment)
    if c:
        arr.comment = c
    return arr


def _parse_assign(params: str, arr, warnings: list, lineno: int):
    if arr is None:
        warnings.append(f"{lineno}行: ARRAY 外の ASSIGN を無視")
        return
    m = re.match(r"^(.*?)\s*->\s*(.*)$", params, re.S)
    if not m:
        warnings.append(f"{lineno}行: ASSIGN に '->' なし: {params!r}")
        return
    lhs, rhs = m.group(1), m.group(2)
    targets = []
    for t in re.finditer(r"([PA])\s*\(\s*(\d+)\s*\)", lhs):
        targets.append((t.group(1), int(t.group(2))))
    if not targets:
        warnings.append(f"{lineno}行: ASSIGN 左辺解釈不能: {lhs!r}")
        return
    if len(targets) > 1:
        warnings.append(f"{lineno}行: 複数ターゲット ASSIGN は最後のみ有効")
    rhs = rhs.strip()
    tables: list = []
    point_texts: list = []
    if rhs.startswith("((") and rhs.endswith(")"):
        # ((j,k),... ,t[,tl]) 形式
        for part in _split_top(rhs[1:-1]):
            p = part.strip()
            if p.startswith("("):
                point_texts.append(p)
            elif p:
                tables.append(p.strip().strip("'").strip())
    else:
        # (j,k) や (j,k),(j2,k2) 形式(テーブルなし)
        point_texts = [p.strip() for p in _split_top(rhs) if p.strip()]
    table = tables[0] if tables else None
    cells = []
    for pt in point_texts:
        inner = pt.strip()
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1]
        jj = _split_top(inner)
        if len(jj) < 2:
            continue
        for j in _expand_spec(jj[0], arr.m):
            for k in _expand_spec(jj[1], arr.n):
                cells.append((j, k))
    # 後着優先で上書き格納
    for kind, number in targets:
        for jk in cells:
            arr.assigns[jk] = AssignCell(kind, number, table)


def _parse_chip(params: str, comment, layer, warnings: list, lineno: int):
    m = re.match(r"^\s*\(\s*(\d+)\s*\)\s*(?:'([^']*)')?", params)
    if not m:
        warnings.append(f"{lineno}行: P コマンド解釈不能: {params!r}")
        return None
    chip = ChipDef(pseudo=int(m.group(1)), filename=m.group(2) or "")
    c = _clean_comment(comment)
    if c:
        chip.comment = c
    if layer is not None:
        layer.chips.append(chip)
    else:
        warnings.append(f"{lineno}行: LAYER 外の P を無視: {params!r}")
    return chip


def _parse_scale(params: str, layer, warnings: list, lineno: int):
    if layer is None:
        warnings.append(f"{lineno}行: LAYER 外の SCALE を無視")
        return
    parts = [p for p in _split_top(params) if p.strip()]
    try:
        sx = _num(parts[0])
        sy = _num(parts[1]) if len(parts) >= 2 else sx
        layer.scale = [sx, sy]
    except (ValueError, IndexError):
        warnings.append(f"{lineno}行: SCALE 解釈不能: {params!r}")


def _parse_shot(params: str, layer, warnings: list, lineno: int):
    if layer is None:
        warnings.append(f"{lineno}行: LAYER 外の SHOT を無視")
        return
    parts = [p.strip() for p in _split_top(params) if p.strip()]
    if parts and parts[0].upper() == "A":
        if len(parts) >= 2:
            try:
                layer.shot_s = int(float(parts[1]))
            except ValueError:
                warnings.append(f"{lineno}行: SHOT 間引き量解釈不能")
    else:
        warnings.append(f"{lineno}行: SHOT マニュアルモードは未対応: {params!r}")


def _parse_resist(params: str, layer, warnings: list, lineno: int):
    if layer is None:
        warnings.append(f"{lineno}行: LAYER 外の RESIST を無視")
        return
    parts = [p for p in _split_top(params) if p.strip()]
    try:
        layer.resist1 = _num(parts[0])
        if len(parts) >= 2:
            layer.resist2 = _num(parts[1])
    except (ValueError, IndexError):
        warnings.append(f"{lineno}行: RESIST 解釈不能: {params!r}")


def _parse_modulat(label, params: str, comment, deck: JobDeck,
                   warnings: list, lineno: int):
    if label is None:
        warnings.append(f"{lineno}行: テーブル名なしの MODULAT を無視")
        return
    name = str(label).strip("'").strip()
    if any(t.name == name for t in deck.modulats):
        return  # 同名は最初の出現を採用(レイヤー横断マージ)
    pairs = []
    # (r,v) 形式のみ対象。3要素の等比形式は未対応
    if re.search(r"\(\s*[-\d.]+\s*,\s*[-\d.]+\s*,\s*[-\d.]+\s*\)", params):
        warnings.append(f"{lineno}行: 等比間隔形式の MODULAT は未対応: {name}")
        return
    for r, v in re.findall(rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*\)", params):
        pairs.append((_num(r), _num(v)))
    tbl = ModulatTable(name=name, pairs=pairs)
    c = _clean_comment(comment)
    if c:
        tbl.comment = c
    deck.modulats.append(tbl)


def parse_jdf(text: str) -> JobDeck:
    """JDF テキストを解析して JobDeck を返す。致命的欠陥は ParseError。"""
    deck = JobDeck()
    warnings: list = []
    lines = _logical_lines(text)

    seen_job = False
    seen_end = False
    cur_array: ArrayDef | None = None
    cur_layer: Layer | None = None
    cur_chip: ChipDef | None = None
    pending = None    # [cmd, idx, layer] パラメータ未取得の GLMP/EOS
    last_bare = None  # [text, idx] 未結合の裸パラメータ行

    def apply_glmp(params: str):
        nums = [p for p in _split_top(params) if p.strip()]
        if len(nums) >= 2:
            try:
                deck.glmp = [_num(nums[0]), _num(nums[1])]
            except ValueError:
                warnings.append(f"GLMP パラメータ解釈不能: {params!r}")

    def apply_eos(params: str, layer):
        if layer is None:
            warnings.append(f"EOS がレイヤー外: {params!r}")
            return
        parts = _split_top(params)
        try:
            layer.eos_mode = int(parts[0].strip())
        except (ValueError, IndexError):
            warnings.append(f"EOS モード解釈不能: {params!r}")
            return
        if len(parts) >= 2:
            layer.eos_cond = parts[1].strip().strip("'").strip()

    for idx, (lineno, code, comment) in enumerate(lines):
        if seen_end:
            break  # END 以降はジョブデックに影響なし
        if not code:
            # 空行 / 行頭コメント行
            if comment is not None and not seen_job:
                deck.header_comments.append(comment)
            # JOB 以降のスタンドアロンコメント(セクション区切り等)は
            # 警告なしで静かにスキップ(生成物の再インポートで警告が出ないように)
            continue
        label, rest = _split_label(code)
        word, params = _command_word(rest)
        is_command = word in _KNOWN if word else False

        # ---- JOB より前: ジョブ名行 ----
        if not seen_job:
            if is_command and word == "JOB":
                seen_job = True
                _parse_job(rest, deck)
            elif is_command:
                warnings.append(f"{lineno}行: JOB より前のコマンドを無視: {code}")
            elif not deck.job_name:
                deck.job_name = code.strip()
            else:
                warnings.append(f"{lineno}行: 2つ目のジョブ名行を無視: {code}")
            continue

        # ---- 裸パラメータ行(行またぎ GLMP/EOS の結合) ----
        if not is_command and label is None and code[0] in _BARE_START:
            if pending is not None and idx - pending[1] <= 5:
                if pending[0] == "GLMP":
                    apply_glmp(code)
                else:
                    apply_eos(code, pending[2])
                pending = None
            else:
                last_bare = [code, idx]
            continue

        if not is_command:
            warnings.append(f"{lineno}行: 未知コマンドをスキップ: {code}")
            continue

        # ---- 既知コマンド ----
        if word == "END":
            seen_end = True
        elif word == "JOB":
            _parse_job(rest, deck)  # 後着優先
        elif word == "GLMPOS":
            _parse_glmpos(params, deck, warnings, lineno)
        elif word == "GLMP":
            if params.strip():
                apply_glmp(params)
            elif last_bare is not None and idx - last_bare[1] <= 2:
                apply_glmp(last_bare[0])
                last_bare = None
            else:
                pending = ["GLMP", idx, None]
        elif word == "PATH":
            deck.path_name = params.strip()
        elif word == "ARRAY":
            cur_array = _parse_array(label, params, comment, warnings, lineno)
            deck.arrays.append(cur_array)
        elif word == "ASSIGN":
            _parse_assign(params, cur_array, warnings, lineno)
        elif word == "AEND":
            cur_array = None
        elif word == "PEND":
            cur_array = None
        elif word == "LAYER":
            m = re.match(rf"^({_NUM})", params.strip())
            if m:
                cur_layer = Layer(number=int(float(m.group(1))))
                c = _clean_comment(comment)
                if c:
                    cur_layer.comment = c
                deck.layers.append(cur_layer)
                cur_chip = None
            else:
                warnings.append(f"{lineno}行: LAYER 番号なし: {code}")
        elif word == "P":
            cur_chip = _parse_chip(params, comment, cur_layer, warnings, lineno)
        elif word == "SPPRM":
            fields = [p.strip() for p in _split_top(params)]
            fields = (fields + [""] * 6)[:6]
            if cur_chip is not None:
                cur_chip.spprm = fields
            else:
                warnings.append(f"{lineno}行: 紐付け先の P がない SPPRM を無視")
        elif word == "SCALE":
            _parse_scale(params, cur_layer, warnings, lineno)
        elif word == "EOS":
            if params.strip():
                apply_eos(params, cur_layer)
            elif last_bare is not None and idx - last_bare[1] <= 2:
                apply_eos(last_bare[0], cur_layer)
                last_bare = None
            else:
                pending = ["EOS", idx, cur_layer]
        elif word == "SHOT":
            _parse_shot(params, cur_layer, warnings, lineno)
        elif word == "RESIST":
            _parse_resist(params, cur_layer, warnings, lineno)
        elif word == "STDCUR":
            if cur_layer is not None:
                try:
                    cur_layer.stdcur = _num(params.strip())
                except ValueError:
                    warnings.append(f"{lineno}行: STDCUR 解釈不能: {code}")
            else:
                warnings.append(f"{lineno}行: LAYER 外の STDCUR を無視")
        elif word == "MODULAT":
            _parse_modulat(label, params, comment, deck, warnings, lineno)

    if pending is not None:
        warnings.append(f"パラメータ未取得の {pending[0]} 行を無視")
    if last_bare is not None:
        warnings.append(f"結合先のない裸パラメータ行を無視: {last_bare[0]}")
    if not seen_job:
        raise ParseError("JOB コマンドが見つかりません")
    if not seen_end:
        raise ParseError("END コマンドが見つかりません")
    deck.parse_warnings = warnings
    return deck
