#!/usr/bin/env python3
"""Validate and deterministically render the frozen PER-27 report contract."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import pathlib
import sys
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


ROOT = pathlib.Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "src" / "financial_agent_reliability" / "reporting" / "spec.report.v1.json"
FREEZE_PATH = ROOT / "contracts" / "report_contract.frozen.v1.json"
SHA256_FIELDS = {
    "result_bundle_sha256", "grader_policy_sha256", "preregistration_sha256",
    "harness_config_sha256", "run_manifest_sha256", "data_snapshot_sha256",
    "selection_commitment_sha256", "content_sha256", "expected_sha256",
}
RUN_STATES = {"succeeded", "failed", "blocked", "excluded", "missing"}
TRACKS = {"financial_knowledge_work", "financial_tool_workflow"}


class ReportContractError(ValueError):
    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: str | pathlib.Path) -> Any:
    with pathlib.Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_keys)


def file_sha256(path: str | pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require(ok: bool, message: str, errors: list[str]) -> None:
    if not ok:
        errors.append(message)


def _object(value: Any, path: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return {}
    return value


def _array(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be an array")
        return []
    return value


def _hashes(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in SHA256_FIELDS:
                _require(
                    isinstance(child, str) and len(child) == 64
                    and all(char in "0123456789abcdef" for char in child),
                    f"{path}/{key}: invalid SHA-256", errors,
                )
            _hashes(child, f"{path}/{key}", errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _hashes(child, f"{path}/{index}", errors)


def validate_report(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Reject ranking contamination, hidden failures, and broken provenance."""

    spec = load_json(SPEC_PATH)
    errors: list[str] = []
    allowed = {
        "contract_type", "contract_version", "report_identity", "audit", "provenance",
        "run_coverage", "ranking", "model_reports", "run_records", "failures",
        "limitations", "demonstrations", "reproduction",
    }
    _require(not (set(bundle) - allowed), f"unregistered top-level fields: {sorted(set(bundle) - allowed)}", errors)
    _require(bundle.get("contract_type") == "financial_agent_report_bundle", "invalid contract_type", errors)
    _require(bundle.get("contract_version") == "1.0.0", "unsupported contract_version", errors)

    identity = _object(bundle.get("report_identity"), "report_identity", errors)
    for field in ("report_id", "framework_version", "data_snapshot_id", "evaluation_date", "generated_at"):
        _require(bool(identity.get(field)), f"report_identity/{field}: required", errors)

    audit = _object(bundle.get("audit"), "audit", errors)
    _require(audit.get("status") == "signed", "audit must be signed before reporting", errors)
    for field in ("signed_by", "signed_at", "frozen_result_sha256"):
        _require(bool(audit.get(field)), f"audit/{field}: required", errors)

    provenance = _object(bundle.get("provenance"), "provenance", errors)
    for field in (
        "result_bundle_sha256", "grader_policy_sha256", "preregistration_sha256",
        "harness_config_sha256", "run_manifest_sha256", "data_snapshot_sha256",
    ):
        _require(field in provenance, f"provenance/{field}: required", errors)

    coverage = _object(bundle.get("run_coverage"), "run_coverage", errors)
    expected = coverage.get("expected_rows")
    observed = coverage.get("observed_rows")
    _require(isinstance(expected, int) and not isinstance(expected, bool) and expected > 0, "run_coverage/expected_rows: positive integer required", errors)
    _require(isinstance(observed, int) and not isinstance(observed, bool) and observed >= 0, "run_coverage/observed_rows: non-negative integer required", errors)
    _require(coverage.get("state") in {"complete", "partial"}, "run_coverage/state: complete or partial required", errors)
    counts = _object(coverage.get("state_counts"), "run_coverage/state_counts", errors)
    _require(set(counts) == RUN_STATES, "run_coverage/state_counts must explicitly contain succeeded, failed, blocked, excluded, and missing", errors)
    _require(all(isinstance(counts.get(state), int) and not isinstance(counts.get(state), bool) and counts.get(state) >= 0 for state in RUN_STATES), "run_coverage/state_counts values must be non-negative integers", errors)

    records = _array(bundle.get("run_records"), "run_records", errors)
    record_ids: set[str] = set()
    actual_counts: Counter[str] = Counter()
    for index, record in enumerate(records):
        row = _object(record, f"run_records/{index}", errors)
        run_id = row.get("run_id")
        _require(isinstance(run_id, str) and bool(run_id), f"run_records/{index}/run_id: required", errors)
        _require(run_id not in record_ids, f"run_records/{index}: duplicate run_id", errors)
        record_ids.add(str(run_id))
        state = row.get("state")
        _require(state in RUN_STATES, f"run_records/{index}/state: invalid", errors)
        if state in RUN_STATES:
            actual_counts[state] += 1
        for field in ("family_id", "variant_id", "blind_model_id", "immutable_model_id", "trace_sha256"):
            _require(bool(row.get(field)), f"run_records/{index}/{field}: required", errors)
        if state in {"failed", "blocked", "missing"}:
            evidence = row.get("failure_evidence")
            _require(isinstance(evidence, dict) and bool(evidence.get("code")) and bool(evidence.get("evidence_ref")), f"run_records/{index}: failed/blocked/missing requires failure_evidence", errors)
    _require(observed == len(records), "run_coverage/observed_rows must equal run_records length", errors)
    _require(
        all(counts.get(state) == actual_counts[state] for state in RUN_STATES - {"missing"}),
        "run_coverage/state_counts does not match run_records; failures may have been omitted",
        errors,
    )
    if isinstance(expected, int):
        _require(sum(counts.get(state, 0) for state in RUN_STATES) == expected, "state_counts must account for every expected row, including missing and blocked", errors)
        _require(counts.get("missing") == expected - len(records), "missing count must equal expected rows minus explicit run records", errors)
    complete = coverage.get("state") == "complete"
    _require(complete == (observed == expected and counts.get("missing") == 0 and counts.get("blocked") == 0), "complete/partial state contradicts explicit matrix coverage", errors)

    failures = _array(bundle.get("failures"), "failures", errors)
    failure_ids = {item.get("run_id") for item in failures if isinstance(item, dict)}
    required_failure_ids = {row.get("run_id") for row in records if isinstance(row, dict) and row.get("state") in {"failed", "blocked", "missing"}}
    ledger_run_ids = {run_id for run_id in failure_ids if isinstance(run_id, str) and not run_id.startswith("missing://")}
    _require(ledger_run_ids == required_failure_ids, "failures ledger must include every failed and blocked run exactly", errors)
    missing_ledgers = [item for item in failures if isinstance(item, dict) and item.get("state") == "missing"]
    _require((counts.get("missing") == 0 and not missing_ledgers) or (counts.get("missing", 0) > 0 and len(missing_ledgers) == 1 and missing_ledgers[0].get("count") == counts.get("missing")), "missing rows require one explicit missing failure ledger with the exact count", errors)

    ranking = _object(bundle.get("ranking"), "ranking", errors)
    _require(ranking.get("track_weights") == spec["main_ranking"]["track_weights"], "main ranking weights must remain exactly 50/50", errors)
    _require(ranking.get("weight_override") is False, "demonstration or report weight override is forbidden", errors)
    _require(ranking.get("included_tier") == "Gold", "main ranking must be Gold only", errors)
    _require(ranking.get("silver_in_main_ranking") is False, "Gold/Silver mixed main ranking is forbidden", errors)
    entries = _array(ranking.get("entries"), "ranking/entries", errors)
    for index, entry in enumerate(entries):
        row = _object(entry, f"ranking/entries/{index}", errors)
        _require(row.get("source_tier") == "Gold", f"ranking/entries/{index}: Silver may appear only in diagnostic appendix", errors)
        _require(row.get("track_weights") == spec["main_ranking"]["track_weights"], f"ranking/entries/{index}: track weights changed", errors)
    eligible = ranking.get("published") is True
    _require(not eligible or complete, "main ranking must be withheld for partial or blocked coverage", errors)
    _require(not eligible or audit.get("status") == "signed", "main ranking requires signed audit", errors)
    _require(eligible or not entries, "withheld ranking must not contain ranked entries", errors)
    if not eligible:
        _require(bool(ranking.get("withheld_reason")), "withheld ranking requires an explicit reason", errors)

    model_reports = _array(bundle.get("model_reports"), "model_reports", errors)
    for index, report in enumerate(model_reports):
        row = _object(report, f"model_reports/{index}", errors)
        for field in ("blind_model_id", "immutable_model_id", "capability", "reliability", "safety", "cost", "latency", "uncertainty"):
            _require(field in row, f"model_reports/{index}/{field}: required", errors)

    limitations = _array(bundle.get("limitations"), "limitations", errors)
    if not complete:
        _require(any(isinstance(item, dict) and item.get("code") == "INCOMPLETE_MATRIX" for item in limitations), "partial coverage requires INCOMPLETE_MATRIX limitation; missing/blocked cannot be treated as zero error", errors)

    demos = _object(bundle.get("demonstrations"), "demonstrations", errors)
    _require(demos.get("illustrative_only") is True, "demonstrations must be explicitly illustrative", errors)
    _require(demos.get("affects_ranking") is False, "demonstrations must not affect ranking", errors)
    _require(demos.get("selection_weight_override") is False, "demonstration reweighting is forbidden", errors)
    cases = _array(demos.get("cases"), "demonstrations/cases", errors)
    _require(spec["demo"]["minimum_cases"] <= len(cases) <= spec["demo"]["maximum_cases"], "demonstrations must contain 6 to 8 cases", errors)
    selected_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    _require(len(selected_ids) == len(set(selected_ids)), "demonstration case ids must be unique", errors)
    selection = _object(demos.get("selection"), "demonstrations/selection", errors)
    _require(selection.get("decided_before_identity_unblinding") is True, "demonstration selection must precede identity unblinding", errors)
    _require(selection.get("selected_case_ids") == selected_ids, "selection record must preserve rendered case order and ids", errors)
    _require(bool(selection.get("selection_commitment_sha256")), "selection commitment hash required", errors)
    unblinding = _object(demos.get("unblinding"), "demonstrations/unblinding", errors)
    _require(bool(unblinding.get("revealed_at")) and bool(unblinding.get("custodian")), "unblinding timestamp and custodian required", errors)
    for index, case in enumerate(cases):
        item = _object(case, f"demonstrations/cases/{index}", errors)
        _require(item.get("illustrative_only") is True and item.get("affects_ranking") is False, f"demonstrations/cases/{index}: audit flags must isolate demo from ranking", errors)
        _require(item.get("selection_reason") in {"typical_difference", "failure_mode", "uncertainty_calibration", "cost_latency_tradeoff"}, f"demonstrations/cases/{index}: unregistered selection_reason", errors)
        outcomes = _array(item.get("outcomes"), f"demonstrations/cases/{index}/outcomes", errors)
        _require(len(outcomes) == len(model_reports), f"demonstrations/cases/{index}: all candidate outcomes required", errors)
        for outcome_index, outcome in enumerate(outcomes):
            row = _object(outcome, f"demonstrations/cases/{index}/outcomes/{outcome_index}", errors)
            for field in ("blind_model_id", "immutable_model_id", "final_answer", "tool_trace_ref", "evidence_chain_refs", "environment_state_ref", "failure_step", "cost_usd", "latency_ms", "uncertainty"):
                _require(field in row, f"demonstrations/cases/{index}/outcomes/{outcome_index}/{field}: required", errors)

    reproduction = _object(bundle.get("reproduction"), "reproduction", errors)
    _require(isinstance(reproduction.get("steps"), list) and bool(reproduction.get("steps")), "reproduction/steps: required", errors)
    _require(isinstance(reproduction.get("artifacts"), list) and bool(reproduction.get("artifacts")), "reproduction/artifacts: required", errors)
    _hashes(bundle, "$", errors)
    if errors:
        raise ReportContractError(errors)
    return {"valid": True, "coverage": coverage.get("state"), "runs": len(records), "demonstrations": len(cases), "ranking_published": eligible}


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    output.extend("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows)
    return output


def render_markdown(bundle: Mapping[str, Any]) -> str:
    validate_report(bundle)
    identity, coverage, ranking = bundle["report_identity"], bundle["run_coverage"], bundle["ranking"]
    lines = [
        "# Financial Agentic Index 报告", "",
        f"报告 `{identity['report_id']}`；框架 `{identity['framework_version']}`；数据快照 `{identity['data_snapshot_id']}`；评测日期 {identity['evaluation_date']}。", "",
        "## 覆盖与有效性", "",
        f"运行状态：**{coverage['state']}**。预期 {coverage['expected_rows']}，已记录 {coverage['observed_rows']}；失败、阻塞和缺失均显式保留。", "",
        "## 综合榜", "",
    ]
    if ranking["published"]:
        lines += _md_table(["名次", "模型", "FAI", "Gold"], [[x["rank"], x["immutable_model_id"], x["financial_agentic_index"], x["source_tier"]] for x in ranking["entries"]])
    else:
        lines += [f"**未发布：** {ranking['withheld_reason']}"]
    lines += ["", "## 分项、可靠性、安全、成本、延迟与不确定性", ""]
    lines += _md_table(
        ["模型", "能力", "可靠性", "安全", "成本 USD", "延迟 ms", "不确定性"],
        [[x["immutable_model_id"], x["capability"], x["reliability"], x["safety"], x["cost"], x["latency"], x["uncertainty"]] for x in bundle["model_reports"]],
    )
    lines += ["", "## 失败与限制", ""]
    if bundle["failures"]:
        lines += [f"- `{x['run_id']}`：{x['state']} / {x['code']}（{x['evidence_ref']}）" for x in bundle["failures"]]
    else:
        lines += ["- 未记录失败、阻塞或缺失运行。"]
    lines += [f"- 限制 `{x['code']}`：{x['statement']}" for x in bundle["limitations"]]
    lines += ["", "## 说明性并排案例（不影响综合分）", ""]
    for case in bundle["demonstrations"]["cases"]:
        lines += [f"### {case['case_id']} — {case['title']}", "", f"选择理由：`{case['selection_reason']}`；仅作说明，不参与排名。", ""]
        lines += _md_table(
            ["模型", "最终答案", "工具轨迹", "证据链", "环境状态", "失败步骤", "成本/延迟", "不确定性"],
            [[o["immutable_model_id"], o["final_answer"], o["tool_trace_ref"], ", ".join(o["evidence_chain_refs"]), o["environment_state_ref"], o["failure_step"] or "无", f"{o['cost_usd']} / {o['latency_ms']}", o["uncertainty"]] for o in case["outcomes"]],
        )
        lines.append("")
    lines += ["## 复现与 provenance", "", *[f"{index}. {step}" for index, step in enumerate(bundle["reproduction"]["steps"], 1)], "", f"机器可读结果 SHA-256：`{bundle['provenance']['result_bundle_sha256']}`。", ""]
    return "\n".join(lines)


def render_html(bundle: Mapping[str, Any]) -> str:
    validate_report(bundle)
    esc = lambda value: html.escape(str(value), quote=True)
    identity, coverage, ranking = bundle["report_identity"], bundle["run_coverage"], bundle["ranking"]
    def table(caption: str, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
        head = "".join(f'<th scope="col">{esc(x)}</th>' for x in headers)
        body = "".join("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in row) + "</tr>" for row in rows)
        return f'<table><caption>{esc(caption)}</caption><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
    rank_html = table("Gold 主榜", ["名次", "模型", "FAI", "层级"], [[x["rank"], x["immutable_model_id"], x["financial_agentic_index"], x["source_tier"]] for x in ranking["entries"]]) if ranking["published"] else f'<p role="status"><strong>未发布：</strong> {esc(ranking["withheld_reason"])}</p>'
    model_html = table("模型分项指标", ["模型", "能力", "可靠性", "安全", "成本 USD", "延迟 ms", "不确定性"], [[x["immutable_model_id"], x["capability"], x["reliability"], x["safety"], x["cost"], x["latency"], x["uncertainty"]] for x in bundle["model_reports"]])
    failure_html = "".join(f'<li><code>{esc(x["run_id"])}</code>：{esc(x["state"])} / {esc(x["code"])}（{esc(x["evidence_ref"])})</li>' for x in bundle["failures"]) or "<li>未记录失败、阻塞或缺失运行。</li>"
    limitation_html = "".join(f'<li><code>{esc(x["code"])}</code>：{esc(x["statement"])}</li>' for x in bundle["limitations"])
    demo_html = []
    for case in bundle["demonstrations"]["cases"]:
        rows = [[o["immutable_model_id"], o["final_answer"], o["tool_trace_ref"], ", ".join(o["evidence_chain_refs"]), o["environment_state_ref"], o["failure_step"] or "无", f"{o['cost_usd']} / {o['latency_ms']}", o["uncertainty"]] for o in case["outcomes"]]
        demo_html.append(f'<section aria-labelledby="demo-{esc(case["case_id"])}"><h3 id="demo-{esc(case["case_id"])}">{esc(case["case_id"])} — {esc(case["title"])}</h3><p>选择理由：{esc(case["selection_reason"])}；仅作说明，不参与排名。</p>{table("候选模型并排回放", ["模型", "最终答案", "工具轨迹", "证据链", "环境状态", "失败步骤", "成本/延迟", "不确定性"], rows)}</section>')
    steps = "".join(f"<li>{esc(step)}</li>" for step in bundle["reproduction"]["steps"])
    return "<!doctype html>\n" + f'''<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Financial Agentic Index 报告</title><style>body{{font:16px/1.55 system-ui,sans-serif;max-width:1200px;margin:auto;padding:1rem}}.skip{{position:absolute;left:-9999px}}.skip:focus{{left:1rem;background:#fff;padding:.5rem}}table{{border-collapse:collapse;width:100%;display:block;overflow-x:auto;margin:1rem 0}}caption{{font-weight:700;text-align:left}}th,td{{border:1px solid #777;padding:.5rem;vertical-align:top}}code{{overflow-wrap:anywhere}}</style></head><body><a class="skip" href="#main">跳到主要内容</a><header><h1>Financial Agentic Index 报告</h1><p>报告 <code>{esc(identity['report_id'])}</code>；框架 <code>{esc(identity['framework_version'])}</code>；数据快照 <code>{esc(identity['data_snapshot_id'])}</code>；评测日期 {esc(identity['evaluation_date'])}。</p></header><main id="main"><section aria-labelledby="coverage"><h2 id="coverage">覆盖与有效性</h2><p>运行状态：<strong>{esc(coverage['state'])}</strong>。预期 {esc(coverage['expected_rows'])}，已记录 {esc(coverage['observed_rows'])}；失败、阻塞和缺失均显式保留。</p></section><section aria-labelledby="ranking"><h2 id="ranking">综合榜</h2>{rank_html}</section><section aria-labelledby="metrics"><h2 id="metrics">分项、可靠性、安全、成本、延迟与不确定性</h2>{model_html}</section><section aria-labelledby="failures"><h2 id="failures">失败与限制</h2><ul>{failure_html}{limitation_html}</ul></section><section aria-labelledby="demos"><h2 id="demos">说明性并排案例（不影响综合分）</h2>{''.join(demo_html)}</section><section aria-labelledby="repro"><h2 id="repro">复现与 provenance</h2><ol>{steps}</ol><p>机器可读结果 SHA-256：<code>{esc(bundle['provenance']['result_bundle_sha256'])}</code>。</p></section></main></body></html>\n'''


def verify_freeze() -> dict[str, Any]:
    manifest = load_json(FREEZE_PATH)
    errors: list[str] = []
    commitments: list[str] = []
    for item in manifest.get("files", []):
        path = ROOT / item["path"]
        actual = file_sha256(path) if path.is_file() else None
        _require(actual == item["sha256"], f"frozen file hash mismatch: {item['path']}", errors)
        commitments.append(f"{item['path']}\0{item['sha256']}\n")
    aggregate = hashlib.sha256("".join(commitments).encode("utf-8")).hexdigest()
    _require(aggregate == manifest.get("contract_bundle_sha256"), "report contract bundle commitment mismatch", errors)
    if errors:
        raise ReportContractError(errors)
    return {"files": len(commitments), "contract_bundle_sha256": aggregate}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("bundle")
    render = commands.add_parser("render")
    render.add_argument("bundle")
    render.add_argument("--markdown", required=True)
    render.add_argument("--html", required=True)
    commands.add_parser("verify-freeze")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-freeze":
            result = verify_freeze()
        else:
            bundle = load_json(args.bundle)
            result = validate_report(bundle)
            if args.command == "render":
                pathlib.Path(args.markdown).write_text(render_markdown(bundle), encoding="utf-8")
                pathlib.Path(args.html).write_text(render_html(bundle), encoding="utf-8")
                result.update({"markdown": args.markdown, "html": args.html})
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, ReportContractError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
