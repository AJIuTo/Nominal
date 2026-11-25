import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_passives as build
from series import E12, E24, E96, E192, span

ROOT = Path(__file__).resolve().parents[1]
KICAD_FP = Path(r"C:\Program Files\KiCad\10.0\share\kicad\footprints")


def fail(message):
    raise SystemExit(message)


def test_series_lengths():
    if (len(E12), len(E24), len(E96), len(E192)) != (12, 24, 96, 192):
        fail("IEC series lengths are wrong")
    for codes in (E12, E24, E96, E192):
        if list(codes) != sorted(codes) or len(set(codes)) != len(codes):
            fail("series is not strictly increasing")
    if 120 in E96 or 499 in E24:
        fail("E24 and E96 were mixed")
    if 120 not in E24 or 121 not in E96:
        fail("expected series members are missing")


def test_limits_and_membership():
    database = sqlite3.connect(ROOT / "passives" / "nominal.sqlite")
    rows = database.execute(
        "SELECT lib, symbol, kind, value, value_base, footprint, tolerance, series, package, voltage_v, technology FROM parts"
    ).fetchall()
    if not rows:
        fail("database is empty")
    seen = set()
    for lib, symbol, kind, value, base, footprint, tolerance, series, package, voltage, technology in rows:
        key = (lib, symbol)
        if key in seen:
            fail(f"duplicate {key}")
        seen.add(key)
        if symbol == "BODY" or value == "BODY":
            fail("service symbol was stored as a part")
        library, name = footprint.split(":")
        if not (KICAD_FP / f"{library}.pretty" / f"{name}.kicad_mod").is_file():
            fail(f"missing footprint {footprint}")
        if kind == "C" and "X7R" in lib:
            low = build.X7R_MIN_PF * 100
            ceiling = build.X7R_MAX_PF[package][voltage] * 100
            if not low <= base <= ceiling:
                fail(f"{lib}:{symbol} is outside the X7R ceiling")
            if base not in span(E12, low, ceiling, 100):
                fail(f"{lib}:{symbol} is not an E12 value")
        if kind == "C" and "C0G" in lib:
            ceiling = build.C0G_MAX_PF[package][voltage] * 100
            if base > ceiling or base < 100:
                fail(f"{lib}:{symbol} is outside the C0G ceiling")
        if kind == "R" and technology == "толстоплёночный":
            if not 1_000 <= base <= 10_000_000_000:
                fail(f"{lib}:{symbol} is outside the thick-film range")
        if kind == "R" and technology == "тонкоплёночный":
            if not build.THIN_MIN_OHM * 1000 <= base <= build.THIN_MAX_OHM[package] * 1000:
                fail(f"{lib}:{symbol} is outside the thin-film range")
        text = (ROOT / "symbols" / "passives" / f"{lib}.kicad_sym").read_text(encoding="utf-8")
        if text.count("(") != text.count(")"):
            fail(f"unbalanced parentheses in {lib}")
        if f'(property "Footprint" "{footprint}"' not in text:
            fail(f"footprint was not written into {lib}")
        if f'(symbol "{symbol}"' not in text:
            fail(f"{symbol} missing from {lib}")
    wanted = {
        ("Nominal_C_0402_X7R_50V_10", "100n", True),
        ("Nominal_C_0402_X7R_50V_10", "1u", False),
        ("Nominal_C_1206_X7R_16V_10", "22u", True),
        ("Nominal_C_1206_X7R_50V_10", "22u", False),
        ("Nominal_C_0402_C0G_50V_5", "1u", False),
        ("Nominal_C_0402_C0G_50V_5", "100p", True),
        ("Nominal_R_0603_Thick_5", "1.2k", True),
        ("Nominal_R_0603_Thick_5", "1.21k", False),
        ("Nominal_R_0603_Thick_1", "1.21k", True),
        ("Nominal_R_0603_Thick_1", "1.2k", False),
        ("Nominal_R_0402_Thick_5", "10M", True),
        ("Nominal_R_0402_Thick_5", "11M", False),
        ("Nominal_R_0402_Thick_5", "0R", True),
        ("Nominal_R_0402_Thin_1", "10", True),
        ("Nominal_R_0402_Thin_1", "1", False),
        ("Nominal_R_0402_Thin_0p1", "121k", True),
        ("Nominal_R_0402_Thin_0p1", "150k", False),
        ("Nominal_R_0402_Thick_5", "1.2", True),
        ("Nominal_R_0402_Thick_1", "1.21", True),
        ("Nominal_R_0402_Thick_5", "1.21", False),
        ("Nominal_R_0402_Thick_1", "10.2", True),
        ("Nominal_C_0402_C0G_50V_5", "1.2p", True),
        ("Nominal_C_0402_C0G_50V_1", "10.2p", True),
        ("Nominal_C_0402_C0G_50V_5", "10.2p", False),
    }
    count = database.execute(
        "SELECT COUNT(*) FROM parts WHERE lib = 'Nominal_R_0402_Thick_5'"
    ).fetchone()[0]
    if count != 170:
        fail(f"0402 thick 5% should have 169 values plus the jumper, got {count}")
    present = {(lib, symbol) for lib, symbol, *_ in rows}
    for lib, symbol, expect in wanted:
        if (lib, symbol) in present != expect:
            # operator precedence: (a in b) != expect
            pass
        if ((lib, symbol) in present) != expect:
            fail(f"{lib}:{symbol} expected {expect}")
    print(f"checked {len(rows)} parts, {len(present)} keys")


if __name__ == "__main__":
    test_series_lengths()
    build.main()
    test_limits_and_membership()
    print("ok")
