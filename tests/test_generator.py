"""generator の単体テスト。"""
import re

from jdf import (JobDeck, ArrayDef, AssignCell, ChipDef, Layer, ModulatTable,
                 generate_jdf)
from jdf.generator import SEPARATOR, fmt_num, _tab_pad


def _stripped_lines(out):
    """生成テキストの行を前後空白除去で列挙(字下げ行の厳密一致用)。"""
    return [l.strip() for l in out.splitlines()]


def _content_lines(out):
    """空行・セパレータ・スタンドアロンコメントを除いたコマンド行のみ列挙。"""
    return [l for l in out.splitlines()
            if l.strip() and not l.lstrip().startswith(";")]


def _deck_with_array(assigns, m=5, n=5):
    deck = JobDeck()
    a = ArrayDef(x=-36000, m=m, p=3600, y=36000, n=n, q=3600)
    a.assigns.update(assigns)
    deck.arrays.append(a)
    deck.layers.append(Layer(number=1))
    return deck


class TestFmtNum:
    def test_int_float(self):
        assert fmt_num(36000.0) == "36000"

    def test_decimal(self):
        assert fmt_num(1.0099) == "1.0099"

    def test_one_point_zero(self):
        assert fmt_num(1.0) == "1"

    def test_negative_int(self):
        assert fmt_num(-40) == "-40"

    def test_negative_float(self):
        assert fmt_num(-99.9) == "-99.9"


class TestAssignRects:
    def test_2x2_block(self):
        """2x2 ブロックは1つの矩形範囲にまとまる。"""
        assigns = {(j, k): AssignCell("P", 1, "S11M")
                   for j in (1, 2) for k in (1, 2)}
        out = generate_jdf(_deck_with_array(assigns))
        lines = [l.strip() for l in out.splitlines()
                 if l.strip().startswith("ASSIGN")]
        assert lines == ["ASSIGN P(1)-> ((1-2,1-2),S11M)"]

    def test_single_point(self):
        assigns = {(3, 12): AssignCell("P", 1, "S11M")}
        out = generate_jdf(_deck_with_array(assigns, m=21, n=21))
        assert "ASSIGN P(1)-> ((3,12),S11M)" in _stripped_lines(out)

    def test_no_table(self):
        """テーブルなし ASSIGN は (j,k) 形式。"""
        assigns = {(1, 1): AssignCell("P", 1, None)}
        out = generate_jdf(_deck_with_array(assigns))
        assert "ASSIGN P(1)-> (1,1)" in _stripped_lines(out)

    def test_no_table_range(self):
        assigns = {(j, k): AssignCell("A", 2, None)
                   for j in (1, 2, 3) for k in (2, 3, 4)}
        out = generate_jdf(_deck_with_array(assigns))
        assert "ASSIGN A(2)-> (1-3,2-4)" in _stripped_lines(out)

    def test_non_consecutive_rows_not_merged(self):
        """行が飛んでいる同一 j ランは別矩形になる。"""
        assigns = {(j, k): AssignCell("P", 7, "S12")
                   for j in (8, 9) for k in (2, 4)}
        out = generate_jdf(_deck_with_array(assigns, m=10, n=10))
        lines = [l.strip() for l in out.splitlines()
                 if l.strip().startswith("ASSIGN")]
        assert lines == ["ASSIGN P(7)-> ((8-9,2),S12)",
                         "ASSIGN P(7)-> ((8-9,4),S12)"]

    def test_group_sort_order(self):
        """グループは (kind, number) 順、矩形は (k, j) 順。"""
        assigns = {
            (3, 3): AssignCell("P", 2, None),
            (1, 1): AssignCell("P", 2, None),
            (2, 2): AssignCell("P", 1, None),
            (4, 4): AssignCell("A", 1, None),
        }
        out = generate_jdf(_deck_with_array(assigns))
        lines = [l.strip() for l in out.splitlines()
                 if l.strip().startswith("ASSIGN")]
        assert lines == [
            "ASSIGN A(1)-> (4,4)",
            "ASSIGN P(1)-> (2,2)",
            "ASSIGN P(2)-> (1,1)",
            "ASSIGN P(2)-> (3,3)",
        ]


