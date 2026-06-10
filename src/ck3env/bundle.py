"""Proof bundles (docs/architecture.md): everything needed to audit and re-score a run
without CK3 installed. Sealing status is recorded, never assumed."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from . import __version__

ARTIFACTS = (
    "episode.json",
    "observation.json",
    "snapshot.json",
    "steps.jsonl",
    "transport_state.json",
)


def build(run_dir: Path, sealed: bool = False) -> Path:
    run_dir = Path(run_dir)
    manifest: dict = {
        "harness_version": __version__,
        "sealed": sealed,
        "artifacts": {},
    }
    bundle_path = run_dir / "bundle.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ARTIFACTS:
            path = run_dir / name
            if not path.exists():
                continue
            data = path.read_bytes()
            manifest["artifacts"][name] = hashlib.sha256(data).hexdigest()
            archive.writestr(name, data)
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return bundle_path


def rescore(bundle_path: Path) -> dict:
    """Recompute the scorecard purely from bundle contents."""
    from .observe import Snapshot
    from .score import compute

    with zipfile.ZipFile(bundle_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for name, expected in manifest["artifacts"].items():
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected:
                raise ValueError(f"bundle artifact tampered: {name}")
        snapshot = Snapshot.from_json(json.loads(archive.read("snapshot.json")))
        steps = [
            json.loads(line)
            for line in archive.read("steps.jsonl").decode().splitlines()
            if line
        ] if "steps.jsonl" in manifest["artifacts"] else []
    return compute(snapshot, steps)
