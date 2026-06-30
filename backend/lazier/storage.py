"""Project persistence + workspace layout. project.json is the truth; media lives
on the filesystem under the project dir."""

from __future__ import annotations

import json
from pathlib import Path

from .config import WORKSPACE
from .models import Project

SUBDIRS = ("audio", "media", "proxies", "exports")


def project_dir(project_id: str) -> Path:
    return WORKSPACE / project_id


def ensure_layout(project_id: str) -> Path:
    root = project_dir(project_id)
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _project_file(project_id: str) -> Path:
    return project_dir(project_id) / "project.json"


def save(project: Project) -> None:
    ensure_layout(project.id)
    tmp = _project_file(project.id).with_suffix(".json.tmp")
    tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(_project_file(project.id))  # atomic-ish write


def load(project_id: str) -> Project:
    f = _project_file(project_id)
    if not f.exists():
        raise FileNotFoundError(f"no project {project_id}")
    return Project.model_validate_json(f.read_text(encoding="utf-8"))


def exists(project_id: str) -> bool:
    return _project_file(project_id).exists()


def list_projects() -> list[dict]:
    out = []
    for d in sorted(WORKSPACE.iterdir() if WORKSPACE.exists() else []):
        pf = d / "project.json"
        if pf.exists():
            try:
                p = Project.model_validate_json(pf.read_text(encoding="utf-8"))
                out.append({
                    "id": p.id, "name": p.name, "aspect_ratio": p.aspect_ratio,
                    "created_at": p.created_at, "duration": p.duration,
                    "has_audio": p.audio_asset_id is not None,
                    "section_count": len(p.sections),
                })
            except Exception:
                continue
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


def abs_path(project_id: str, rel: str) -> Path:
    return project_dir(project_id) / rel
