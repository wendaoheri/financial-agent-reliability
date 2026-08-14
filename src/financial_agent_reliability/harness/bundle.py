"""Content-addressed immutable input bundle support."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
from dataclasses import dataclass


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate(entries: list[dict[str, str]]) -> str:
    commitments = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(entries, key=lambda item: item["path"])
    )
    return hashlib.sha256(commitments.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ImmutableBundle:
    root: pathlib.Path
    bundle_sha256: str
    artifacts: tuple[tuple[str, str], ...]

    @classmethod
    def create(cls, source: pathlib.Path, destination: pathlib.Path) -> "ImmutableBundle":
        source = pathlib.Path(source).resolve()
        destination = pathlib.Path(destination)
        if not source.is_dir():
            raise ValueError("bundle source must be a directory")
        if destination.exists():
            raise FileExistsError("immutable bundle destination already exists")
        destination.mkdir(parents=True)
        entries: list[dict[str, str]] = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"symlinks are forbidden in immutable bundles: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(source).as_posix()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            entries.append({"path": relative, "sha256": _sha256(target)})
        bundle_hash = _aggregate(entries)
        manifest = {
            "contract_type": "immutable_run_bundle",
            "contract_version": "1.0.0",
            "bundle_sha256": bundle_hash,
            "artifacts": entries,
        }
        manifest_path = destination / "bundle.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        for path in sorted(destination.rglob("*"), reverse=True):
            if path.is_file():
                os.chmod(path, 0o444)
            elif path.is_dir():
                os.chmod(path, 0o555)
        os.chmod(destination, 0o555)
        return cls(
            root=destination,
            bundle_sha256=bundle_hash,
            artifacts=tuple((item["path"], item["sha256"]) for item in entries),
        )

    @classmethod
    def open(cls, root: pathlib.Path) -> "ImmutableBundle":
        root = pathlib.Path(root)
        manifest = json.loads((root / "bundle.manifest.json").read_text(encoding="utf-8"))
        artifacts = tuple(
            (str(item["path"]), str(item["sha256"])) for item in manifest["artifacts"]
        )
        return cls(root, str(manifest["bundle_sha256"]), artifacts)

    def verify(self) -> str:
        entries: list[dict[str, str]] = []
        for relative, expected in self.artifacts:
            path = self.root / relative
            if not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"immutable artifact mismatch: {relative}")
            entries.append({"path": relative, "sha256": expected})
        actual = _aggregate(entries)
        if actual != self.bundle_sha256:
            raise ValueError("immutable bundle aggregate mismatch")
        return actual

    def write_text(self, relative: str, value: str) -> None:
        del relative, value
        raise PermissionError("immutable run bundles are read-only")
