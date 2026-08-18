"""Strict v8 validator with case/variant-to-artifact input binding."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from financial_agent_reliability.harness.hashing import build_run_id, file_sha256
from financial_agent_reliability.harness.secret_scan import scan_persisted_value_for_secrets
from financial_agent_reliability.inference_config import load_inference_config


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCHEMA_PATH = pathlib.Path(__file__).resolve().parent / "contracts/run_trace.schema.v8.json"
HARNESS_CONTRACT_PATH = ROOT / "configs/harness_contract.v1.json"
InputKey = tuple[str, str]


@dataclass(frozen=True)
class FrozenInputCommitment:
    """Registry commitment transported intact into trace verification."""

    path: str
    sha256: str
    actual_path: pathlib.Path


def load_frozen_input_registry(
    registry_path: pathlib.Path,
) -> tuple[dict[InputKey, FrozenInputCommitment], list[str]]:
    """Load path+SHA commitments and independently bind them to real files."""

    errors: list[str] = []
    path = pathlib.Path(registry_path)
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"registry load: {exc}"]
    if not isinstance(registry, Mapping) or not isinstance(registry.get("entries"), list):
        return {}, ["registry: entries must be an array"]
    root = path.parent.parent
    commitments: dict[InputKey, FrozenInputCommitment] = {}
    for item in registry["entries"]:
        if not isinstance(item, Mapping):
            errors.append("registry: entry must be an object")
            continue
        key = (str(item.get("case_id")), str(item.get("variant_id")))
        relative = str(item.get("path"))
        commitment = FrozenInputCommitment(
            path=relative,
            sha256=str(item.get("sha256")),
            actual_path=(root / relative).resolve(),
        )
        if key in commitments:
            errors.append(f"registry: duplicate case/variant {key}")
        commitments[key] = commitment
        try:
            actual_sha = file_sha256(commitment.actual_path)
        except OSError as exc:
            errors.append(f"registry: cannot read actual frozen file {relative} ({exc})")
            continue
        if actual_sha != commitment.sha256:
            errors.append(f"registry: sha256 != actual frozen file {relative}")
        try:
            card = json.loads(commitment.actual_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"registry: cannot load frozen case {relative} ({exc})")
            continue
        if card.get("case_id") != key[0]:
            errors.append(f"registry: path {relative} belongs to a different case")
        if card.get("variant", {}).get("kind") != key[1]:
            errors.append(f"registry: path {relative} belongs to a different variant")
    return commitments, errors


def _bundle_sha256(artifacts: list[Mapping[str, Any]]) -> str:
    commitments = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(artifacts, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(commitments.encode("utf-8")).hexdigest()


def _schema_errors(trace: Any) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(trace),
        key=lambda item: list(item.absolute_path),
    )
    return [
        "schema $/{}: {}".format(
            "/".join(str(part) for part in error.absolute_path), error.message
        )
        for error in errors
    ]


def verify_trace(
    trace_path: pathlib.Path,
    *,
    registered_inputs: Mapping[InputKey, FrozenInputCommitment] | None = None,
    registry_path: pathlib.Path | None = None,
    inference_config_path: pathlib.Path | None = None,
) -> list[str]:
    """Validate v8 against registry, file, bundle, and context commitments."""

    if registered_inputs is None:
        registered_inputs, registry_errors = load_frozen_input_registry(
            registry_path or ROOT / "baseline/v5/contracts/frozen_input_registry.frozen.v5.json"
        )
        if registry_errors:
            return registry_errors

    path = pathlib.Path(trace_path)
    try:
        trace = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"trace load: {exc}"]
    errors = _schema_errors(trace)
    if errors or not isinstance(trace, Mapping):
        return errors

    identity = trace["run_identity"]
    provider = trace["provider"]
    bundle = trace["immutable_bundle"]
    request = trace["request"]
    context = trace["context"]

    if trace["run_id"] != build_run_id(identity):
        errors.append("anchor run_id: does not recompute from full run_identity")
    if identity["requested_model_id"] != provider["requested_model_id"]:
        errors.append("anchor requested_model_id: run_identity != provider")
    if identity["seed"] != request.get("seed"):
        errors.append("anchor seed: run_identity != request")
    if identity["inference_config_path"] != provider["inference_config_path"]:
        errors.append("anchor inference_config_path: run_identity != provider")
    if identity["inference_config_sha256"] != provider["inference_config_sha256"]:
        errors.append("anchor inference_config_sha256: run_identity != provider")
    if identity["immutable_bundle_sha256"] != bundle["bundle_sha256"]:
        errors.append("anchor immutable_bundle_sha256: run_identity != immutable_bundle")

    actual_config_path = pathlib.Path(
        inference_config_path or identity["inference_config_path"]
    ).resolve()
    if identity["inference_config_path"] != actual_config_path.as_posix():
        errors.append("anchor inference_config_path: trace != actual resolved path")
    try:
        actual_config_sha = file_sha256(actual_config_path)
        config = load_inference_config(actual_config_path, env={})
    except Exception as exc:
        errors.append(f"anchor inference config: cannot load verified config ({exc})")
        config = None
        actual_config_sha = None
    if actual_config_sha != identity["inference_config_sha256"]:
        errors.append("anchor inference_config_sha256: trace != actual file")
    if identity["harness_contract_sha256"] != file_sha256(HARNESS_CONTRACT_PATH):
        errors.append("anchor harness_contract_sha256: trace != actual file")

    if config is not None:
        try:
            configured_models = config.models_for_provider(provider["name"])
        except Exception:
            configured_models = ()
        matching = [
            model
            for model in configured_models
            if model.model_id == provider["requested_model_id"]
        ]
        if len(matching) != 1:
            errors.append("anchor provider/model: requested model not uniquely configured")
        elif provider["response_model_id"] not in matching[0].allowed_response_model_ids:
            errors.append("anchor response_model_id: not allowed by configured ModelConfig")
    if not str(provider["endpoint_id"]).startswith(f"{provider['name']}_"):
        errors.append("anchor endpoint_id: provider prefix mismatch")

    artifacts = bundle["artifacts"]
    if _bundle_sha256(artifacts) != bundle["bundle_sha256"]:
        errors.append("anchor immutable_bundle: aggregate does not recompute")
    artifact_by_path = {item["path"]: item["sha256"] for item in artifacts}
    if len(artifact_by_path) != len(artifacts):
        errors.append("anchor immutable_bundle: duplicate artifact path")
    input_key = (identity["case_id"], identity["variant_id"])
    commitment = registered_inputs.get(input_key)
    if commitment is None:
        errors.append("registered frozen input: case/variant is not registered")
    elif not isinstance(commitment, FrozenInputCommitment):
        errors.append("registered frozen input: commitment must include typed path and sha256")
    elif context["frozen_input_path"] != commitment.path:
        errors.append("registered frozen input: trace path != case/variant registry")
    elif commitment.path not in artifact_by_path:
        errors.append("registered frozen input: path is not committed by immutable bundle")
    else:
        try:
            actual_input_sha = file_sha256(commitment.actual_path)
        except OSError as exc:
            errors.append(f"registered frozen input: cannot read actual frozen file ({exc})")
            actual_input_sha = None
        artifact_sha = artifact_by_path[commitment.path]
        context_sha = context["frozen_input_sha256"]
        if actual_input_sha != commitment.sha256:
            errors.append("registered frozen input: registry sha256 != actual frozen file")
        if artifact_sha != commitment.sha256:
            errors.append("registered frozen input: registry sha256 != bundle artifact")
        if context_sha != commitment.sha256:
            errors.append("registered frozen input: registry sha256 != trace context")
    if trace["environment"].get("network_scope") != "configured_provider_inference_only":
        errors.append("anchor network_scope: must be configured-provider scoped")

    scan_target = copy.deepcopy(trace)
    scan_target["redaction"]["secret_fields_removed"] = []
    scan_target["run_identity"]["inference_config_path"] = ""
    scan_target["provider"]["inference_config_path"] = ""
    if scan_persisted_value_for_secrets(scan_target):
        errors.append("secret scan: trace contains secret-shaped persisted content")
    return errors
