# -*- coding: utf-8 -*-
"""产品图片图形化工作区的纯状态模型。"""
from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


CandidateStatus = Literal[
    "local",
    "warning",
    "invalid",
    "queued",
    "uploading",
    "uploaded",
    "failed",
    "canceled",
]


@dataclass(frozen=True)
class WorkspaceImage:
    image_id: str = ""
    image_url: str = ""
    image_name: str = ""
    image_source: str = "ttd"
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def workspace_image_from_api(value: dict[str, Any]) -> WorkspaceImage:
    image_id = str(value.get("imageId") or "").strip()
    image_url = str(value.get("imageUrl") or "").strip()
    if not image_id and not image_url:
        raise ValueError("图片缺少 imageId/imageUrl，不能进入工作区")
    return WorkspaceImage(
        image_id=image_id,
        image_url=image_url,
        image_name=str(value.get("imageName") or "").strip(),
        image_source=str(value.get("imageSource") or "ttd").strip() or "ttd",
        raw=copy.deepcopy(value),
    )


def workspace_image_key(image: WorkspaceImage) -> tuple[str, str]:
    if image.image_id:
        return "id", image.image_id
    return "url", image.image_url


@dataclass
class SiteImagePlan:
    code: str
    label: str
    raw_row: dict[str, Any]
    baseline: list[WorkspaceImage]
    planned: list[WorkspaceImage]

    @property
    def dirty(self) -> bool:
        baseline_keys = [workspace_image_key(image) for image in self.baseline]
        planned_keys = [workspace_image_key(image) for image in self.planned]
        return baseline_keys != planned_keys


@dataclass(frozen=True)
class LocalImageInspection:
    path: Path
    mime_type: str
    size_bytes: int
    width: int
    height: int
    allowed: bool
    warning: str = ""
    error: str = ""


@dataclass
class CandidateImage:
    path: Path
    status: CandidateStatus = "local"
    mime_type: str = ""
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    warning: str = ""
    error: str = ""
    uploaded: WorkspaceImage | None = None


@dataclass
class ProductImageEditorState:
    product_id: str
    product_info: dict[str, Any]
    sites: dict[str, SiteImagePlan]
    currency_context: Any = None
    candidates: dict[str, CandidateImage] = field(default_factory=dict)

    @property
    def dirty(self) -> bool:
        return any(site.dirty for site in self.sites.values())

    def baseline_by_site(self) -> dict[str, list[WorkspaceImage]]:
        return {
            code: list(site.baseline)
            for code, site in self.sites.items()
        }

    def planned_by_site(self) -> dict[str, list[WorkspaceImage]]:
        return {
            code: list(site.planned)
            for code, site in self.sites.items()
        }


