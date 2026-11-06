"""VNCMA draft and release documents (VNCMA Prompt 8).

From one stored `cma_run`:
- `payload()`   the public JSON (the API shape of /v1/vncma/{version}); derived statistics
                only, never raw vendor series (DECISIONS 2026-11-05).
- `write_xlsx()` sheets Summary, Macro, Building blocks, Correlation, Scenarios, Inputs, Changes.
- `markdown_vi()` a Vietnamese summary with grades and the disclaimer.
Rates in the payload are decimal strings with two places, like the rest of the API.
"""

import datetime as dt
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from core.cma.config import CLASSES, MACRO_VARS

NAMES_VI = {
    "cash_vnd": "Tiền gửi VND (12 tháng)",
    "gov_bond": "Trái phiếu Chính phủ (10 năm)",
    "corp_bond": "Trái phiếu doanh nghiệp",
    "eq_large": "Cổ phiếu vốn hoá lớn (VN30)",
    "eq_midsmall": "Cổ phiếu vừa và nhỏ (VNMID, VNSML)",
    "gold": "Vàng (giá thế giới, quy VND)",
    "usd": "Đô la Mỹ",
    "eq_global": "Cổ phiếu toàn cầu (S&P 500, quy VND)",
    "real_estate": "Bất động sản nhà ở",
}
# Spec §3: classes an optimiser may use by default (corp_bond with a weight cap).
OPTIMIZER = {
    "cash_vnd": True,
    "gov_bond": True,
    "corp_bond": True,
    "eq_large": True,
    "eq_midsmall": True,
    "gold": True,
    "usd": True,
    "eq_global": False,
    "real_estate": False,
}
GRADES_VI = {
    "A": "dữ liệu dài, nguồn trực tiếp",
    "B": "dữ liệu ngắn hơn hoặc gián tiếp",
    "C": "ít dữ liệu, dựa nhiều vào giả định",
}
MACRO_VI = {
    "pi": "Lạm phát Việt Nam (CPI)",
    "pi_us": "Lạm phát Mỹ",
    "g": "Tăng trưởng GDP thực",
    "r_star": "Lãi suất thực trung tính (liên ngân hàng)",
    "r_star_gov": "Lãi suất thực ngắn hạn của thị trường trái phiếu",
    "tp": "Phần bù kỳ hạn (10 năm trừ 1 năm)",
    "d": "Mức mất giá VND so với USD",
}
DISCLAIMER_VI = (
    "VNCMA là bộ giả định dài hạn (10 năm) để lập kế hoạch tài chính, không phải lời khuyên đầu tư "
    "hay dự báo chắc chắn. Lợi nhuận thực tế có thể khác xa các con số này, kể cả ngoài dải 80%. "
    "Soivi không nhận tiền từ tổ chức nào để thay đổi giả định hay xếp hạng."
)
DISCLAIMER_EN = (
    "VNCMA is a set of long-term (10-year) planning assumptions, not investment advice or a "
    "forecast. Actual returns can differ widely, including outside the 80% band."
)


def macro_order(name: str) -> int:
    return MACRO_VARS.index(name) if name in MACRO_VARS else len(MACRO_VARS)


def class_order(name: str) -> int:
    return CLASSES.index(name) if name in CLASSES else len(CLASSES)


def _pct(x: float | None) -> str | None:
    return None if x is None else f"{x:.2f}"


