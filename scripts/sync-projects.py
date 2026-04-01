#!/usr/bin/env python3
"""
Синхронизация документации из репозиториев проектов в портфолио.

Usage:
    python scripts/sync-projects.py --project 1c_tj_logs --dry-run
    python scripts/sync-projects.py --all --force
"""

import argparse
import hashlib
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

import yaml

try:
    from git import Repo
except ImportError:
    print("❌ Установите GitPython: pip install GitPython")
    sys.exit(1)

# ==================== КОНФИГУРАЦИЯ ====================

PROJECTS_CONFIG: Dict[str, Dict[str, Any]] = {
    "1c_tj_logs": {
        "repo_url": "https://github.com/andreynetrebin/1c_tj_logs",
        "branch": "main",
        "source_path": "docs/portfolio",
        "target_slug": "1c-tj-logs",
        "enabled": True,
    },
    # Добавьте остальные проекты по аналогии:
    # "lakehouse-local": {
    #     "repo_url": "https://github.com/andreynetrebin/lakehouse-local",
    #     "branch": "main",
    #     "source_path": "docs/portfolio",
    #     "target_slug": "lakehouse-local",
    #     "enabled": True,
    # },
}

# ==================== ПУТИ ====================

PORTFOLIO_ROOT = Path(__file__).parent.parent
PROJECTS_TARGET = PORTFOLIO_ROOT / "docs" / "projects"
MANIFEST_FILE = PROJECTS_TARGET / "_sync-manifest.json"
TEMP_DIR = PORTFOLIO_ROOT / ".sync-temp"
ASSETS_TARGET = PORTFOLIO_ROOT / "docs" / "assets" / "projects"

# ==================== ЛОГИРОВАНИЕ ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


# ==================== УТИЛИТЫ ====================

def compute_file_hash(filepath: Path) -> str:
    if not filepath.exists():
        return ""
    with open(filepath, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_manifest() -> dict:
    if MANIFEST_FILE.exists():
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"projects": {}, "last_sync": None}


def save_manifest(manifest: dict):
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def clone_or_fetch(repo_url: str, branch: str, temp_dir: Path) -> Repo:
    import subprocess

    if temp_dir.exists():
        logger.info(f"🔄 Обновление репозитория {repo_url}")
        repo = Repo(temp_dir)
        repo.remotes.origin.fetch()
        repo.git.checkout(branch)
        repo.remotes.origin.pull()
    else:
        logger.info(f"📥 Клонирование {repo_url}")
        temp_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "-b", branch, repo_url, str(temp_dir)],
            check=True,
            capture_output=True
        )
        repo = Repo(temp_dir)
    return repo


def rewrite_relative_links(content: str, project_slug: str) -> str:
    import re

    def replace_link(match):
        full_match = match.group(0)
        link_text = match.group(1)
        link_path = match.group(2)

        if link_path.startswith(("http://", "https://", "#", "/")):
            return full_match

        clean_path = link_path.replace("./", "").replace("../", "")
        return f"[{link_text}](../{project_slug}/{clean_path})"

    def replace_image(match):
        full_match = match.group(0)
        alt_text = match.group(1)
        img_path = match.group(2)

        if img_path.startswith(("http://", "https://", "/")):
            return full_match

        clean_path = img_path.replace("./", "").replace("../", "")
        return f"![{alt_text}](../../assets/projects/{project_slug}/{clean_path})"

    content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, content)
    content = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_image, content)

    return content


def add_frontmatter(content: str, meta: dict, source_commit: str) -> str:
    frontmatter = [
        "---",
        "generated: true",
        f"source_repo: {meta.get('project', {}).get('repo', '')}",
        f"source_commit: {source_commit}",
        f"last_sync: {datetime.utcnow().isoformat()}Z",
        "---",
        "",
    ]
    return "\n".join(frontmatter) + content


# ==================== ОСНОВНАЯ ЛОГИКА ====================