def candidate_path_key(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def add_candidate(
    state: ProductImageEditorState,
    inspection: LocalImageInspection,
) -> CandidateImage:
    key = candidate_path_key(inspection.path)
    if key in state.candidates:
        raise ValueError(f"图片已在候选区：{inspection.path.name}")
    if not inspection.allowed:
        status: CandidateStatus = "invalid"
    elif inspection.warning:
        status = "warning"
    else:
        status = "local"
    candidate = CandidateImage(
        path=inspection.path,
        status=status,
        mime_type=inspection.mime_type,
        size_bytes=inspection.size_bytes,
        width=inspection.width,
        height=inspection.height,
        warning=inspection.warning,
        error=inspection.error,
    )
    state.candidates[key] = candidate
    return candidate


@dataclass(frozen=True)
class SiteImageDiff:
    added: tuple[tuple[str, str], ...]
    removed: tuple[tuple[str, str], ...]
    order_changed: bool


def _site(state: ProductImageEditorState, site_code: str) -> SiteImagePlan:
    try:
        return state.sites[site_code]
    except KeyError as exc:
        raise KeyError(f"未知图片站点：{site_code}") from exc


def add_image_to_site(
    state: ProductImageEditorState,
    site_code: str,
    image: WorkspaceImage,
    index: int | None = None,
) -> None:
    site = _site(state, site_code)
    key = workspace_image_key(image)
    if key in {workspace_image_key(item) for item in site.planned}:
        raise ValueError(f"图片 {key[1]} 已在站点 {site_code}")
    target = len(site.planned) if index is None else max(0, min(index, len(site.planned)))
    site.planned.insert(target, image)


def remove_image_from_site(
    state: ProductImageEditorState,
    site_code: str,
    index: int,
) -> WorkspaceImage:
    return _site(state, site_code).planned.pop(index)


def move_image_in_site(
    state: ProductImageEditorState,
    site_code: str,
    old_index: int,
    new_index: int,
) -> None:
    site = _site(state, site_code)
    if old_index == new_index:
        return
    image = site.planned.pop(old_index)
    target = max(0, min(new_index, len(site.planned)))
    site.planned.insert(target, image)


def copy_site_plan(
    state: ProductImageEditorState,
    source_code: str,
    target_codes: list[str],
) -> None:
    source = _site(state, source_code)
    for target_code in target_codes:
        if target_code == source_code:
            continue
        _site(state, target_code).planned = list(source.planned)


def restore_site(state: ProductImageEditorState, site_code: str) -> None:
    site = _site(state, site_code)
    site.planned = list(site.baseline)


def restore_product(state: ProductImageEditorState) -> None:
    for site_code in state.sites:
        restore_site(state, site_code)


def site_image_diff(site: SiteImagePlan) -> SiteImageDiff:
    baseline_keys = [workspace_image_key(image) for image in site.baseline]
    planned_keys = [workspace_image_key(image) for image in site.planned]
    baseline_counts = Counter(baseline_keys)
    planned_counts = Counter(planned_keys)
    added = tuple((planned_counts - baseline_counts).elements())
    removed = tuple((baseline_counts - planned_counts).elements())
    common_counts = baseline_counts & planned_counts

    def common_order(keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
        remaining = common_counts.copy()
        result: list[tuple[str, str]] = []
        for key in keys:
            if remaining[key] > 0:
                result.append(key)
                remaining[key] -= 1
        return result

    return SiteImageDiff(
        added=added,
        removed=removed,
        order_changed=common_order(baseline_keys) != common_order(planned_keys),
    )


def _planned_snapshot(
    state: ProductImageEditorState,
) -> dict[str, list[WorkspaceImage]]:
    return {
        code: list(site.planned)
        for code, site in state.sites.items()
    }


def _restore_snapshot(
    state: ProductImageEditorState,
    snapshot: dict[str, list[WorkspaceImage]],
) -> None:
    for code, images in snapshot.items():
        if code in state.sites:
            state.sites[code].planned = list(images)


class ProductImageEditHistory:
    def __init__(
        self,
        state: ProductImageEditorState,
        limit: int = 100,
    ) -> None:
        self.state = state
        self.limit = max(1, int(limit))
        self._undo: list[
            tuple[
                dict[str, list[WorkspaceImage]],
                dict[str, list[WorkspaceImage]],
            ]
        ] = []
        self._redo: list[
            tuple[
                dict[str, list[WorkspaceImage]],
                dict[str, list[WorkspaceImage]],
            ]
        ] = []

    def perform(self, operation: Callable[[], None]) -> None:
        before = _planned_snapshot(self.state)
        operation()
        after = _planned_snapshot(self.state)
        if before == after:
            return
        self._undo.append((before, after))
        self._undo = self._undo[-self.limit :]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        before, after = self._undo.pop()
        _restore_snapshot(self.state, before)
        self._redo.append((before, after))
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        before, after = self._redo.pop()
        _restore_snapshot(self.state, after)
        self._undo.append((before, after))
        return True

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


def make_product_editor_state(
    product_id: str,
    product_info: dict[str, Any],
    site_rows: list[dict[str, Any]],
    currency_context: Any = None,
) -> ProductImageEditorState:
    sites: dict[str, SiteImagePlan] = {}
    for index, row in enumerate(site_rows):
        code = str(
            row.get("languageCode")
            or row.get("languagelocale")
            or f"site-{index}"
        ).strip()
        label = str(row.get("languagelocale") or code).strip()
        images = [
            workspace_image_from_api(item)
            for item in row.get("imageList", [])
            if isinstance(item, dict)
        ]
        sites[code] = SiteImagePlan(
            code=code,
            label=label,
            raw_row=copy.deepcopy(row),
            baseline=list(images),
            planned=list(images),
        )
    return ProductImageEditorState(
        product_id=str(product_id),
        product_info=copy.deepcopy(product_info),
        sites=sites,
        currency_context=currency_context,
    )
