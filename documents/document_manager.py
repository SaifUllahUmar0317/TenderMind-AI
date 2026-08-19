import os
import json
from config import TEMP_FOLDER

REGISTRY_PATH = os.path.join(TEMP_FOLDER, "document_registry.json")

class DocumentManager:
    """
    Central registry for uploaded documents, indexing state, and active document selection.
    """

    _active_doc_id = None

    @classmethod
    def _load_registry(cls) -> dict:
        if os.path.exists(REGISTRY_PATH):
            try:
                with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"active_document_id": None, "documents": {}}

    @classmethod
    def _save_registry(cls, data: dict):
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @classmethod
    def register_document(cls, doc_id: str, filename: str, page_count: int, file_size: int, overall_type: str) -> dict:
        reg = cls._load_registry()
        doc_entry = {
            "document_id": doc_id,
            "filename": filename,
            "page_count": page_count,
            "file_size": file_size,
            "overall_type": overall_type,
            "status": "indexing"
        }
        reg["documents"][doc_id] = doc_entry
        reg["active_document_id"] = doc_id
        cls._active_doc_id = doc_id
        cls._save_registry(reg)
        return doc_entry

    @classmethod
    def update_status(cls, doc_id: str, status: str, chunk_count: int = 0):
        reg = cls._load_registry()
        if doc_id in reg["documents"]:
            reg["documents"][doc_id]["status"] = status
            reg["documents"][doc_id]["chunk_count"] = chunk_count
            cls._save_registry(reg)

    @classmethod
    def list_documents(cls) -> list:
        reg = cls._load_registry()
        active_id = reg.get("active_document_id")
        docs = []
        for d_id, meta in reg.get("documents", {}).items():
            item = dict(meta)
            item["is_active"] = (d_id == active_id)
            docs.append(item)
        return docs

    @classmethod
    def set_active_document(cls, doc_id: str) -> bool:
        reg = cls._load_registry()
        if doc_id in reg.get("documents", {}):
            reg["active_document_id"] = doc_id
            cls._active_doc_id = doc_id
            cls._save_registry(reg)
            return True
        return False

    @classmethod
    def get_active_document_id(cls) -> str:
        reg = cls._load_registry()
        return reg.get("active_document_id")

    @classmethod
    def delete_document(cls, doc_id: str) -> bool:
        reg = cls._load_registry()
        if doc_id in reg["documents"]:
            del reg["documents"][doc_id]
            if reg.get("active_document_id") == doc_id:
                remaining = list(reg["documents"].keys())
                reg["active_document_id"] = remaining[0] if remaining else None
            cls._save_registry(reg)
            return True
        return False