def sync_project(project_key: str, config: dict, dry_run: bool = False, force: bool = False) -> bool:
    logger.info(f"🔄 Синхронизация: {project_key}")

    source_repo = config["repo_url"]
    branch = config["branch"]
    source_path = config["source_path"]
    target_slug = config["target_slug"]

    temp_dir = TEMP_DIR / project_key
    target_dir = PROJECTS_TARGET / target_slug

    try:
        repo = clone_or_fetch(source_repo, branch, temp_dir)
        source_commit = repo.head.commit.hexsha[:7]

        meta_path = Path(repo.working_dir) / source_path / "meta.yaml"
        if not meta_path.exists():
            logger.warning(f"⚠️ Не найден meta.yaml в {source_path}")
            return False

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f)

        manifest = load_manifest()
        project_manifest = manifest["projects"].get(project_key, {})

        files_to_sync = []
        source_root = Path(repo.working_dir) / source_path

        for pattern in meta.get("sync", {}).get("include", ["*.md", "assets/**/*"]):
            if "**" in pattern:
                base_pattern = pattern.replace("/**/*", "")
                search_path = source_root.rglob(base_pattern) if base_pattern else [source_root]
            else:
                search_path = source_root.glob(pattern)

            for filepath in search_path:
                if filepath.is_file():
                    rel_path = filepath.relative_to(source_root)

                    excluded = any(
                        rel_path.match(exc) or str(rel_path).startswith(exc)
                        for exc in meta.get("sync", {}).get("exclude", [])
                    )
                    if excluded:
                        continue

                    max_size = meta.get("sync", {}).get("max_file_size_mb", 10) * 1024 * 1024
                    if filepath.stat().st_size > max_size:
                        logger.warning(f"⚠️ Файл {rel_path} превышает лимит, пропускаем")
                        continue

                    current_hash = compute_file_hash(filepath)
                    stored_hash = project_manifest.get("files", {}).get(str(rel_path), "")

                    if force or current_hash != stored_hash:
                        files_to_sync.append((filepath, rel_path, current_hash))

        if not files_to_sync and not force:
            logger.info(f"✅ {project_key}: изменений нет")
            return True

        logger.info(f"📦 {project_key}: {len(files_to_sync)} файлов для обновления")

        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)

            for src_file, rel_path, file_hash in files_to_sync:
                dst_file = target_dir / rel_path
                dst_file.parent.mkdir(parents=True, exist_ok=True)

                content = src_file.read_text(encoding="utf-8")

                if src_file.suffix == ".md":
                    if meta.get("sync", {}).get("rewrite_links"):
                        content = rewrite_relative_links(content, target_slug)
                    if meta.get("sync", {}).get("add_frontmatter"):
                        content = add_frontmatter(content, meta, source_commit)

                dst_file.write_text(content, encoding="utf-8")
                logger.debug(f"  ✓ {rel_path}")

                project_manifest.setdefault("files", {})[str(rel_path)] = file_hash

                # Копирование изображений
                if src_file.suffix.lower() in ['.png', '.jpg', '.jpeg', '.svg', '.gif']:
                    assets_target = ASSETS_TARGET / target_slug
                    assets_target.mkdir(parents=True, exist_ok=True)
                    dst_asset = assets_target / rel_path.name
                    shutil.copy2(src_file, dst_asset)
                    logger.debug(f"  🖼️ Скопировано: {dst_asset}")

        if not dry_run:
            manifest["projects"][project_key] = {
                "last_sync": datetime.utcnow().isoformat() + "Z",
                "source_commit": source_commit,
                "files_count": len(files_to_sync),
                **project_manifest
            }
            manifest["last_sync"] = datetime.utcnow().isoformat() + "Z"
            save_manifest(manifest)

        logger.info(f"✅ {project_key}: синхронизация завершена")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка синхронизации {project_key}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Синхронизация документации проектов")
    parser.add_argument("--project", type=str, help="Синхронизировать конкретный проект")
    parser.add_argument("--all", action="store_true", help="Синхронизировать все проекты")
    parser.add_argument("--dry-run", action="store_true", help="Режим проверки без записи")
    parser.add_argument("--force", action="store_true", help="Принудительная синхронизация")

    args = parser.parse_args()

    if not args.project and not args.all:
        print("❌ Укажите --project <name> или --all")
        sys.exit(1)

    projects_to_sync = []
    if args.all:
        projects_to_sync = [(k, v) for k, v in PROJECTS_CONFIG.items() if v.get("enabled", True)]
    elif args.project:
        if args.project not in PROJECTS_CONFIG:
            print(f"❌ Проект '{args.project}' не найден в конфигурации")
            sys.exit(1)
        projects_to_sync = [(args.project, PROJECTS_CONFIG[args.project])]

    success_count = 0
    for project_key, config in projects_to_sync:
        if sync_project(project_key, config, dry_run=args.dry_run, force=args.force):
            success_count += 1

    logger.info(f"\n🎯 Готово: {success_count}/{len(projects_to_sync)} проектов обновлено")
    sys.exit(0 if success_count == len(projects_to_sync) else 1)


if __name__ == "__main__":
    main()