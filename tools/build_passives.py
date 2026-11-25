"""Build the Nominal passive libraries.

Each KiCad library is one fixed combination: package, dielectric or film,
voltage, and tolerance. Inside it are only the IEC values that fit under
that combination's ceiling. The footprint is stored on every symbol.
"""

import json
import sqlite3
from pathlib import Path

from series import E12, E24, E96, E192, span

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "symbols" / "passives"
DB = ROOT / "passives" / "nominal.sqlite"

SIZES = ("0402", "0603", "0805", "1206")

FOOTPRINTS = {
    "C": {
        "0402": "Capacitor_SMD:C_0402_1005Metric",
        "0603": "Capacitor_SMD:C_0603_1608Metric",
        "0805": "Capacitor_SMD:C_0805_2012Metric",
        "1206": "Capacitor_SMD:C_1206_3216Metric",
    },
    "R": {
        "0402": "Resistor_SMD:R_0402_1005Metric",
        "0603": "Resistor_SMD:R_0603_1608Metric",
        "0805": "Resistor_SMD:R_0805_2012Metric",
        "1206": "Resistor_SMD:R_1206_3216Metric",
    },
}

# Maximum capacitance in pF, inclusive.
# X7R ceilings follow current general-purpose catalogs (Samsung CL, Yageo CC,
# Murata GRM): 100 nF exists in 0402/50 V, 1 µF does not. The old Yageo
# high-capacitance guide is the source for the upper steps (1 µF, 2.2 µF,
# 4.7 µF, 10 µF, 22 µF) against voltage.
X7R_MAX_PF = {
    "0402": {10: 470_000, 16: 220_000, 25: 100_000, 50: 100_000},
    "0603": {10: 2_200_000, 16: 2_200_000, 25: 1_000_000, 50: 1_000_000},
    "0805": {10: 10_000_000, 16: 10_000_000, 25: 4_700_000, 50: 1_000_000},
    "1206": {10: 22_000_000, 16: 22_000_000, 25: 10_000_000, 50: 4_700_000},
}
X7R_MIN_PF = 100

# C0G/NP0. Percent tolerance starts at 1 pF; ±1% (E96) starts at 10 pF,
# because smaller values are sold with an absolute picofarad tolerance.
C0G_MAX_PF = {
    "0402": {50: 1_000, 100: 470},
    "0603": {50: 10_000, 100: 2_200},
    "0805": {50: 22_000, 100: 10_000},
    "1206": {50: 100_000, 100: 22_000},
}

# Thick film: Yageo RC. 1 ohm through 10 Mohm, both ends included.
# Thin film: Yageo RT ceilings, same for every tolerance of that size.
THICK_OHM = (1, 10_000_000)
THIN_MAX_OHM = {
    "0402": 121_000,
    "0603": 681_000,
    "0805": 1_500_000,
    "1206": 1_500_000,
}
THIN_MIN_OHM = 10

THICK_POWER = {"0402": "0.063W", "0603": "0.1W", "0805": "0.125W", "1206": "0.25W"}
THICK_VOLTAGE = {"0402": 50, "0603": 75, "0805": 150, "1206": 200}
POWER_RU = {
    "0.063W": "0,063 Вт",
    "0.1W": "0,1 Вт",
    "0.125W": "0,125 Вт",
    "0.25W": "0,25 Вт",
}


def comma(text):
    return text.replace(".", ",")


def fmt_amount(amount, unit):
    whole, rem = divmod(amount, unit)
    if rem == 0:
        return str(whole)
    digits = []
    frac = rem
    while frac and len(digits) < 4:
        frac *= 10
        digit, frac = divmod(frac, unit)
        digits.append(str(digit))
    while digits and digits[-1] == "0":
        digits.pop()
    return f"{whole}.{''.join(digits)}"


def fmt_c(hundredths):
    if hundredths >= 100_000_000:
        return fmt_amount(hundredths, 100_000_000) + "u"
    if hundredths >= 100_000:
        return fmt_amount(hundredths, 100_000) + "n"
    return fmt_amount(hundredths, 100) + "p"


