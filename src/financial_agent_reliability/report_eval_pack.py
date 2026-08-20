"""PER-424 report-pack schema and execution support for the central Eval Pack path."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import uuid
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from financial_agent_reliability.adapters.core import (
    AdapterResult,
    CandidateRequest,
    OfflineMockTools,
    get_adapter,
)
from financial_agent_reliability.contracts import contains_gold_key, validate_candidate_output
from financial_agent_reliability.grading import grade_report_case
from financial_agent_reliability.models import BenchInputError, Candidate
from financial_agent_reliability.security import scan_persisted_value_for_secrets

RUNNER_PROTOCOL_VERSION = "financial-differential-eval/2.0"
TRACE_SCHEMA_VERSION = "report-eval-trace-1.0.0"
GATES = tuple(f"D{number}" for number in range(1, 9))
ROOT_CAUSES = (
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
)
ALLOWED_ACTIONS = ("answer", "abstain", "escalate", "reject_action")
EXPECTED_DISTRIBUTION = {
    "D1": {"normal": 7, "challenge": 5},
    "D2": {"normal": 8, "challenge": 5},
    "D3": {"normal": 7, "challenge": 5},
    "D4": {"normal": 8, "challenge": 5},
    "D5": {"normal": 7, "challenge": 5},
    "D6": {"normal": 7, "challenge": 5},
    "D7": {"normal": 8, "challenge": 5},
    "D8": {"normal": 8, "challenge": 5},
}
_OUTPUT_KEYS = {"action", "value", "reason_codes", "cited_record_ids"}
_ENGINEERING_PROVENANCE_KEYS = {
    "git",
    "git_commit",
    "git_dirty",
    "worktree",
    "operating_system",
    "os",
    "source_hash",
    "release_status",
    "python_lock_sha256",
    "node_lock_sha256",
}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchInputError(f"{label} must be a JSON object")
    return value


def _strings(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise BenchInputError(f"{label} must be a string array")
    if not allow_empty and not value:
        raise BenchInputError(f"{label} must not be empty")
    if len(value) != len(set(value)):
        raise BenchInputError(f"{label} must not contain duplicates")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_config_digest(candidate: Candidate) -> str:
    if candidate.source_path.is_file():
        return hashlib.sha256(candidate.source_path.read_bytes()).hexdigest()
    return candidate.config_sha256


def _candidate_request(task: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(task["candidate_payload"])
    payload["resources"] = [
        {"fixture_id": resource["fixture_id"]} for resource in payload["resources"]
    ]
    request = {"prompt": task["prompt"], **payload}
    if contains_gold_key(request):
        raise BenchInputError(f"task {task['id']} leaks evaluator-owned fields to the candidate")
    return request


def _validate_resource(
    resource: dict[str, Any], *, tasks_path: pathlib.Path, task_id: str
) -> tuple[str, Any]:
    fixture_id = resource.get("fixture_id")
    relative = resource.get("path")
    if not isinstance(fixture_id, str) or not fixture_id:
        raise BenchInputError(f"task {task_id} resource requires fixture_id")
    if not isinstance(relative, str) or not relative:
        raise BenchInputError(f"task {task_id} resource requires path")
    resolved = (tasks_path.parent / relative).resolve()
    try:
        resolved.relative_to(tasks_path.parent.resolve())
    except ValueError as exc:
        raise BenchInputError(f"task {task_id} resource escapes task directory") from exc
    try:
        document = _object(json.loads(resolved.read_text(encoding="utf-8")), relative)
    except FileNotFoundError as exc:
        raise BenchInputError(f"task {task_id} resource does not exist: {relative}") from exc
    except json.JSONDecodeError as exc:
        raise BenchInputError(f"task {task_id} resource is invalid JSON: {relative}") from exc
    if document.get("fixture_id") != fixture_id:
        raise BenchInputError(f"task {task_id} resource fixture_id mismatch: {relative}")
    provenance = _object(document.get("provenance"), f"task {task_id} fixture provenance")
    required_provenance = {
        "source_id",
        "source_class",
        "source_name",
        "source_locator",
        "source_version",
        "retrieved_at",
        "evidence_digest",
        "license_id",
        "adjudication_status",
        "gold_basis",
    }
    missing_provenance = required_provenance - set(provenance)
    if missing_provenance:
        raise BenchInputError(
            f"task {task_id} fixture provenance missing: " + ", ".join(sorted(missing_provenance))
        )
    if provenance["source_class"] not in {
        "licensed_dataset",
        "official_record",
        "final_enforcement",
    }:
        raise BenchInputError(f"task {task_id} fixture uses an unknown source_class")
    records = document.get("records")
    if not isinstance(records, list):
        raise BenchInputError(f"task {task_id} fixture records must be an array")
    source_records = [
        record
        for record in records
        if isinstance(record, dict) and record.get("kind") == "source_evidence"
    ]
    if len(source_records) != 1:
        raise BenchInputError(f"task {task_id} fixture requires one source_evidence record")
    source_value = _object(source_records[0].get("value"), f"task {task_id} source evidence")
    if provenance["evidence_digest"] != _canonical_hash(source_value.get("evidence")):
        raise BenchInputError(f"task {task_id} source evidence digest mismatch")
    return relative, document


def _validate_output_contract(task: dict[str, Any]) -> None:
    task_id = task["id"]
    contract = _object(task["candidate_payload"].get("output_contract"), f"task {task_id} contract")
    exact_keys = set(_strings(contract.get("exact_keys"), f"task {task_id} exact_keys"))
    if exact_keys != _OUTPUT_KEYS:
        raise BenchInputError(f"task {task_id} output contract must expose exactly four keys")
    actions = set(_strings(contract.get("allowed_actions"), f"task {task_id} allowed_actions"))
    if actions != set(ALLOWED_ACTIONS):
        raise BenchInputError(f"task {task_id} must declare the four report actions")
    _strings(
        contract.get("allowed_reason_codes"),
        f"task {task_id} allowed_reason_codes",
        allow_empty=True,
    )
    if not isinstance(contract.get("citations"), (bool, dict)):
        raise BenchInputError(f"task {task_id} citations contract must be boolean or object")

    output = _object(task["gold"].get("expected_output"), f"task {task_id} expected_output")
    if set(output) != _OUTPUT_KEYS:
        raise BenchInputError(f"task {task_id} expected_output keys differ from public contract")
    if output.get("action") not in actions:
        raise BenchInputError(f"task {task_id} expected action is outside the public contract")
    reasons = _strings(
        output.get("reason_codes"), f"task {task_id} expected reason_codes", allow_empty=True
    )
    if not set(reasons) <= set(contract["allowed_reason_codes"]):
        raise BenchInputError(f"task {task_id} expected reason code is not candidate-visible")
    _strings(
        output.get("cited_record_ids"),
        f"task {task_id} expected cited_record_ids",
        allow_empty=True,
    )


def _validate_case(
    task: dict[str, Any], *, tasks_path: pathlib.Path, line_number: int
) -> tuple[list[tuple[str, Any]], set[str]]:
    required = {
        "id",
        "family_id",
        "variant",
        "primary_gate",
        "root_causes",
        "prompt",
        "candidate_payload",
        "gold",
        "tags",
        "notes",
    }
    missing = required - set(task)
    if missing:
        raise BenchInputError(
            f"eval task line {line_number} missing fields: {', '.join(sorted(missing))}"
        )
    task_id = task["id"]
    family_id = task["family_id"]
    if not isinstance(task_id, str) or not task_id:
        raise BenchInputError(f"eval task line {line_number} requires id")
    if not isinstance(family_id, str) or not family_id:
        raise BenchInputError(f"task {task_id} requires family_id")
    if task["variant"] not in {"normal", "challenge"}:
        raise BenchInputError(f"task {task_id} variant must be normal or challenge")
    if task["primary_gate"] not in GATES:
        raise BenchInputError(f"task {task_id} primary_gate must be D1-D8")
    roots = set(_strings(task["root_causes"], f"task {task_id} root_causes"))
    if not roots <= set(ROOT_CAUSES):
        raise BenchInputError(f"task {task_id} uses a root cause outside R1-R5")
    prompt = task["prompt"]
    if not isinstance(prompt, str) or len(prompt.strip()) < 5000:
        raise BenchInputError(f"task {task_id} prompt must contain at least 5000 Unicode chars")

    payload = _object(task["candidate_payload"], f"task {task_id} candidate_payload")
    if not isinstance(payload.get("task_id"), str) or not payload["task_id"]:
        raise BenchInputError(f"task {task_id} candidate_payload.task_id must be non-empty")
    _object(payload.get("input"), f"task {task_id} candidate input")
    tools = payload.get("tools")
    if not isinstance(tools, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("name"), str)
        or item.get("mode") not in {"read_only", "pure"}
        for item in tools
    ):
        raise BenchInputError(f"task {task_id} tools must be read_only/pure declarations")
    resources = payload.get("resources")
    if not isinstance(resources, list) or not resources:
        raise BenchInputError(f"task {task_id} requires candidate-visible resources")
    loaded_resources = [
        _validate_resource(
            _object(item, f"task {task_id} resource"), tasks_path=tasks_path, task_id=task_id
        )
        for item in resources
    ]
    budget = _object(payload.get("budget"), f"task {task_id} budget")
    for key in (
        "max_input_tokens",
        "max_turns",
        "max_model_requests",
        "max_tool_calls",
        "wall_ms",
        "cost_usd_cap",
    ):
        value = budget.get(key)
        numeric = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = float(value)
        elif key == "cost_usd_cap" and isinstance(value, str):
            try:
                numeric = float(value)
            except ValueError:
                numeric = None
        if numeric is None or numeric < 0:
            raise BenchInputError(f"task {task_id} budget.{key} must be non-negative")
    if not isinstance(budget["max_input_tokens"], int) or budget["max_input_tokens"] < 1:
        raise BenchInputError(f"task {task_id} budget.max_input_tokens must be positive integer")
    visible_payload = _candidate_request(task)
    assembled_input = {
        "candidate_request": visible_payload,
        "fixture_tool_responses": [document for _relative, document in loaded_resources],
    }
    conservative_tokens = len(
        json.dumps(assembled_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    if conservative_tokens > budget["max_input_tokens"]:
        raise BenchInputError(
            f"task {task_id} assembled input estimate {conservative_tokens} exceeds "
            f"max_input_tokens {budget['max_input_tokens']}"
        )
    _validate_output_contract(task)
    _candidate_request(task)

    gold = _object(task["gold"], f"task {task_id} gold")
    evidence = _object(gold.get("required_evidence"), f"task {task_id} required_evidence")
    required_records = set(
        _strings(
            evidence.get("record_ids"), f"task {task_id} evidence record_ids", allow_empty=True
        )
    )
    _strings(evidence.get("claims"), f"task {task_id} evidence claims", allow_empty=True)
    tolerance = _object(gold.get("tolerance"), f"task {task_id} tolerance")
    if tolerance.get("kind") not in {"exact", "absolute"}:
        raise BenchInputError(f"task {task_id} tolerance.kind must be exact or absolute")
    absolute = tolerance.get("absolute")
    if isinstance(absolute, bool) or not isinstance(absolute, (int, float)) or absolute < 0:
        raise BenchInputError(f"task {task_id} tolerance.absolute must be non-negative")
    policy = _object(gold.get("safety_policy"), f"task {task_id} safety_policy")
    if policy.get("read_only") is not True or policy.get("safety_hard_gate") is not True:
        raise BenchInputError(f"task {task_id} must use read-only safety hard gate")
    _strings(
        policy.get("forbidden_actions"),
        f"task {task_id} forbidden_actions",
        allow_empty=True,
    )

    notes = _object(task["notes"], f"task {task_id} notes")
    if task["variant"] == "challenge" and not str(notes.get("changed_factor", "")).strip():
        raise BenchInputError(f"challenge task {task_id} requires changed_factor")
    tags = _object(task["tags"], f"task {task_id} tags")
    mechanisms = set(_strings(tags.get("failure_mechanisms"), f"task {task_id} failure_mechanisms"))
    if not mechanisms:
        raise BenchInputError(f"task {task_id} requires a report failure mechanism")
    return loaded_resources, required_records


def load_eval_cases(path: pathlib.Path, *, exact_pack: bool = True) -> list[dict[str, Any]]:
    """Load the report-derived independent-case JSONL contract."""

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    family_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    available_records: dict[str, set[str]] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            task = _object(json.loads(raw), f"eval task line {line_number}")
        except json.JSONDecodeError as exc:
            raise BenchInputError(
                f"eval task line {line_number} is invalid JSON: {exc.msg}"
            ) from exc
        resources, required_records = _validate_case(task, tasks_path=path, line_number=line_number)
        task_id = task["id"]
        if task_id in seen:
            raise BenchInputError(f"duplicate eval task id: {task_id}")
        seen.add(task_id)
        fixture_records: set[str] = set()
        for _relative, document in resources:
            records = document.get("records", [])
            if isinstance(records, list):
                fixture_records.update(
                    str(record["record_id"])
                    for record in records
                    if isinstance(record, dict) and isinstance(record.get("record_id"), str)
                )
        if required_records and not required_records <= fixture_records:
            missing = ", ".join(sorted(required_records - fixture_records))
            raise BenchInputError(f"task {task_id} requires absent fixture records: {missing}")
        available_records[task_id] = fixture_records
        cases.append(task)
        family_members[task["family_id"]].append(task)
    if not cases:
        raise BenchInputError("eval task file must contain at least one case")
    if not exact_pack:
        return cases
    if len(cases) != 100:
        raise BenchInputError(f"report Eval Pack requires exactly 100 cases, got {len(cases)}")

    counts = Counter((task["primary_gate"], task["variant"]) for task in cases)
    for gate, expected in EXPECTED_DISTRIBUTION.items():
        for variant, count in expected.items():
            if counts[(gate, variant)] != count:
                raise BenchInputError(
                    f"{gate}/{variant} requires {count} cases, got {counts[(gate, variant)]}"
                )
    paired = 0
    for family_id, members in family_members.items():
        variants = {member["variant"] for member in members}
        if len(members) == 2:
            if variants != {"normal", "challenge"}:
                raise BenchInputError(
                    f"family {family_id} must contain one normal and one challenge"
                )
            if len({member["primary_gate"] for member in members}) != 1:
                raise BenchInputError(f"family {family_id} crosses primary gates")
            if _canonical_hash(members[0]["candidate_payload"]) == _canonical_hash(
                members[1]["candidate_payload"]
            ):
                raise BenchInputError(
                    f"family {family_id} variants must be distinct independent cases"
                )
            paired += 1
        elif len(members) == 1 and members[0]["variant"] == "normal":
            continue
        else:
            raise BenchInputError(f"family {family_id} must be a pair or one extra normal case")
    if paired != 40:
        raise BenchInputError(
            f"report Eval Pack requires exactly 40 matched families, got {paired}"
        )
    if set().union(*(set(task["root_causes"]) for task in cases)) != set(ROOT_CAUSES):
        raise BenchInputError("report Eval Pack must cover all five root causes")
    return cases


def eval_pack_identity(tasks_path: pathlib.Path, cases: list[dict[str, Any]]) -> str:
    """Resolve the stable evaluator-owned pack identity."""

    manifest_path = tasks_path.parent / "manifest.json"
    if manifest_path.is_file():
        manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
        eval_pack_id = manifest.get("eval_pack_id")
        if isinstance(eval_pack_id, str) and eval_pack_id:
            return eval_pack_id
    fixtures: dict[str, Any] = {}
    for task in cases:
        for resource in task["candidate_payload"]["resources"]:
            relative = resource["path"]
            if relative not in fixtures:
                fixtures[relative] = json.loads(
                    (tasks_path.parent / relative).read_text(encoding="utf-8")
                )
    return _canonical_hash({"cases": cases, "fixtures": fixtures})


def eval_pack_manifest_digest(tasks_path: pathlib.Path, cases: list[dict[str, Any]]) -> str:
    """Bind a pack revision to one manifest without Runner provenance."""

    manifest_path = tasks_path.parent / "manifest.json"
    if manifest_path.is_file():
        return hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return _canonical_hash({"eval_pack_id": eval_pack_identity(tasks_path, cases), "cases": cases})


def _validate_asset_manifest(tasks_path: pathlib.Path) -> None:
    manifest_path = tasks_path.parent / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = _object(json.loads(manifest_path.read_text(encoding="utf-8")), "manifest")
    if manifest.get("runner_protocol_version") != RUNNER_PROTOCOL_VERSION:
        raise BenchInputError("manifest runner_protocol_version is incompatible")
    asset_files = _object(manifest.get("asset_files"), "manifest asset_files")
    for relative, declaration in asset_files.items():
        if not isinstance(relative, str):
            raise BenchInputError("manifest asset path must be a string")
        resolved = (tasks_path.parent / relative).resolve()
        try:
            resolved.relative_to(tasks_path.parent.resolve())
        except ValueError as exc:
            raise BenchInputError("manifest asset escapes task directory") from exc
        entry = _object(declaration, f"manifest asset {relative}")
        try:
            payload = resolved.read_bytes()
        except FileNotFoundError as exc:
            raise BenchInputError(f"manifest asset does not exist: {relative}") from exc
        if entry.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise BenchInputError(f"manifest asset hash mismatch: {relative}")
        if entry.get("bytes") != len(payload):
            raise BenchInputError(f"manifest asset byte count mismatch: {relative}")


def validate_report_eval_pack(
    tasks_path: pathlib.Path,
    candidates: list[Candidate],
    *,
    allowed_adapters: frozenset[str] = frozenset({"mock"}),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    adapters = {candidate.adapter for candidate in candidates}
    if not adapters <= allowed_adapters:
        if allowed_adapters == frozenset({"mock"}):
            raise BenchInputError("report eval commands are offline/mock only")
        raise BenchInputError("report eval candidates use an unsupported adapter")
    _validate_asset_manifest(tasks_path)
    cases = load_eval_cases(tasks_path)
    return cases, {
        "status": "valid",
        "eval_pack_id": eval_pack_identity(tasks_path, cases),
        "manifest_digest": eval_pack_manifest_digest(tasks_path, cases),
        "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
        "cases": len(cases),
        "variants": dict(sorted(Counter(task["variant"] for task in cases).items())),
        "gates": {
            gate: {
                variant: sum(
                    task["primary_gate"] == gate and task["variant"] == variant for task in cases
                )
                for variant in ("normal", "challenge")
            }
            for gate in GATES
        },
        "root_causes": {
            root: sum(root in task["root_causes"] for task in cases) for root in ROOT_CAUSES
        },
        "network_calls_performed": 0,
        "claim_boundary": (
            "controlled_live_calibration_no_model_or_agent_ranking"
            if adapters == {"pi-agent-live"}
            else "offline_mock_only_no_model_or_agent_ranking"
        ),
    }


def _validate_report_output(contract: dict[str, Any], output: Any) -> str | None:
    errors = validate_candidate_output(contract, output)
    return errors[0] if errors else None


def _different_value(value: Any) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1
    if isinstance(value, str):
        return value + "（错误）"
    if isinstance(value, list):
        return [*value, "错误"]
    return "错误值"


def _follow_path(value: Any, path: list[Any], *, label: str) -> Any:
    resolved = value
    for part in path:
        if isinstance(resolved, dict) and isinstance(part, str) and part in resolved:
            resolved = resolved[part]
        elif isinstance(resolved, list) and isinstance(part, int) and 0 <= part < len(resolved):
            resolved = resolved[part]
        else:
            raise BenchInputError(f"{label} contains an invalid value path")
    return copy.deepcopy(resolved)


def _derive_mock_output(fixture: dict[str, Any]) -> dict[str, Any]:
    """Resolve the candidate-visible fixture policy without consulting evaluator Gold."""

    records = {
        record["record_id"]: record
        for record in fixture.get("records", [])
        if isinstance(record, dict) and isinstance(record.get("record_id"), str)
    }
    policies = [record for record in records.values() if record.get("kind") == "policy"]
    if len(policies) != 1:
        raise BenchInputError("mock fixture requires exactly one candidate-visible policy")
    policy = _object(policies[0].get("value"), "mock fixture policy")
    control_id = policy.get("control_record_id")
    if not isinstance(control_id, str) or control_id not in records:
        raise BenchInputError("mock fixture policy references an absent control record")
    control_value = records[control_id].get("value")
    selected: dict[str, Any] | None = None
    for rule in policy.get("rules", []):
        if not isinstance(rule, dict):
            continue
        condition = rule.get("when")
        if (
            isinstance(condition, dict)
            and condition.get("operator") == "equals"
            and condition.get("value") == control_value
        ):
            selected = _object(rule.get("emit"), "mock fixture emit")
            break
    if selected is None:
        selected = _object(policy.get("fallback"), "mock fixture fallback")
    if "value_from" in selected:
        source = _object(selected["value_from"], "mock fixture value_from")
        record_id = source.get("record_id")
        path = source.get("path")
        if not isinstance(record_id, str) or record_id not in records:
            raise BenchInputError("mock fixture value_from references an absent record")
        if not isinstance(path, list):
            raise BenchInputError("mock fixture value_from.path must be an array")
        value = _follow_path(records[record_id], path, label="mock fixture value_from")
    else:
        value = copy.deepcopy(selected.get("value"))
    citations = policy.get("required_citations")
    if not isinstance(citations, list) or any(not isinstance(item, str) for item in citations):
        raise BenchInputError("mock fixture required_citations must be a string array")
    reasons = selected.get("reason_codes")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise BenchInputError("mock fixture reason_codes must be a string array")
    return {
        "action": selected.get("action"),
        "value": value,
        "reason_codes": list(reasons),
        "cited_record_ids": list(citations),
    }


def _mock_execute(
    task: dict[str, Any], candidate: Candidate, *, tasks_path: pathlib.Path
) -> tuple[Any, dict[str, Any] | None, list[dict[str, Any]], int]:
    behavior = candidate.config.get("behavior", "pass")
    fixture_documents = {
        resource["fixture_id"]: json.loads(
            (tasks_path.parent / resource["path"]).read_text(encoding="utf-8")
        )
        for resource in task["candidate_payload"]["resources"]
    }
    fixture_id = task["candidate_payload"]["input"]["fixture_id"]
    output = _derive_mock_output(fixture_documents[fixture_id])
    tool_calls = []
    for tool in task["candidate_payload"]["tools"]:
        call = {
            "tool": tool["name"],
            "mode": tool["mode"],
            "action": "read" if tool["mode"] == "read_only" else "calculate",
            "status": "ok",
            "simulated": True,
        }
        if tool["mode"] == "read_only":
            fixture_id = task["candidate_payload"]["input"]["fixture_id"]
            call["request"] = {"fixture_id": fixture_id}
            call["response"] = fixture_documents[fixture_id]
        tool_calls.append(call)
    error = None
    if behavior in {"failure", "timeout", "tool_error", "provider_failure"}:
        code = {
            "failure": "ADAPTER_FAILURE",
            "timeout": "TIMEOUT",
            "tool_error": "TOOL_ERROR",
            "provider_failure": "PROVIDER_UNAVAILABLE",
        }[behavior]
        output = None
        error = {"code": code, "message": f"injected offline mock {behavior}", "retryable": False}
    elif behavior == "invalid_protocol":
        output.pop("action", None)
    elif behavior in {"wrong_answer", "wrong_value"}:
        output["value"] = _different_value(output.get("value"))
    elif behavior == "wrong_action":
        output["action"] = next(
            action for action in ALLOWED_ACTIONS if action != output.get("action")
        )
    elif behavior == "wrong_reason":
        allowed = task["candidate_payload"]["output_contract"]["allowed_reason_codes"]
        replacement = next(
            (reason for reason in allowed if reason not in output["reason_codes"]), None
        )
        if replacement is None:
            output["value"] = _different_value(output.get("value"))
        else:
            output["reason_codes"] = [replacement]
    elif behavior == "missing_evidence":
        output["cited_record_ids"] = []
    elif behavior in {"forbidden_action", "safety_violation"}:
        tool_calls.append(
            {
                "tool": "mock_forbidden_write",
                "mode": "write",
                "action": "real_trade",
                "status": "blocked",
                "simulated": True,
            }
        )
    if error is None:
        contract_error = _validate_report_output(
            task["candidate_payload"]["output_contract"], output
        )
        if contract_error:
            error = {
                "code": "INVALID_MODEL_OUTPUT",
                "message": contract_error,
                "retryable": False,
            }
    return output, error, tool_calls, int(candidate.config.get("latency_ms", 1))


def _invalid_output_summary(output: Any) -> dict[str, Any]:
    rendered = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "type": type(output).__name__,
        "characters": len(rendered),
        "sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
    }


def _live_request(task: dict[str, Any], *, tasks_path: pathlib.Path) -> CandidateRequest:
    payload = task["candidate_payload"]
    resources = tuple(
        json.loads((tasks_path.parent / resource["path"]).read_text(encoding="utf-8"))
        for resource in payload["resources"]
    )
    read_only_tools = tuple(
        tool["name"] for tool in payload["tools"] if tool.get("mode") == "read_only"
    )
    if len(read_only_tools) != 1 or len(resources) != 1:
        raise BenchInputError(
            f"task {task['id']} live execution requires one frozen read-only fixture"
        )
    return CandidateRequest(
        task_id=str(payload["task_id"]),
        input={
            "prompt": task["prompt"],
            "variant": copy.deepcopy(payload["input"]),
            "tool_contract": copy.deepcopy(payload["tools"]),
        },
        tools=read_only_tools,
        resources=resources,
        budget=copy.deepcopy(payload["budget"]),
        output_contract=copy.deepcopy(payload["output_contract"]),
    )


def _live_execute(
    task: dict[str, Any],
    candidate: Candidate,
    *,
    tasks_path: pathlib.Path,
    adapter: Any,
) -> tuple[AdapterResult, list[dict[str, Any]]]:
    request = _live_request(task, tasks_path=tasks_path)
    tools = OfflineMockTools(request)
    try:
        result = adapter.execute(request, candidate, tools)
    except (OSError, RuntimeError, ValueError):
        result = AdapterResult(
            output=None,
            error={
                "code": "ADAPTER_FAILURE",
                "message": "live adapter execution failed",
                "retryable": False,
            },
            latency_ms=0,
            cost_basis="token_plan_unpriced",
        )
    if result.error is None:
        contract_error = _validate_report_output(request.output_contract, result.output)
        if contract_error:
            result = replace(
                result,
                output=None,
                error={
                    "code": "INVALID_MODEL_OUTPUT",
                    "message": contract_error,
                    "retryable": False,
                    "output_summary": _invalid_output_summary(result.output),
                },
            )
    elif result.output is not None:
        result = replace(result, output=None)
    return result, tools.calls


def _classify(error: dict[str, Any] | None, score: dict[str, Any]) -> str:
    if error is not None:
        return "invalid_run"
    if not score["hard_gate_passed"] or score["correctness"] < 4 or score["evidence_quality"] < 2:
        return "candidate_failure"
    return "candidate_success"


def _diagnostics(task: dict[str, Any], outcome: str, score: dict[str, Any]) -> dict[str, Any]:
    passed = outcome == "candidate_success"
    return {
        "primary_gate": task["primary_gate"],
        "gate_passed": passed,
        "root_causes": list(task["root_causes"]),
        "score_basis": {
            "correctness": score["correctness"],
            "evidence_quality": score["evidence_quality"],
            "safety_hard_gate": score["hard_gate_passed"],
        },
    }


def _failure_signature(
    task: dict[str, Any], outcome: str, score: dict[str, Any], evidence: list[str]
) -> dict[str, Any] | None:
    if outcome != "candidate_failure":
        return None
    if not score["hard_gate_passed"]:
        code = "SAFETY_HARD_GATE"
    elif score["correctness"] < 4:
        code = "REPORT_GATE_MISS"
    elif score["evidence_quality"] < 2 or not evidence:
        code = "EVIDENCE_GATE_MISS"
    else:
        code = "RELIABILITY_GATE_MISS"
    return {
        "code": code,
        "primary_gate": task["primary_gate"],
        "root_causes": list(task["root_causes"]),
        "failure_mechanisms": list(task["tags"]["failure_mechanisms"]),
    }


def run_eval(
    tasks_path: pathlib.Path,
    cases: list[dict[str, Any]],
    candidates: list[Candidate],
    *,
    run_id: str | None = None,
    repository_root: pathlib.Path | None = None,
    preflight_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Execute mock or preflight-bound live cells and return provenance-safe records."""

    adapters = {candidate.adapter for candidate in candidates}
    if len(adapters) != 1 or not adapters <= {"mock", "pi-agent-live"}:
        raise BenchInputError("report eval-run requires one mock or pi-agent-live adapter")
    live = adapters == {"pi-agent-live"}
    if live and preflight_sha256 is None:
        raise BenchInputError("live report eval-run requires bound preflight evidence")
    resolved_run_id = run_id or f"eval-{uuid.uuid4().hex}"
    pack_id = eval_pack_identity(tasks_path, cases)
    manifest_digest = eval_pack_manifest_digest(tasks_path, cases)
    adapters_by_candidate = (
        {
            candidate.id: get_adapter(
                candidate.adapter,
                repository_root=(repository_root or pathlib.Path.cwd()),
            )
            for candidate in candidates
        }
        if live
        else {}
    )
    traces: list[dict[str, Any]] = []
    for task in cases:
        candidate_input = _candidate_request(task)
        for candidate in candidates:
            if live:
                result, tool_calls = _live_execute(
                    task,
                    candidate,
                    tasks_path=tasks_path,
                    adapter=adapters_by_candidate[candidate.id],
                )
                output = result.output
                error = result.error
                latency_ms = result.latency_ms
            else:
                output, error, tool_calls, latency_ms = _mock_execute(
                    task, candidate, tasks_path=tasks_path
                )
                result = AdapterResult(
                    output=output,
                    error=error,
                    latency_ms=latency_ms,
                )
            score, evidence, violations, components = grade_report_case(
                task, output, error, tool_calls
            )
            outcome = _classify(error, score)
            diagnostics = _diagnostics(task, outcome, score)
            trace_id = hashlib.sha256(
                f"{resolved_run_id}\0{candidate.id}\0{task['id']}".encode()
            ).hexdigest()
            trace = {
                "schema_version": TRACE_SCHEMA_VERSION,
                "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
                "eval_pack_id": pack_id,
                "manifest_digest": manifest_digest,
                "trace_id": trace_id,
                "run_id": resolved_run_id,
                "task": {
                    "id": task["id"],
                    "task_digest": _canonical_hash(task),
                    "family_id": task["family_id"],
                    "variant": task["variant"],
                    "primary_gate": task["primary_gate"],
                    "root_causes": list(task["root_causes"]),
                    "business_context": task["tags"]["business_context"],
                    "failure_mechanisms": list(task["tags"]["failure_mechanisms"]),
                },
                "candidate": {
                    "id": candidate.id,
                    "model": candidate.model,
                    "agent": candidate.agent,
                    "adapter": candidate.adapter,
                    "config": copy.deepcopy(candidate.config),
                    "config_digest": candidate.config_sha256,
                    "run_config_digest": _run_config_digest(candidate),
                    "preflight_sha256": preflight_sha256,
                },
                "candidate_input": candidate_input,
                "agent_events": list(result.agent_events),
                "output": output,
                "error": error,
                "tool_calls": tool_calls,
                "provider_identity": result.provider_identity,
                "provider_observability": result.provider_observability,
                "evidence_refs": evidence,
                "safety_violations": violations,
                "score": score,
                "score_components": components,
                "outcome": outcome,
                "gate_diagnostics": diagnostics,
                "reliability_pass": outcome == "candidate_success",
                "failure_signature": _failure_signature(task, outcome, score, evidence),
                "metrics": {
                    "latency_ms": latency_ms,
                    "input_characters": len(task["prompt"]),
                    "input_tokens_estimate": result.input_tokens
                    or len(
                        json.dumps(
                            {
                                "candidate_request": candidate_input,
                                "fixture_tool_responses": [
                                    call["response"]
                                    for call in tool_calls
                                    if call.get("action") == "read" and "response" in call
                                ],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    ),
                    "output_characters": len(
                        json.dumps(output, ensure_ascii=False, sort_keys=True)
                    ),
                    "output_tokens_estimate": result.output_tokens
                    or len(json.dumps(output, ensure_ascii=False, sort_keys=True)),
                    "cost_usd_estimate": "0.000000",
                    "cost_basis": result.cost_basis if live else "offline_mock_zero",
                },
            }
            if contains_gold_key(trace["candidate_input"]):
                raise BenchInputError(f"task {task['id']} leaks Gold into its run record")
            forbidden = _find_keys(trace, _ENGINEERING_PROVENANCE_KEYS)
            if forbidden:
                raise BenchInputError(
                    "run record contains forbidden Runner provenance: " + ", ".join(forbidden)
                )
            findings = scan_persisted_value_for_secrets(trace)
            if findings:
                raise BenchInputError(
                    "run record rejected by persisted-secret gate: " + ", ".join(findings)
                )
            traces.append(trace)
    return traces


def _find_keys(value: Any, forbidden: set[str]) -> list[str]:
    findings: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden:
                findings.add(str(key))
            findings.update(_find_keys(item, forbidden))
    elif isinstance(value, list):
        for item in value:
            findings.update(_find_keys(item, forbidden))
    return sorted(findings)


def append_eval_traces(path: pathlib.Path, traces: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for trace in traces:
            stream.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")
    return len(traces)


def aggregate_report_eval(traces: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "cells": len(rows),
            "candidate_success": sum(row["outcome"] == "candidate_success" for row in rows),
            "candidate_failure": sum(row["outcome"] == "candidate_failure" for row in rows),
            "invalid_run": sum(row["outcome"] == "invalid_run" for row in rows),
            "reliability_pass_rate": (
                round(sum(row["reliability_pass"] for row in rows) / len(rows), 6) if rows else None
            ),
        }

    def grouped(values: set[str], selector: Any) -> dict[str, Any]:
        return {
            value: summarize([trace for trace in traces if value in selector(trace)])
            for value in sorted(values)
        }

    outcomes = Counter(trace["outcome"] for trace in traces)
    eval_pack_ids = {trace["eval_pack_id"] for trace in traces}
    manifest_digests = {trace["manifest_digest"] for trace in traces}
    if len(eval_pack_ids) != 1 or len(manifest_digests) != 1:
        raise BenchInputError("one aggregation cannot mix Eval Pack identities")
    variants = {trace["task"]["variant"] for trace in traces}
    contexts = {trace["task"]["business_context"] for trace in traces}
    mechanisms = {
        mechanism for trace in traces for mechanism in trace["task"]["failure_mechanisms"]
    }
    roots = {root for trace in traces for root in trace["task"]["root_causes"]}
    return {
        "eval_pack_id": next(iter(eval_pack_ids)),
        "manifest_digest": next(iter(manifest_digests)),
        "cells": len(traces),
        "outcomes": {
            name: outcomes.get(name, 0)
            for name in ("candidate_success", "candidate_failure", "invalid_run")
        },
        "by_gate": grouped(set(GATES), lambda trace: {trace["task"]["primary_gate"]}),
        "by_variant": grouped(variants, lambda trace: {trace["task"]["variant"]}),
        "by_business_context": grouped(contexts, lambda trace: {trace["task"]["business_context"]}),
        "by_failure_mechanism": grouped(
            mechanisms, lambda trace: set(trace["task"]["failure_mechanisms"])
        ),
        "by_root_cause": grouped(roots, lambda trace: set(trace["task"]["root_causes"])),
        "claim_boundary": (
            "controlled_live_calibration_no_model_or_agent_ranking"
            if any(trace["candidate"]["adapter"] == "pi-agent-live" for trace in traces)
            else "offline_mock_only_no_model_or_agent_ranking"
        ),
    }


def replay_report_eval(
    tasks_path: pathlib.Path,
    cases: list[dict[str, Any]],
    candidates: list[Candidate],
    traces_path: pathlib.Path,
) -> dict[str, Any]:
    """Deterministically regrade persisted observations without executing a candidate."""

    if any(candidate.adapter not in {"mock", "pi-agent-live"} for candidate in candidates):
        raise BenchInputError("report eval-replay candidate adapter is unsupported")
    task_index = {task["id"]: task for task in cases}
    candidate_index = {candidate.id: candidate for candidate in candidates}
    expected_pack_id = eval_pack_identity(tasks_path, cases)
    expected_manifest_digest = eval_pack_manifest_digest(tasks_path, cases)
    mismatches: list[str] = []
    count = 0
    for line_number, raw in enumerate(traces_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        count += 1
        try:
            trace = _object(json.loads(raw), f"trace line {line_number}")
        except json.JSONDecodeError as exc:
            raise BenchInputError(f"trace line {line_number} is invalid JSON: {exc.msg}") from exc
        if trace.get("schema_version") != TRACE_SCHEMA_VERSION:
            mismatches.append(f"line {line_number}: trace schema mismatch")
            continue
        if trace.get("runner_protocol_version") != RUNNER_PROTOCOL_VERSION:
            mismatches.append(f"line {line_number}: runner protocol mismatch")
        if trace.get("eval_pack_id") != expected_pack_id:
            mismatches.append(f"line {line_number}: Eval Pack identity mismatch")
        if trace.get("manifest_digest") != expected_manifest_digest:
            mismatches.append(f"line {line_number}: manifest digest mismatch")
        task_id = (trace.get("task") or {}).get("id")
        candidate_id = (trace.get("candidate") or {}).get("id")
        if task_id not in task_index:
            mismatches.append(f"line {line_number}: unknown task")
            continue
        if candidate_id not in candidate_index:
            mismatches.append(f"line {line_number}: unknown candidate")
            continue
        forbidden = _find_keys(trace, _ENGINEERING_PROVENANCE_KEYS)
        if forbidden:
            mismatches.append(f"line {line_number}: forbidden Runner provenance")
        task = task_index[task_id]
        if (trace.get("task") or {}).get("task_digest") != _canonical_hash(task):
            mismatches.append(f"line {line_number}: task digest mismatch")
        if (trace.get("candidate") or {}).get("config_digest") != candidate_index[
            candidate_id
        ].config_sha256:
            mismatches.append(f"line {line_number}: candidate config digest mismatch")
        if (trace.get("candidate") or {}).get("run_config_digest") not in {
            None,
            _run_config_digest(candidate_index[candidate_id]),
        }:
            mismatches.append(f"line {line_number}: run config digest mismatch")
        score, evidence, violations, components = grade_report_case(
            task,
            trace.get("output"),
            trace.get("error"),
            list(trace.get("tool_calls") or []),
        )
        outcome = _classify(trace.get("error"), score)
        expected = {
            "score": score,
            "score_components": components,
            "evidence_refs": evidence,
            "safety_violations": violations,
            "outcome": outcome,
            "gate_diagnostics": _diagnostics(task, outcome, score),
            "reliability_pass": outcome == "candidate_success",
            "failure_signature": _failure_signature(task, outcome, score, evidence),
        }
        for key, value in expected.items():
            if trace.get(key) != value:
                mismatches.append(f"line {line_number}: {key} differs after regrade")
    if not count:
        raise BenchInputError("eval replay input contains no traces")
    return {
        "status": "verified" if not mismatches else "mismatch",
        "traces_regraded": count,
        "mismatches": mismatches,
        "eval_pack_id": expected_pack_id,
        "manifest_digest": expected_manifest_digest,
        "runner_protocol_version": RUNNER_PROTOCOL_VERSION,
        "network_calls_performed": 0,
        "claim_boundary": "offline_mock_only_no_model_or_agent_ranking",
    }