def payload(
    run: Any,
    version: str,
    *,
    status: str = "draft",
    approved_by: str | None = None,
    approved_at: dt.datetime | None = None,
) -> dict[str, Any]:
    """The public JSON for one run. `run` is a CmaRun (or anything with its fields)."""
    out = run.output
    classes = []
    for cls in [*CLASSES, *sorted(set(out["classes"]) - set(CLASSES))]:  # JSONB loses key order
        if cls not in out["classes"]:
            continue
        c = out["classes"][cls]
        row: dict[str, Any] = {
            "id": cls,
            "name": NAMES_VI.get(cls, cls),
            "expected_return": _pct(c["final"]),
            "model_return": _pct(c["model"]),
            "adjustment_pp": _pct(c["adjustment"]),
            "adjustment_reason": c.get("adjustment_reason"),
            "arithmetic_return": _pct(c["arithmetic"]),
            "volatility": _pct(None if c["vol"] is None else 100 * c["vol"]),
            "volatility_historical": _pct(None if c["vol_hist"] is None else 100 * c["vol_hist"]),
            "band_80": None
            if c["band_low"] is None
            else [_pct(c["band_low"]), _pct(c["band_high"])],
            "scenarios": {k: _pct(v) for k, v in c["scenarios"].items()},
            "grade": c["grade"],
            "optimizer_default": OPTIMIZER.get(cls, False),
            "formula": c["formula"],
        }
        if "range" in c:
            row["range"] = [_pct(c["range"]["low"]), _pct(c["range"]["high"])]
        classes.append(row)
    corr = out["correlation"]
    return {
        "version": version,
        "status": status,
        "methodology_version": out["methodology_version"],
        "as_of": out["as_of"],
        "horizon_years": out["horizon_years"],
        "currency": "VND",
        "return_basis": "geometric, nominal, percent per year",
        "approved_by": approved_by,
        "approved_at": approved_at.isoformat() if approved_at else None,
        "classes": classes,
        "correlation": {
            "classes": corr["classes"],
            "matrix": [[round(x, 2) for x in row] for row in corr["matrix"]],
        },
        "macro": {
            k: {
                "value": _pct(v["value"]),
                "name": MACRO_VI.get(k, k),
                "derivation": v["derivation"],
            }
            for k, v in sorted(out["macro"].items(), key=lambda kv: macro_order(kv[0]))
        },
        "checks": out["checks"],
        "provenance": {
            "run_id": run.id,
            "code_version": run.code_version,
            "config_sha256": run.config_sha256,
            "inputs_sha256": run.inputs_sha256,
        },
        "disclaimer": {"vi": DISCLAIMER_VI, "en": DISCLAIMER_EN},
    }