def ru_c(hundredths):
    if hundredths >= 100_000_000:
        return comma(fmt_amount(hundredths, 100_000_000)) + " мкФ"
    if hundredths >= 100_000:
        return comma(fmt_amount(hundredths, 100_000)) + " нФ"
    return comma(fmt_amount(hundredths, 100)) + " пФ"


def fmt_r(milliohms):
    if milliohms == 0:
        return "0"
    if milliohms >= 1_000_000_000:
        return fmt_amount(milliohms, 1_000_000_000) + "M"
    if milliohms >= 1_000_000:
        return fmt_amount(milliohms, 1_000_000) + "k"
    return fmt_amount(milliohms, 1_000)


def ru_r(milliohms):
    if milliohms == 0:
        return "0 Ом"
    if milliohms >= 1_000_000_000:
        return comma(fmt_amount(milliohms, 1_000_000_000)) + " МОм"
    if milliohms >= 1_000_000:
        return comma(fmt_amount(milliohms, 1_000_000)) + " кОм"
    return comma(fmt_amount(milliohms, 1_000)) + " Ом"


def prop(name, value, hide=True, at="0 0 0"):
    hidden = "\n\t\t\t(hide yes)" if hide else ""
    return (
        f'\t\t(property "{name}" "{value}"\n'
        f"\t\t\t(at {at})\n"
        f"\t\t\t(show_name no)\n"
        f"\t\t\t(do_not_autoplace no){hidden}\n"
        f"\t\t\t(effects\n"
        f"\t\t\t\t(font\n"
        f"\t\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t\t)\n"
        f"\t\t\t)\n"
        f"\t\t)"
    )


CAP_BODY = """\t\t(symbol "не_ставить_0_1"
\t\t\t(polyline
\t\t\t\t(pts
\t\t\t\t\t(xy -2.032 0.762) (xy 2.032 0.762)
\t\t\t\t)
\t\t\t\t(stroke
\t\t\t\t\t(width 0.508)
\t\t\t\t\t(type default)
\t\t\t\t)
\t\t\t\t(fill
\t\t\t\t\t(type none)
\t\t\t\t)
\t\t\t)
\t\t\t(polyline
\t\t\t\t(pts
\t\t\t\t\t(xy -2.032 -0.762) (xy 2.032 -0.762)
\t\t\t\t)
\t\t\t\t(stroke
\t\t\t\t\t(width 0.508)
\t\t\t\t\t(type default)
\t\t\t\t)
\t\t\t\t(fill
\t\t\t\t\t(type none)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(symbol "не_ставить_1_1"
\t\t\t(pin passive line
\t\t\t\t(at 0 3.81 270)
\t\t\t\t(length 2.794)
\t\t\t\t(name ""
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number "1"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(pin passive line
\t\t\t\t(at 0 -3.81 90)
\t\t\t\t(length 2.794)
\t\t\t\t(name ""
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number "2"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)"""

RES_BODY = """\t\t(symbol "не_ставить_0_1"
\t\t\t(rectangle
\t\t\t\t(start -1.016 -2.54)
\t\t\t\t(end 1.016 2.54)
\t\t\t\t(stroke
\t\t\t\t\t(width 0.254)
\t\t\t\t\t(type default)
\t\t\t\t)
\t\t\t\t(fill
\t\t\t\t\t(type none)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(symbol "не_ставить_1_1"
\t\t\t(pin passive line
\t\t\t\t(at 0 3.81 270)
\t\t\t\t(length 1.27)
\t\t\t\t(name ""
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number "1"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(pin passive line
\t\t\t\t(at 0 -3.81 90)
\t\t\t\t(length 1.27)
\t\t\t\t(name ""
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(number "2"
\t\t\t\t\t(effects
\t\t\t\t\t\t(font
\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)"""


