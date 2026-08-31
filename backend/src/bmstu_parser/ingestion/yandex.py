from __future__ import annotations

import copy
import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from ..config import YANDEX_RESOURCE_ENDPOINT
from ..domain.ids import stable_id
from ..domain.models import Major, PlanFile, StudyPlan
from ..transform.text import clean_slug, first_text, safe_filename
from .http import ApiClient, FetchError


def is_yandex_public_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    return host.endswith("yandex.ru") or host.endswith("yandex.com") or host.endswith("yadi.sk")


class StudyPlanResolver:
    def __init__(self, client: ApiClient, output_dir: Path) -> None:
        self.client = client
        self.output_dir = output_dir
        self.plan_root = output_dir / "study_plans"

    def _resource(self, public_url: str, path: str | None = None, offset: int = 0) -> dict[str, Any]:
        params: dict[str, Any] = {"public_key": public_url, "limit": 100, "offset": offset}
        if path:
            params["path"] = path
        return self.client.get_json(YANDEX_RESOURCE_ENDPOINT, params=params)

    def _collect_yandex_files(self, public_url: str) -> list[dict[str, Any]]:
        first = self._resource(public_url)
        if first.get("type") == "file":
            return [first]

        files: list[dict[str, Any]] = []
        visited: set[str] = set()

        def walk(path: str, depth: int = 0) -> None:
            if depth > 6 or path in visited:
                return
            visited.add(path)
            offset = 0
            while True:
                page = self._resource(public_url, path=path, offset=offset)
                embedded = page.get("_embedded") if isinstance(page.get("_embedded"), dict) else {}
                children = [item for item in embedded.get("items", []) if isinstance(item, dict)]
                for child in children:
                    child_path = str(child.get("path", ""))
                    if child.get("type") == "dir":
                        walk(child_path, depth + 1)
                    elif child.get("type") == "file":
                        try:
                            files.append(self._resource(public_url, path=child_path))
                        except FetchError:
                            files.append(child)
                total = embedded.get("total")
                if not children or not isinstance(total, int) or offset + len(children) >= total:
                    break
                offset += len(children)

        walk(str(first.get("path", "/")))
        return files

    def _file(self, metadata: dict[str, Any], source_url: str, resolved_url: str) -> PlanFile:
        path = str(metadata.get("path", ""))
        name = first_text(metadata.get("name"), Path(unquote(path)).name, "study_plan")
        return PlanFile(
            id=stable_id("study-plan-document", source_url, path or name),
            name=name,
            path=path,
            size=metadata.get("size"),
            mime_type=first_text(metadata.get("mime_type"), metadata.get("media_type")),
            md5=str(metadata.get("md5", "")),
            sha256=str(metadata.get("sha256", "")),
            source_url=source_url,
            resolved_url=resolved_url,
            download_url=str(metadata.get("file", "")),
        )

    def resolve(self, plan_url: str, visited: set[str] | None = None) -> StudyPlan:
        if not plan_url:
            return StudyPlan(url="", status="missing")
        visited = set(visited or set())
        if plan_url in visited:
            raise FetchError(f"Циклическая переадресация ссылки на план: {plan_url}")
        visited.add(plan_url)

        host = urlparse(plan_url).netloc.lower().split(":", 1)[0]
        if host.endswith(("clck.su", "clck.ru")):
            response = self.client.request(plan_url)
            candidates: list[str] = []
            for history_response in response.history:
                location = history_response.headers.get("Location")
                if location:
                    candidates.append(urljoin(history_response.url, location))
            candidates.append(response.url)
            resolved_url = next(
                (
                    candidate
                    for candidate in candidates
                    if is_yandex_public_url(candidate)
                    and urlparse(candidate).path.startswith(("/i/", "/d/"))
                ),
                "",
            )
            if not resolved_url:
                match = re.search(
                    r"(?:var|let|const)\s+redirectUrl\s*=\s*[\"']([^\"']+)[\"']",
                    response.text,
                    flags=re.IGNORECASE,
                )
                if match:
                    resolved_url = html.unescape(match.group(1)).replace("\\/", "/")
            if not resolved_url:
                raise FetchError(f"В короткой ссылке не найдена ссылка на публичный ресурс: {plan_url}")
            result = self.resolve(resolved_url, visited)
            result.url = plan_url
            result.resolved_url = resolved_url
            for file_info in result.files:
                file_info.source_url = plan_url
            return result

        if is_yandex_public_url(plan_url):
            metadata = self._collect_yandex_files(plan_url)
            files = [self._file(item, plan_url, plan_url) for item in metadata]
            return StudyPlan(
                url=plan_url,
                resolved_url=plan_url,
                status="resolved" if files else "resolved_empty",
                files=files,
            )

        filename = Path(unquote(urlparse(plan_url).path)).name or "study_plan"
        return StudyPlan(
            url=plan_url,
            resolved_url=plan_url,
            status="resolved",
            files=[
                PlanFile(
                    id=stable_id("study-plan-document", plan_url, filename),
                    name=filename,
                    path="",
                    size=None,
                    mime_type="",
                    md5="",
                    sha256="",
                    source_url=plan_url,
                    resolved_url=plan_url,
                    download_url=plan_url,
                )
            ],
        )

    def _destination(self, major_slug: str, program_id: str, file_info: PlanFile) -> Path:
        raw_path = str(file_info.path or "")
        path_parts = [safe_filename(part) for part in unquote(raw_path).strip("/").split("/") if part]
        if path_parts:
            filename = path_parts[-1]
            parent_parts = path_parts[:-1]
        else:
            filename = safe_filename(file_info.name, "study_plan")
            parent_parts = []
        return self.plan_root.joinpath(
            clean_slug(major_slug),
            clean_slug(program_id or "program"),
            *parent_parts,
            filename,
        )

    def download(self, major_slug: str, program_id: str, plan: StudyPlan) -> None:
        for file_info in plan.files:
            if not file_info.download_url:
                file_info.download_error = "У источника не найден прямой URL файла"
                continue
            destination = self._destination(major_slug, program_id, file_info)
            file_info.local_path = str(destination.relative_to(self.output_dir))
            expected_size = file_info.size
            if destination.exists() and (
                not isinstance(expected_size, int) or destination.stat().st_size == expected_size
            ):
                file_info.downloaded = True
                continue
            try:
                file_info.downloaded_size = self.client.download(file_info.download_url, destination)
                file_info.downloaded = True
            except FetchError as exc:
                file_info.download_error = str(exc)

    def enrich(self, majors: list[Major], resolve: bool = True, download: bool = False) -> None:
        if not resolve:
            return
        cache: dict[str, StudyPlan] = {}
        for major in majors:
            if major.status != "ok":
                continue
            for program in major.educational_programs:
                if not program.study_plan_url:
                    program.study_plan = StudyPlan(url="", status="missing")
                    continue
                try:
                    if program.study_plan_url not in cache:
                        cache[program.study_plan_url] = self.resolve(program.study_plan_url)
                    program.study_plan = copy.deepcopy(cache[program.study_plan_url])
                    if download:
                        self.download(major.slug, program.id, program.study_plan)
                except FetchError as exc:
                    program.study_plan = StudyPlan(
                        url=program.study_plan_url,
                        resolved_url=program.study_plan_url,
                        status="error",
                        error=str(exc),
                    )
