from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def _reference_value(reference: Any, field: str) -> str:
    if isinstance(reference, dict):
        return str(reference.get(field, "") or "")
    return str(getattr(reference, field, "") or "")


def _reference_key(reference: Any) -> tuple[str, ...]:
    return tuple(
        _reference_value(reference, field)
        for field in (
            "document_id",
            "local_path",
            "program_id",
            "plan_url",
            "resolved_url",
        )
    )


def validate_extractions(
    references: list[Any],
    results: list[dict[str, Any]],
    physical_files: list[Path],
    row_count: int,
    cell_count: int,
    all_references: list[Any] | None = None,
    invalid_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest_references = all_references or references
    expected_reference_keys = Counter(
        _reference_key(reference) for reference in manifest_references
    )
    attached_references = [
        reference
        for item in results
        for reference in item["document"].get("source_references", [])
    ]
    attached_reference_keys = Counter(
        _reference_key(reference) for reference in attached_references
    )
    expected_paths = {
        reference.get("local_path", "").replace("\\", "/")
        for reference in attached_references
    }
    actual_paths = {path.as_posix() for path in physical_files}
    invalid_results = [
        {
            "document_id": item["document"].get("document_id"),
            "status": item["document"].get("status"),
            "errors": item["document"].get("errors", []),
        }
        for item in results
        if item["document"].get("status") in {"missing", "invalid_source", "error"}
    ]
    tableless_pdfs = [
        item["document"].get("document_id")
        for item in results
        if item["document"].get("kind") == "pdf"
        and item["document"].get("table_count", 0) == 0
    ]
    no_raw_content = [
        item["document"].get("document_id")
        for item in results
        if not item.get("layout_text", "").strip()
        and item["document"].get("kind") == "pdf"
    ]
    size_mismatches: list[dict[str, Any]] = []
    hash_mismatches: list[dict[str, Any]] = []
    document_count_mismatches: list[dict[str, Any]] = []
    table_count_mismatches: list[dict[str, Any]] = []
    for item in results:
        document = item["document"]
        if document.get("expected_size") is not None and document.get(
            "source_size"
        ) != document.get("expected_size"):
            size_mismatches.append(
                {
                    "document_id": document.get("document_id"),
                    "expected": document.get("expected_size"),
                    "actual": document.get("source_size"),
                }
            )
        expected_hash = str(document.get("expected_sha256") or "").lower()
        if (
            expected_hash
            and expected_hash != str(document.get("source_sha256") or "").lower()
        ):
            hash_mismatches.append(
                {
                    "document_id": document.get("document_id"),
                    "expected": expected_hash,
                    "actual": document.get("source_sha256"),
                }
            )
        actual_table_count = len(item.get("tables", []))
        actual_row_count = sum(
            len(table.get("rows", [])) for table in item.get("tables", [])
        )
        actual_cell_count = sum(
            len(row)
            for table in item.get("tables", [])
            for row in table.get("rows", [])
        )
        for field, actual in (
            ("table_count", actual_table_count),
            ("row_count", actual_row_count),
            ("cell_count", actual_cell_count),
        ):
            declared = document.get(field)
            if declared is not None and int(declared or 0) != actual:
                document_count_mismatches.append(
                    {
                        "document_id": document.get("document_id"),
                        "field": field,
                        "declared": declared,
                        "actual": actual,
                    }
                )
        for table in item.get("tables", []):
            actual_table_rows = len(table.get("rows", []))
            declared_table_rows = table.get("row_count")
            if (
                declared_table_rows is not None
                and int(declared_table_rows or 0) != actual_table_rows
            ):
                table_count_mismatches.append(
                    {
                        "table_id": table.get("id"),
                        "field": "row_count",
                        "declared": declared_table_rows,
                        "actual": actual_table_rows,
                    }
                )
    statuses = Counter(item["document"].get("status", "unknown") for item in results)
    kinds = Counter(item["document"].get("kind", "unknown") for item in results)
    checks = {
        "canonical_document_count_matches_manifest": len(results) == len(references),
        "manifest_reference_count_matches_attached": len(manifest_references)
        == len(attached_references),
        "all_manifest_references_attached": expected_reference_keys
        == attached_reference_keys,
        "all_referenced_files_exist": expected_paths.issubset(actual_paths),
        "no_invalid_or_failed_documents": not invalid_results,
        "all_pdf_tables_detected": not tableless_pdfs,
        "all_pdf_raw_layout_captured": not no_raw_content,
        "source_sizes_match_metadata": not size_mismatches,
        "source_hashes_match_metadata": not hash_mismatches,
        "document_counts_match_materialized_data": not document_count_mismatches,
        "table_counts_match_materialized_data": not table_count_mismatches,
        "all_table_rows_and_cells_materialized": (
            row_count > 0
            and cell_count > 0
            and not document_count_mismatches
            and not table_count_mismatches
        ),
        "no_unreferenced_downloads": actual_paths.issubset(expected_paths),
        "all_manifest_references_valid": not invalid_references,
    }
    checks["passed"] = all(checks.values())
    return {
        "verification": checks,
        "counts": {
            "manifest_references": len(manifest_references),
            "attached_references": len(attached_references),
            "unique_documents": len(results),
            "physical_files": len(physical_files),
            "tables": sum(item["document"].get("table_count", 0) for item in results),
            "rows": row_count,
            "cells": cell_count,
        },
        "file_kinds": dict(sorted(kinds.items())),
        "document_statuses": dict(sorted(statuses.items())),
        "invalid_documents": invalid_results,
        "tableless_pdfs": tableless_pdfs,
        "documents_without_raw_layout": no_raw_content,
        "size_mismatches": size_mismatches,
        "hash_mismatches": hash_mismatches,
        "document_count_mismatches": document_count_mismatches,
        "table_count_mismatches": table_count_mismatches,
        "invalid_references": invalid_references or [],
        "unreferenced_downloads": sorted(actual_paths - expected_paths),
        "warnings": [
            {
                "document_id": item["document"].get("document_id"),
                "warnings": item["document"].get("warnings", []),
            }
            for item in results
            if item["document"].get("warnings")
        ],
    }