def payload_sha256(doc: Mapping[str, Any]) -> str:
    text = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def changes(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Expected return and volatility per class against the previous release."""
    if previous is None:
        return []
    before = {c["id"]: c for c in previous["classes"]}
    rows = []
    for c in current["classes"]:
        p = before.get(c["id"])
        if p is None:
            rows.append({"id": c["id"], "note": "new class"})
            continue

        def delta(key: str, c: Mapping[str, Any] = c, p: Mapping[str, Any] = p) -> str | None:
            if c.get(key) is None or p.get(key) is None:
                return None
            return f"{float(c[key]) - float(p[key]):+.2f}"

        rows.append(
            {
                "id": c["id"],
                "expected_return": c["expected_return"],
                "previous": p["expected_return"],
                "change_pp": delta("expected_return"),
                "volatility_change_pp": delta("volatility"),
            }
        )
    return rows


# --------------------------------------------------------------------------- xlsx


def write_xlsx(
    run: Any, doc: Mapping[str, Any], path: Path, previous: Mapping[str, Any] | None = None
) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    bold = Font(bold=True)

    def sheet(
        title: str, header: Sequence[str], rows: Sequence[Sequence[Any]], first: bool = False
    ) -> None:
        ws = wb.active if first else wb.create_sheet()
        assert ws is not None
        ws.title = title
        ws.append(list(header))
        for cell in ws[1]:
            cell.font = bold
        for r in rows:
            ws.append(list(r))
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 80)

    def num(x: Any) -> Any:
        return None if x is None else float(x)

    sheet(
        "Summary",
        [
            "class",
            "name",
            "expected %/yr",
            "model",
            "adjustment pp",
            "reason",
            "arithmetic",
            "volatility %",
            "band 80% low",
            "band 80% high",
            "grade",
            "optimizer",
        ],
        [
            [
                c["id"],
                c["name"],
                num(c["expected_return"]),
                num(c["model_return"]),
                num(c["adjustment_pp"]),
                c["adjustment_reason"],
                num(c["arithmetic_return"]),
                num(c["volatility"]),
                num((c["band_80"] or [None, None])[0]),
                num((c["band_80"] or [None, None])[1]),
                c["grade"],
                c["optimizer_default"],
            ]
            for c in doc["classes"]
        ],
        first=True,
    )
    ws = wb["Summary"]
    ws.append([])
    for line in (
        f"VNCMA {doc['version']} ({doc['status']}), data to {doc['as_of']}, "
        f"methodology {doc['methodology_version']}",
        f"run {run.id}, code {run.code_version}, config {run.config_sha256[:12]}, "
        f"inputs {run.inputs_sha256[:12]}",
        DISCLAIMER_VI,
    ):
        ws.append([line])
    sheet(
        "Macro",
        ["variable", "name", "value %", "derivation", "override"],
        [
            [
                k,
                MACRO_VI.get(k, k),
                round(v["value"], 4),
                v["derivation"],
                json.dumps(v["override"], ensure_ascii=False) if v["override"] else "",
            ]
            for k, v in sorted(run.output["macro"].items(), key=lambda kv: macro_order(kv[0]))
        ]
        + [[]]
        + [
            [f"param:{k}", p["note"], p["value"], p["source"], ""]
            for k, p in run.output["params"].items()
        ]
        + [
            [f"cma:{c['name']}", c["as_of"], c["value"], c["source"], ""]
            for c in run.output["global_cmas"]
        ],
    )
    sheet(
        "Building blocks",
        ["class", "formula", "inputs", "history %/yr", "history months"],
        [
            [
                k,
                c["formula"],
                ", ".join(c["inputs"]),
                None if not c["history"] else round(c["history"]["return"], 2),
                None if not c["history"] else c["history"]["months"],
            ]
            for k, c in sorted(run.output["classes"].items(), key=lambda kv: class_order(kv[0]))
        ],
    )
    corr = doc["correlation"]
    sheet(
        "Correlation",
        ["", *corr["classes"]],
        [[n, *row] for n, row in zip(corr["classes"], corr["matrix"], strict=True)],
    )
    sheet(
        "Scenarios",
        ["class", "adverse", "base", "favourable", "band 80% low", "band 80% high"],
        [
            [
                c["id"],
                num(c["scenarios"]["adverse"]),
                num(c["scenarios"]["base"]),
                num(c["scenarios"]["favourable"]),
                num((c["band_80"] or [None, None])[0]),
                num((c["band_80"] or [None, None])[1]),
            ]
            for c in doc["classes"]
        ]
        + [[], ["shocks", json.dumps(run.output["scenarios"], ensure_ascii=False)]],
    )
    sheet(
        "Inputs",
        ["series", "first", "last", "count", "sha256", "snapshots"],
        [
            [k, v["first"], v["last"], v["count"], v["sha256"], ", ".join(map(str, v["snapshots"]))]
            for k, v in run.inputs["series"].items()
        ]
        + [
            [
                "savings_12m",
                "",
                "",
                run.inputs["savings_12m"]["months"],
                run.inputs["savings_12m"]["sha256"],
                "",
            ]
        ],
    )
    diff = changes(doc, previous)
    sheet(
        "Changes",
        ["class", "expected", "previous", "change pp", "volatility change pp"],
        [
            [
                r["id"],
                r.get("expected_return"),
                r.get("previous"),
                r.get("change_pp"),
                r.get("volatility_change_pp"),
            ]
            for r in diff
        ]
        or [["first release: nothing to compare"]],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# --------------------------------------------------------------------------- markdown


def _vi(x: str | None) -> str:
    return "—" if x is None else x.replace(".", ",")


def markdown_vi(doc: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> str:
    lines = [
        f"# VNCMA {doc['version']}: giả định thị trường vốn Việt Nam 10 năm",
        "",
        f"Dữ liệu đến {doc['as_of']} · phương pháp {doc['methodology_version']} · "
        f"trạng thái: {'đã duyệt' if doc['status'] == 'released' else 'bản nháp, chưa duyệt'}"
        + (f" · người duyệt: {doc['approved_by']}" if doc.get("approved_by") else ""),
        "",
        f"> {DISCLAIMER_VI}",
        "",
        "## Lợi nhuận kỳ vọng (VND, %/năm, bình quân nhân)",
        "",
        "| Lớp tài sản | Kỳ vọng | Biến động | Dải 80% | Xấu / Tốt | Điều chỉnh | Hạng |",
        "|---|---:|---:|---|---|---:|:-:|",
    ]
    for c in doc["classes"]:
        band = (
            f"{_vi(c['band_80'][0])} đến {_vi(c['band_80'][1])}"
            if c["band_80"]
            else (
                f"khoảng {_vi(c['range'][0])} đến {_vi(c['range'][1])}" if c.get("range") else "—"
            )
        )
        s = c["scenarios"]
        adj = (
            ""
            if float(c["adjustment_pp"]) == 0
            else f"{_vi(c['adjustment_pp'])} ({c['adjustment_reason']})"
        )
        ref = "" if c["optimizer_default"] else " *(tham khảo)*"
        lines.append(
            f"| {c['name']}{ref} | {_vi(c['expected_return'])} | {_vi(c['volatility'])} | {band} | "
            f"{_vi(s['adverse'])} / {_vi(s['favourable'])} | {adj} | {c['grade']} |"
        )
    lines += [
        "",
        "Kịch bản xấu: GDP thấp hơn 1 điểm %, VND mất giá thêm 1 điểm %, P/E mục tiêu ở mức thấp "
        "(phân vị 25). Kịch bản tốt: ngược lại.",
        "Dải 80%: lợi nhuận bình quân 10 năm nằm trong khoảng này với xác suất khoảng 80% "
        "nếu biến động đúng như ước tính.",
        "",
        "Hạng dữ liệu: " + "; ".join(f"**{k}** {v}" for k, v in GRADES_VI.items()) + ".",
        "",
        "## Giả định vĩ mô",
        "",
        "| Biến | Giá trị | Cách tính |",
        "|---|---:|---|",
    ]
    for k, m in doc["macro"].items():
        lines.append(f"| {m['name']} (`{k}`) | {_vi(m['value'])} | {m['derivation']} |")
    lines += ["", "## Kiểm tra hợp lý", ""]
    lines += [f"- {c}" for c in doc["checks"]]
    diff = changes(doc, previous)
    lines += ["", "## Thay đổi so với bản trước", ""]
    if not diff:
        lines.append("Bản đầu tiên, chưa có bản trước để so sánh.")
    for r in diff:
        if r.get("change_pp") is not None:
            lines.append(
                f"- {r['id']}: {_vi(r['previous'])} → {_vi(r['expected_return'])} "
                f"({_vi(r['change_pp'])} điểm %)"
            )
    p = doc["provenance"]
    lines += [
        "",
        "## Nguồn gốc",
        "",
        f"Run {p['run_id']} · code {p['code_version']} · config `{p['config_sha256'][:12]}` · "
        f"inputs `{p['inputs_sha256'][:12]}`. "
        "Phương pháp: docs/vncma/spec.md và docs/DECISIONS.md.",
        "",
    ]
    return "\n".join(lines)


def write_all(
    run: Any, doc: Mapping[str, Any], out_dir: Path, previous: Mapping[str, Any] | None = None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"vncma-{doc['version']}"
    json_path = out_dir / f"{stem}.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", "utf-8")
    md_path = out_dir / f"{stem}.md"
    md_path.write_text(markdown_vi(doc, previous), "utf-8")
    return [write_xlsx(run, doc, out_dir / f"{stem}.xlsx", previous), json_path, md_path]