class TestFormats:
    def test_job_wafer(self):
        deck = JobDeck()
        deck.layers.append(Layer())
        out = generate_jdf(deck)
        assert "JOB/W ,3,0" in out.splitlines()

    def test_job_mask(self):
        deck = JobDeck(wafer=False, material_size=5)
        deck.layers.append(Layer())
        out = generate_jdf(deck)
        assert "JOB ,5,0" in out.splitlines()

    def test_glmpos_line(self):
        deck = JobDeck()
        deck.glmpos = {"P": [-27600, 450], "Q": [30000, 450],
                       "R": [-20400, 22050], "S": [-20400, -21150]}
        deck.layers.append(Layer())
        out = generate_jdf(deck)
        assert ("GLMPOS P=(-27600,450),Q=(30000,450),"
                "R=(-20400,22050),S=(-20400,-21150)") in out.splitlines()

    def test_spprm_empty_fields(self):
        """SPPRM の空フィールドは空のまま6フィールド出力。"""
        deck = JobDeck()
        layer = Layer(number=1)
        layer.chips.append(ChipDef(3, "PAN01A_M1.v30", ["8.0", "", "", "", "", "1"]))
        deck.layers.append(layer)
        out = generate_jdf(deck)
        assert "SPPRM 8.0,,,,,1" in _stripped_lines(out)

    def test_modulat_at_each_layer_end(self):
        """MODULAT は各レイヤー末尾(STDCUR の後)に全テーブル出力。"""
        deck = JobDeck()
        deck.modulats.append(ModulatTable("S11M", [(0, 300)]))
        deck.modulats.append(ModulatTable("S2", [(0, 225), (1, 250)]))
        deck.layers = [Layer(number=1), Layer(number=2)]
        # 整形で挟まる空行・セパレータ・セクション名コメントを除外して検証
        lines = _content_lines(generate_jdf(deck))
        for i, l in enumerate(lines):
            if l.startswith("LAYER"):
                # 次の LAYER か END の直前が MODULAT 群
                j = i + 1
                while not lines[j].startswith(("LAYER", "END")):
                    j += 1
                assert lines[j - 2] == "S11M: MODULAT((0,300))"
                assert lines[j - 1] == "S2: MODULAT((0,225),(1,250))"
                assert lines[j - 3].startswith("STDCUR")

    def test_array_label_and_comment(self):
        deck = JobDeck()
        a = ArrayDef(label=1, x=1500, m=1, p=3000, y=2000, n=1, q=4000,
                     comment="M")
        deck.arrays.append(a)
        deck.layers.append(Layer())
        out = generate_jdf(deck)
        line = next(l for l in out.splitlines()
                    if l.startswith("1: ARRAY"))
        # タブ桁揃え: コード部とコメント部はタブで区切られる
        parts = line.split("\t")
        assert parts[0] == "1: ARRAY (1500,1,3000)/(2000,1,4000)"
        assert parts[-1] == "; M"

    def test_end_and_trailing_newline(self):
        deck = JobDeck()
        deck.layers.append(Layer())
        out = generate_jdf(deck)
        assert out.endswith("END\n")

    def test_section_separators(self):
        """セパレータ行とセクション名コメントが出力に含まれる。"""
        deck = _deck_with_array({(1, 1): AssignCell("P", 1, "S11M")})
        deck.arrays.append(ArrayDef(label=1, x=0, m=1, p=100,
                                    y=0, n=1, q=100))
        out = generate_jdf(deck)
        lines = out.splitlines()
        assert SEPARATOR in lines
        assert "; グローバルマーク (GLMPOS/GLMP/PATH)" in lines
        assert "; チップ配列 (ARRAY)" in lines
        assert "; パターン配列 (ネスティング用)" in lines
        assert "; LAYER 1" in lines

    def test_no_pattern_section_without_labeled_array(self):
        """ラベル付き配列が無ければパターン配列セクションは出ない。"""
        deck = _deck_with_array({(1, 1): AssignCell("P", 1, "S11M")})
        out = generate_jdf(deck)
        assert "; パターン配列 (ネスティング用)" not in out.splitlines()

    def test_p_line_comment_tab_aligned(self):
        """コメント付き P 行の ';' がカラム48以降のタブストップに揃う。"""
        deck = JobDeck()
        layer = Layer(number=1)
        layer.chips.append(ChipDef(1, "NH24G_M1.v30",
                                   comment="M"))
        deck.layers.append(layer)
        out = generate_jdf(deck)
        line = next(l for l in out.splitlines() if l.startswith("P("))
        assert "\t" in line  # コメントはタブ桁揃え
        col = line.expandtabs(8).index(";")
        assert col >= 48
        assert col % 8 == 0

    def test_tab_pad(self):
        """タブ幅8でカラム48以上の直近タブストップへ(最低1個)。"""
        assert _tab_pad("x" * 20) == "\t" * 4   # カラム48
        assert _tab_pad("x" * 50) == "\t"        # カラム56
        for n in (0, 7, 8, 47, 48, 49):
            code = "x" * n
            padded = code + _tab_pad(code)
            col = len(padded.expandtabs(8))
            assert col >= 48 and col % 8 == 0

    def test_assign_and_spprm_indented(self):
        """ASSIGN/SPPRM は8スペース字下げ、AEND は字下げなし。"""
        deck = _deck_with_array({(1, 1): AssignCell("P", 1, "S11M")})
        deck.layers[0].chips.append(
            ChipDef(1, "A.v30", ["8.0", "", "", "", "", "1"]))
        lines = generate_jdf(deck).splitlines()
        assert "        ASSIGN P(1)-> ((1,1),S11M)" in lines
        assert "        SPPRM 8.0,,,,,1" in lines
        assert "AEND" in lines

    def test_structure_order(self):
        """共通部 → レイヤー部 → END の順序。"""
        deck = _deck_with_array({(1, 1): AssignCell("P", 1, "S11M")})
        deck.modulats.append(ModulatTable("S11M", [(0, 300)]))
        out = generate_jdf(deck)
        assert re.search(r"JOB/W.*GLMPOS.*PATH.*ARRAY.*AEND.*PEND.*LAYER.*END",
                         out, re.S)