def body_symbol(reference, graphic):
    return "\n".join([
        '\t(symbol "не_ставить"',
        "\t\t(pin_numbers",
        "\t\t\t(hide yes)",
        "\t\t)",
        "\t\t(pin_names",
        "\t\t\t(offset 0.254)",
        "\t\t)",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom no)",
        "\t\t(on_board no)",
        "\t\t(in_pos_files no)",
        "\t\t(duplicate_pin_numbers_are_jumpers no)",
        prop("Reference", reference, hide=False, at="0.635 2.54 0"),
        prop("Value", "не ставить", hide=False, at="0.635 -2.54 0"),
        prop("Footprint", ""),
        prop("Datasheet", ""),
        prop("Description", "Служебный рисунок. На схему не ставится."),
        graphic,
        "\t\t(embedded_fonts no)",
        "\t)",
    ])


def part_symbol(reference, name, value, footprint, description, keywords, fields):
    lines = [
        f'\t(symbol "{name}"',
        '\t\t(extends "не_ставить")',
        prop("Reference", reference, hide=False, at="0.635 2.54 0"),
        prop("Value", value, hide=False, at="0.635 -2.54 0"),
        prop("Footprint", footprint),
        prop("Datasheet", ""),
        prop("Description", description),
        prop("ki_keywords", keywords),
    ]
    for key, field in fields:
        lines.append(prop(key, field))
    lines.append("\t\t(embedded_fonts no)")
    lines.append("\t)")
    return "\n".join(lines)


def write_library(path, reference, graphic, parts):
    chunks = [
        "(kicad_symbol_lib",
        "\t(version 20251024)",
        '\t(generator "nominal")',
        '\t(generator_version "1")',
        body_symbol(reference, graphic),
    ]
    for part in parts:
        chunks.append(part_symbol(reference, **part))
    chunks.append(")")
    path.write_text("\n".join(chunks) + "\n", encoding="utf-8", newline="\n")


def cap_parts(size, dielectric, voltage, tolerance, series_name, codes, low, high):
    footprint = FOOTPRINTS["C"][size]
    dielectric_text = "C0G (NP0)" if dielectric == "C0G" else "X7R"
    parts = []
    rows = []
    for pf in span(codes, low * 100, high * 100, 100):
        value = fmt_c(pf)
        description = (
            f"Конденсатор {ru_c(pf)} ±{tolerance} {dielectric_text} {voltage} В, "
            f"корпус {size}. Ряд {series_name}."
        )
        keywords = f"C capacitor {size} {dielectric} {voltage}V {tolerance} {series_name} {value}"
        fields = [
            ("Dielectric", dielectric_text),
            ("Voltage", f"{voltage}V"),
            ("Tolerance", tolerance),
            ("Series", series_name),
            ("Package", size),
        ]
        parts.append({
            "name": value,
            "value": value,
            "footprint": footprint,
            "description": description,
            "keywords": keywords,
            "fields": fields,
        })
        rows.append({
            "kind": "C",
            "value": value,
            "value_base": pf,
            "footprint": footprint,
            "tolerance": tolerance,
            "series": series_name,
            "dielectric": dielectric_text,
            "voltage_v": voltage,
            "power_w": "",
            "tcr_ppm": "",
            "technology": "MLCC",
            "package": size,
            "description": description,
            "keywords": keywords,
        })
    return parts, rows


def resistor_parts(size, technology, tolerance, series_name, codes, low, high, power, voltage):
    footprint = FOOTPRINTS["R"][size]
    film = "толстоплёночный" if technology == "thick" else "тонкоплёночный"
    parts = []
    rows = []
    for ohms in span(codes, low * 1000, high * 1000, 1000):
        tcr = 200 if technology == "thick" and ohms < 10_000 else (100 if technology == "thick" else 50)
        value = fmt_r(ohms)
        description = (
            f"Резистор {ru_r(ohms)} ±{tolerance} {film}, {POWER_RU[power]}, "
            f"{voltage} В, корпус {size}. Ряд {series_name}, ТК {tcr} ppm/°C."
        )
        keywords = f"R resistor {size} {technology} {tolerance} {series_name} {value}"
        fields = [
            ("Tolerance", tolerance),
            ("Series", series_name),
            ("Power", power),
            ("Voltage", f"{voltage}V"),
            ("TCR", f"{tcr}ppm"),
            ("Technology", film),
            ("Package", size),
        ]
        parts.append({
            "name": value,
            "value": value,
            "footprint": footprint,
            "description": description,
            "keywords": keywords,
            "fields": fields,
        })
        rows.append({
            "kind": "R",
            "value": value,
            "value_base": ohms,
            "footprint": footprint,
            "tolerance": tolerance,
            "series": series_name,
            "dielectric": "",
            "voltage_v": voltage,
            "power_w": power,
            "tcr_ppm": tcr,
            "technology": film,
            "package": size,
            "description": description,
            "keywords": keywords,
        })
    return parts, rows


