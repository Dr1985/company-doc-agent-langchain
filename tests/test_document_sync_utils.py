from src.utils.document_sync import (
    StoredObjectRecord,
    build_storage_object_name,
    plan_minio_document_sync,
)


def test_build_storage_object_name_preserves_original_filename():
    object_name = build_storage_object_name(r"nested\\windows/path/员工手册.pdf", prefix="sync-batch")

    assert object_name == "sync-batch/员工手册.pdf"


def test_plan_minio_document_sync_creates_candidates_for_missing_supported_objects():
    stored_objects = [
        StoredObjectRecord(object_name="manual/员工手册.pdf", size=1024),
        StoredObjectRecord(object_name="existing/readme.md", size=256),
        StoredObjectRecord(object_name="notes/todo.txt", size=64),
        StoredObjectRecord(object_name="ignored/image.png", size=512),
        StoredObjectRecord(object_name="ignored/no-extension", size=512),
    ]

    plan = plan_minio_document_sync(
        stored_objects=stored_objects,
        existing_storage_paths={"existing/readme.md", "stale/tmp.pdf"},
        allowed_extensions={"pdf", "md", "txt", "docx"},
    )

    assert plan.scanned_objects == 5
    assert plan.skipped_existing == 1
    assert plan.skipped_unsupported == 2
    assert plan.stale_storage_paths == ("stale/tmp.pdf",)
    assert [candidate.object_name for candidate in plan.candidates] == [
        "manual/员工手册.pdf",
        "notes/todo.txt",
    ]
    assert [candidate.filename for candidate in plan.candidates] == [
        "员工手册.pdf",
        "todo.txt",
    ]
    assert [candidate.file_type for candidate in plan.candidates] == ["pdf", "txt"]
    assert [candidate.file_size for candidate in plan.candidates] == [1024, 64]