def jumper(size):
    footprint = FOOTPRINTS["R"][size]
    power = THICK_POWER[size]
    voltage = THICK_VOLTAGE[size]
    description = f"Перемычка 0 Ом, {POWER_RU[power]}, корпус {size}."
    part = {
        "name": "0R",
        "value": "0",
        "footprint": footprint,
        "description": description,
        "keywords": f"R jumper 0R {size}",
        "fields": [
            ("Tolerance", ""),
            ("Series", ""),
            ("Power", power),
            ("Voltage", f"{voltage}V"),
            ("TCR", ""),
            ("Technology", "перемычка"),
            ("Package", size),
        ],
    }
    row = {
        "kind": "R",
        "value": "0",
        "value_base": 0,
        "footprint": footprint,
        "tolerance": "",
        "series": "",
        "dielectric": "",
        "voltage_v": voltage,
        "power_w": power,
        "tcr_ppm": "",
        "technology": "перемычка",
        "package": size,
        "description": description,
        "keywords": part["keywords"],
    }
    return part, row


def libraries():
    """Yield (nickname, filename, reference, graphic, description, parts, rows)."""
    for size in SIZES:
        for voltage, ceiling in X7R_MAX_PF[size].items():
            nickname = f"Nominal_C_{size}_X7R_{voltage}V_10"
            parts, rows = cap_parts(size, "X7R", voltage, "10%", "E12", E12, X7R_MIN_PF, ceiling)
            text = f"Конденсаторы {size}, X7R, {voltage} В, ±10%, ряд E12, от {ru_c(X7R_MIN_PF * 100)} до {ru_c(ceiling * 100)}."
            yield nickname, f"{nickname}.kicad_sym", "C", CAP_BODY, text, parts, rows
        for voltage, ceiling in C0G_MAX_PF[size].items():
            for tolerance, series_name, codes, low in (
                ("5%", "E24", E24, 1),
                ("1%", "E96", E96, 10),
            ):
                nickname = f"Nominal_C_{size}_C0G_{voltage}V_{tolerance.replace('%', '')}"
                parts, rows = cap_parts(size, "C0G", voltage, tolerance, series_name, codes, low, ceiling)
                text = (
                    f"Конденсаторы {size}, C0G (NP0), {voltage} В, ±{tolerance}, "
                    f"ряд {series_name}, от {ru_c(low * 100)} до {ru_c(ceiling * 100)}."
                )
                yield nickname, f"{nickname}.kicad_sym", "C", CAP_BODY, text, parts, rows
        for tolerance, series_name, codes in (("5%", "E24", E24), ("1%", "E96", E96)):
            nickname = f"Nominal_R_{size}_Thick_{tolerance.replace('%', '')}"
            parts, rows = resistor_parts(
                size, "thick", tolerance, series_name, codes,
                THICK_OHM[0], THICK_OHM[1], THICK_POWER[size], THICK_VOLTAGE[size],
            )
            if tolerance == "5%":
                part, row = jumper(size)
                parts.append(part)
                rows.append(row)
            text = (
                f"Резисторы {size}, толстая плёнка, ±{tolerance}, ряд {series_name}, "
                f"от {ru_r(THICK_OHM[0] * 1000)} до {ru_r(THICK_OHM[1] * 1000)}, "
                f"{POWER_RU[THICK_POWER[size]]}, {THICK_VOLTAGE[size]} В."
            )
            yield nickname, f"{nickname}.kicad_sym", "R", RES_BODY, text, parts, rows
        for tolerance, series_name, codes in (("1%", "E96", E96), ("0.1%", "E192", E192)):
            mark = tolerance.replace("%", "").replace(".", "p")
            nickname = f"Nominal_R_{size}_Thin_{mark}"
            ceiling = THIN_MAX_OHM[size]
            parts, rows = resistor_parts(
                size, "thin", tolerance, series_name, codes,
                THIN_MIN_OHM, ceiling, THICK_POWER[size], THICK_VOLTAGE[size],
            )
            text = (
                f"Резисторы {size}, тонкая плёнка, ±{tolerance}, ряд {series_name}, "
                f"от {ru_r(THIN_MIN_OHM * 1000)} до {ru_r(ceiling * 1000)}, "
                f"{POWER_RU[THICK_POWER[size]]}, {THICK_VOLTAGE[size]} В."
            )
            yield nickname, f"{nickname}.kicad_sym", "R", RES_BODY, text, parts, rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    connection = sqlite3.connect(DB)
    connection.execute(
        """
        CREATE TABLE parts (
            id TEXT PRIMARY KEY,
            lib TEXT NOT NULL,
            symbol TEXT NOT NULL,
            kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_base INTEGER NOT NULL,
            footprint TEXT NOT NULL,
            tolerance TEXT NOT NULL,
            series TEXT NOT NULL,
            dielectric TEXT NOT NULL,
            voltage_v INTEGER,
            power_w TEXT NOT NULL,
            tcr_ppm TEXT NOT NULL,
            technology TEXT NOT NULL,
            package TEXT NOT NULL,
            description TEXT NOT NULL,
            keywords TEXT NOT NULL
        )
        """
    )
    table_lines = ["(sym_lib_table", "\t(version 7)"]
    catalog = ["# Каталог Nominal", ""]
    total = 0
    for nickname, filename, reference, graphic, text, parts, rows in libraries():
        if not parts:
            raise SystemExit(f"empty library {nickname}")
        write_library(OUT / filename, reference, graphic, parts)
        uri = "${NOMINAL_DIR}/symbols/passives/" + filename
        table_lines.append(
            f'\t(lib (name "{nickname}") (type "KiCad") (uri "{uri}") '
            f'(options "") (descr "{text}"))'
        )
        catalog.append(f"- `{nickname}` — {len(parts)} номиналов. {text}")
        for part, row in zip(parts, rows):
            connection.execute(
                """
                INSERT INTO parts (
                    id, lib, symbol, kind, value, value_base, footprint, tolerance,
                    series, dielectric, voltage_v, power_w, tcr_ppm, technology,
                    package, description, keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{nickname}:{part['name']}", nickname, part["name"], row["kind"],
                    row["value"], row["value_base"], row["footprint"], row["tolerance"],
                    row["series"], row["dielectric"], row["voltage_v"], row["power_w"],
                    str(row["tcr_ppm"]), row["technology"], row["package"],
                    row["description"], row["keywords"],
                ),
            )
        total += len(parts)
    connection.execute("CREATE INDEX parts_lookup ON parts (kind, package, dielectric, voltage_v, tolerance, value_base)")
    connection.commit()
    connection.close()
    table_lines.append(")")
    (ROOT / "sym-lib-table-passives").write_text("\n".join(table_lines) + "\n", encoding="utf-8", newline="\n")
    (ROOT / "passives" / "CATALOG.md").write_text("\n".join(catalog) + "\n", encoding="utf-8", newline="\n")
    dbl = {
        "meta": {"version": 0},
        "name": "Nominal",
        "description": "Те же номиналы, что в символах Nominal. Для выбора в KiCad используются символьные библиотеки.",
        "source": {
            "type": "odbc",
            "dsn": "",
            "username": "",
            "password": "",
            "timeout_seconds": 5,
            "connection_string": "Driver={SQLite3 ODBC Driver};Database=${NOMINAL_DIR}/passives/nominal.sqlite;",
        },
        "libraries": [],
    }
    (ROOT / "passives" / "nominal.kicad_dbl").write_text(
        json.dumps(dbl, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"parts {total}")


if __name__ == "__main__":
    main()
