import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import config
import uuid
import threading
import time
from flask import Flask, render_template, request, jsonify, send_file, Response, abort
from werkzeug.utils import secure_filename

from services.pdf_analyzer import PDFAnalyzer
from services.text_extractor import TextExtractor
from services.image_preprocessor import ImagePreprocessor
from services.ocr_engine import OCREngine
from services.document_exporter import DocumentExporter

# PDF Tools Imports (Compressor & Combiner)
from pdf_tools.compressor import analyze_pdf, compress_pdf
from pdf_tools.combiner import process_file_into_pages, combine_pages_to_pdf

# RAG & Chatbot Modules
from rag.adapter import ExtractionAdapter
from rag.chunker import SemanticChunker
from rag.embeddings import EmbeddingGenerator
from rag.vector_store import VectorStore
from rag.keyword_search import BM25Search
from rag.retriever import HybridRetriever
from documents.summarizer import DocumentSummarizer
from documents.document_manager import DocumentManager
from llm.provider import LLMProvider
from citations.citation_manager import CitationManager
from chat.conversation import ConversationMemory


# Tender Deadline Reminder System Imports
from deadlines.database import DeadlineDB, TimezoneHelper, DEFAULT_TIMEZONE
from deadlines.extractor import DeadlineExtractor
from deadlines.scheduler import DeadlineScheduler

app = Flask(__name__)
app.config.from_object(config)
app.config['MAX_CONTENT_LENGTH'] = config.COMBINER_MAX_CONTENT_LENGTH

# In-memory dictionary for active job status & results
JOBS = {}

# Active in-memory RAG retriever instances map: { doc_id: HybridRetriever }
RAG_INDEXES = {}


def get_or_create_rag_retriever(doc_id: str) -> HybridRetriever:
    """Retrieves or loads persistent FAISS + BM25 retriever for document."""
    if doc_id in RAG_INDEXES:
        return RAG_INDEXES[doc_id]

    vstore = VectorStore(doc_id)
    bm25 = BM25Search()
    if vstore.chunks:
        bm25.index_chunks(vstore.chunks)

    retriever = HybridRetriever(vstore, bm25)
    RAG_INDEXES[doc_id] = retriever
    return retriever

def update_job_status(job_id: str, status: str, progress: int, log_message: str = None, result: dict = None, error: str = None):
    """Helper to update background job state safely."""
    if job_id in JOBS:
        JOBS[job_id]["status"] = status
        JOBS[job_id]["progress"] = progress
        if log_message:
            JOBS[job_id]["logs"].append(log_message)
        if result:
            JOBS[job_id]["result"] = result
        if error:
            JOBS[job_id]["error"] = error

def run_pdf_extraction_pipeline(job_id: str, pdf_path: str, filename: str, file_size: int, lang: str = "eng"):
    """
    High-Speed Extraction & Indexing Pipeline:
    1. Single-pass high-speed PyMuPDF native block & table extraction.
    2. Instant semantic chunking.
    3. Multi-threaded batch vector embeddings & FAISS index building.
    4. Hierarchical summary caching.
    """
    try:
        update_job_status(job_id, "processing", 10, "Extracting document structure & text...")

        def on_page_progress(current_page, total_pages):
            pct = int(10 + (current_page / max(1, total_pages)) * 60)
            update_job_status(job_id, "processing", pct, f"Extracting page {current_page} of {total_pages}...")

        # Step 1: Single-pass fast extraction
        extracted = TextExtractor.extract_document_fast(pdf_path, progress_callback=on_page_progress, lang=lang)
        if not extracted.get("success"):
            update_job_status(job_id, "error", 0, error=extracted.get("error", "Failed to parse PDF document."))
            return

        page_count = extracted["page_count"]
        overall_type = extracted["overall_type"]

        # Register document
        DocumentManager.register_document(job_id, filename, page_count, file_size, overall_type)

        final_payload = {
            "job_id": job_id,
            "filename": filename,
            "page_count": page_count,
            "overall_type": overall_type,
            "word_count": extracted["word_count"],
            "character_count": extracted["character_count"],
            "pages": extracted["pages"],
            "full_text": extracted["full_text"]
        }

        # Step 2: Semantic Chunking
        update_job_status(job_id, "processing", 75, "Structuring semantic sections & tables...")
        adapted_doc = ExtractionAdapter.adapt_extraction_payload(final_payload, job_id, filename)
        chunker = SemanticChunker(target_chunk_size=1200, chunk_overlap=200)
        chunks = chunker.create_chunks(adapted_doc)

        # Step 3: Fast Batch Embeddings
        update_job_status(job_id, "processing", 85, f"Vectorizing {len(chunks)} chunks...")
        chunk_texts = [c["text"] for c in chunks]
        embeddings = EmbeddingGenerator.embed_texts(chunk_texts)

        # Step 4: Vector Store & BM25 Index
        update_job_status(job_id, "processing", 92, "Building FAISS vector index & BM25 store...")
        vstore = VectorStore(job_id)
        vstore.add_chunks(chunks, embeddings)

        bm25 = BM25Search()
        bm25.index_chunks(chunks)

        RAG_INDEXES[job_id] = HybridRetriever(vstore, bm25)

        # Step 5: Hierarchical Summary
        update_job_status(job_id, "processing", 95, "Finalizing summary & document hierarchy...")
        DocumentSummarizer.generate_hierarchical_summary(adapted_doc)
        DocumentManager.update_status(job_id, "ready", len(chunks))

        # Mark job completed FIRST — workspace opens immediately for the user
        update_job_status(
            job_id, "completed", 100,
            "Document processing & AI Chatbot indexing complete!",
            result=final_payload
        )

        # Step 6: Deadline extraction runs in background AFTER workspace is open
        # This avoids blocking the user waiting for LLM deadline scan
        def _extract_deadline_bg():
            try:
                deadline_info = DeadlineExtractor.extract_from_document(job_id, RAG_INDEXES.get(job_id))
                if deadline_info.get("has_deadline"):
                    saved_tender = DeadlineDB.save_tender_deadline(
                        tender_id=job_id,
                        title=deadline_info.get("tender_title") or filename,
                        organization=deadline_info.get("organization") or "Not specified",
                        submission_deadline=deadline_info.get("submission_deadline"),
                        opening_datetime=deadline_info.get("opening_datetime"),
                        tz_name=deadline_info.get("timezone", DEFAULT_TIMEZONE),
                        source_page=deadline_info.get("submission_deadline_source_page", 1),
                        file_name=filename,
                        reminder_config=None,
                        custom_reminders=[],
                        notification_channels=["in_app", "browser"],
                        detected_raw=deadline_info
                    )
                    # Patch the result in JOBS so subsequent polls pick it up
                    if job_id in JOBS and JOBS[job_id].get("result"):
                        JOBS[job_id]["result"]["deadline_info"] = deadline_info
                        JOBS[job_id]["result"]["deadline_saved"] = True
                        JOBS[job_id]["result"]["tender_deadline"] = saved_tender
                    print(f"[app.py] BG deadline extracted & scheduled (3d & 1d) for '{filename}' -> {saved_tender['display']['formatted']}")
                else:
                    if job_id in JOBS and JOBS[job_id].get("result"):
                        JOBS[job_id]["result"]["deadline_info"] = deadline_info
            except Exception as d_err:
                print(f"[app.py] BG deadline extraction error: {d_err}")

        dl_thread = threading.Thread(target=_extract_deadline_bg, daemon=True)
        dl_thread.start()

    except Exception as top_err:
        update_job_status(
            job_id, "error", 0,
            error=f"Unable to process this PDF: {str(top_err)}"
        )

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in config.ALLOWED_EXTENSIONS



# ------------------------------------------------------------------------------
# ROUTES
# ------------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html', languages=config.SUPPORTED_LANGUAGES)

@app.route('/api/upload', methods=['POST'])
def upload_pdf():
    """Handles PDF file upload and triggers async extraction + RAG indexing."""
    if 'pdf_file' not in request.files:
        return jsonify({"success": False, "error": "No PDF file attached to request."}), 400

    file = request.files['pdf_file']
    if file.filename == '':
        return jsonify({"success": False, "error": "No file selected."}), 400

    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Invalid file type. Only .pdf files are allowed."}), 400

    lang = request.form.get("ocr_lang", config.DEFAULT_OCR_LANG)

    job_id = str(uuid.uuid4())
    safe_name = secure_filename(file.filename)
    pdf_filename = f"{job_id}_{safe_name}"
    pdf_path = os.path.join(config.UPLOAD_FOLDER, pdf_filename)

    file.save(pdf_path)
    file_size = os.path.getsize(pdf_path)

    max_allowed = getattr(config, 'COMBINER_MAX_CONTENT_LENGTH', 2 * 1024 * 1024 * 1024)
    if file_size > max_allowed:
        try:
            os.remove(pdf_path)
        except Exception:
            pass
        return jsonify({"success": False, "error": "File size exceeds the maximum limit."}), 413

    JOBS[job_id] = {
        "job_id": job_id,
        "filename": file.filename,
        "pdf_path": pdf_path,
        "status": "queued",
        "progress": 0,
        "logs": ["File uploaded. Queuing for extraction & RAG indexing..."],
        "result": None,
        "error": None
    }

    thread = threading.Thread(
        target=run_pdf_extraction_pipeline,
        args=(job_id, pdf_path, file.filename, file_size, lang)
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        "success": True,
        "job_id": job_id,
        "filename": file.filename,
        "file_size": file_size
    })

@app.route('/api/status/<job_id>', methods=['GET'])
def get_job_status(job_id):
    """Returns current progress percentage, step logs, and status."""
    if job_id not in JOBS:
        return jsonify({"success": False, "error": "Job ID not found."}), 404

    job = JOBS[job_id]
    return jsonify({
        "success": True,
        "status": job["status"],
        "progress": job["progress"],
        "logs": job["logs"],
        "error": job["error"]
    })

def _reconstruct_result_from_disk(job_id: str) -> dict | None:
    """
    Reconstructs a minimal result payload from DocumentManager registry and
    persisted disk artifacts (FAISS index, summary cache) when the JOBS
    in-memory dict is empty (e.g. after a server restart).
    Returns a result dict compatible with enterWorkspace(), or None if not found.
    """
    reg = DocumentManager._load_registry()
    doc_meta = reg.get("documents", {}).get(job_id)
    if not doc_meta:
        return None

    # Ensure the RAG retriever is loaded from disk if not already in memory
    try:
        get_or_create_rag_retriever(job_id)
    except Exception:
        pass

    return {
        "job_id": job_id,
        "filename": doc_meta.get("filename", "document.pdf"),
        "page_count": doc_meta.get("page_count", 0),
        "overall_type": doc_meta.get("overall_type", "text-based"),
        "word_count": 0,
        "character_count": 0,
        "pages": [],
        "full_text": "",
        "deadline_info": {"has_deadline": False},
        "_reconstructed": True   # flag so caller knows this is a rebuilt stub
    }


@app.route('/api/result/<job_id>', methods=['GET'])
def get_job_result(job_id):
    """Returns final extraction payload when complete.
    Falls back to reconstructing from disk when JOBS dict is empty (server restart).
    """
    if job_id in JOBS:
        job = JOBS[job_id]
        if job["status"] == "completed" and job["result"]:
            return jsonify({"success": True, "data": job["result"]})
        elif job["status"] == "error":
            return jsonify({"success": False, "error": job.get("error", "Processing error occurred.")}), 400
        else:
            return jsonify({"success": False, "status": job["status"], "progress": job["progress"]}), 202

    # JOBS cache miss (server restarted) — try to reconstruct from DocumentManager + disk
    reconstructed = _reconstruct_result_from_disk(job_id)
    if reconstructed:
        return jsonify({"success": True, "data": reconstructed})

    return jsonify({"success": False, "error": "Job session not found. Please re-upload the document."}), 404


@app.route('/api/pdf/<job_id>', methods=['GET'])
def stream_pdf(job_id):
    """Streams the uploaded PDF for the frontend PDF preview renderer.
    Falls back to scanning uploads folder when JOBS dict is empty (server restart).
    """
    # 1. Try in-memory JOBS dict first
    if job_id in JOBS:
        pdf_path = JOBS[job_id]["pdf_path"]
        if os.path.exists(pdf_path):
            return send_file(pdf_path, mimetype='application/pdf')
        return jsonify({"error": "PDF file no longer exists."}), 404

    # 2. Server restart fallback: scan uploads folder for matching file
    upload_dir = str(config.UPLOAD_FOLDER)
    if os.path.isdir(upload_dir):
        for fname in os.listdir(upload_dir):
            if fname.startswith(job_id):
                full_path = os.path.join(upload_dir, fname)
                if os.path.exists(full_path):
                    return send_file(full_path, mimetype='application/pdf')

    return jsonify({"error": "PDF file not found. Please re-upload the document."}), 404

# ------------------------------------------------------------------------------
# RAG CHATBOT API ROUTES
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# RAG CHATBOT API ROUTE
# ------------------------------------------------------------------------------
@app.route('/api/chat', methods=['POST'])
def chat_with_document():
    """
    Standard RAG Chatbot Endpoint:
    Processes user questions against the active document using RAG retrieval,
    returning grounded natural language answers with page citations.
    """
    data = request.get_json() or {}
    question = data.get("question", "").strip()
    question_type = data.get("question_type")
    doc_id = (data.get("document_id") or DocumentManager.get_active_document_id() or "").strip()
    session_id = (data.get("session_id") or doc_id or "default").strip()

    if not question:
        return jsonify({"success": False, "error": "Question parameter is required."}), 400

    if not doc_id:
        return jsonify({"success": False, "error": "No active tender document is selected. Please select a document first."}), 400

    # Validate that document exists in registry, in-memory JOBS, or has a persisted FAISS vector index
    reg = DocumentManager._load_registry()
    doc_exists = (
        doc_id in reg.get("documents", {}) or
        doc_id in JOBS or
        os.path.exists(os.path.join(config.TEMP_FOLDER, "vector_stores", f"{doc_id}.faiss"))
    )
    if not doc_exists:
        return jsonify({
            "success": False,
            "error": "The selected document was not found or has expired. Please select a document from the sidebar or upload a new tender."
        }), 404

    # Keep backend active document state synchronized with the request
    DocumentManager.set_active_document(doc_id)

    try:
        retriever = get_or_create_rag_retriever(doc_id)
        summary_data = DocumentSummarizer.get_summary(doc_id)

        # Classify Intent before retrieval
        intent = question_type or LLMProvider.classify_question_type(question)

        search_query = ConversationMemory.reformulate_query(question, session_id)

        # Intent-specific top_k: Summary uses maximum chunks (18) to cover all sections; Equipment uses 10; others 6
        if intent == "TENDER_SUMMARY":
            top_k = 18
        elif intent == "EQUIPMENT_SPECIFICATIONS":
            top_k = 10
        else:
            top_k = 6
        retrieval_res = retriever.retrieve(search_query, top_k=top_k, intent=intent)

        # Detect Product Search / Equipment Links Intent
        from chat.product_search_handler import ProductSearchHandler
        if intent == "PRODUCT_SEARCH" or question_type == "equipment_links" or ProductSearchHandler.is_product_search_intent(question):
            prod_res = ProductSearchHandler.handle_product_search(
                question=question,
                doc_id=doc_id,
                retrieved_chunks=retrieval_res["chunks"],
                rag_retriever=retriever
            )
            ConversationMemory.add_user_message(question, session_id)
            ConversationMemory.add_assistant_message(prod_res["answer_text"], prod_res["citations"], session_id)

            return jsonify({
                "success": True,
                "document_id": doc_id,
                "is_doc_generation": False,
                "is_product_search_intent": True,
                "answer_text": prod_res["answer_text"],
                "answer_html": prod_res["answer_html"],
                "citations": prod_res["citations"],
                "provider": "tender_product_search",
                "question_type": "PRODUCT_SEARCH",
                "top_retrieval_score": retrieval_res.get("top_score", 0.0)
            })

        chat_history = ConversationMemory.get_history(session_id)
        response_data = LLMProvider.generate_rag_answer(
            question,
            retrieval_res["chunks"],
            chat_history=chat_history,
            summary_data=summary_data,
            question_type=intent
        )

        ConversationMemory.add_user_message(question, session_id)
        ConversationMemory.add_assistant_message(response_data["answer"], response_data["citations"], session_id)

        return jsonify({
            "success": True,
            "document_id": doc_id,
            "is_doc_generation": False,
            "is_product_search_intent": False,
            "answer_text": response_data["answer"],
            "answer_html": None,
            "citations": response_data["citations"],
            "provider": response_data["provider"],
            "question_type": response_data.get("question_type", "specific_question"),
            "top_retrieval_score": retrieval_res.get("top_score", 0.0)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": f"Processing error: {str(e)}"}), 500

@app.route('/api/documents', methods=['GET'])
def get_documents():
    """Returns list of uploaded documents and indexing state enriched with deadline info."""
    docs = DocumentManager.list_documents()
    for d in docs:
        d_id = d.get("document_id")
        if d_id:
            try:
                deadline = DeadlineDB.get_tender_deadline(d_id)
                if not deadline:
                    # On-the-fly auto-detection and persistence for any document missing from deadline DB
                    try:
                        retriever = RAG_INDEXES.get(d_id)
                        d_info = DeadlineExtractor.extract_from_document(d_id, rag_retriever=retriever)
                        if d_info.get("has_deadline"):
                            deadline = DeadlineDB.save_tender_deadline(
                                tender_id=d_id,
                                title=d_info.get("tender_title") or d.get("filename", "Tender"),
                                organization=d_info.get("organization") or "Not specified",
                                submission_deadline=d_info.get("submission_deadline"),
                                opening_datetime=d_info.get("opening_datetime"),
                                tz_name=d_info.get("timezone", DEFAULT_TIMEZONE),
                                source_page=d_info.get("submission_deadline_source_page", 1),
                                file_name=d.get("filename"),
                                reminder_config=None,
                                custom_reminders=[],
                                notification_channels=["in_app", "browser"],
                                detected_raw=d_info
                            )
                            print(f"[/api/documents] Auto-detected and saved deadline on-the-fly for '{d.get('filename')}' -> {deadline['display']['formatted']}")
                    except Exception as ext_err:
                        print(f"[/api/documents] On-the-fly extraction error for {d_id}: {ext_err}")

                if deadline:
                    d["deadline"] = {
                        "has_deadline": True,
                        "submission_deadline": deadline.get("submission_deadline"),
                        "display": deadline.get("display"),
                        "urgency": deadline.get("urgency"),
                        "urgency_text": deadline.get("urgency_text"),
                        "remaining_human": deadline.get("remaining_human"),
                        "is_expired": deadline.get("is_expired", False)
                    }
                else:
                    d["deadline"] = {"has_deadline": False}
            except Exception as e:
                d["deadline"] = {"has_deadline": False}
        else:
            d["deadline"] = {"has_deadline": False}

    return jsonify({"success": True, "documents": docs})

@app.route('/api/documents/select', methods=['POST'])
def select_document():
    """Sets active document for chatbot queries."""
    data = request.get_json() or {}
    doc_id = (data.get("document_id") or "").strip()
    if not doc_id:
        return jsonify({"success": False, "error": "Document ID is required."}), 400

    reg = DocumentManager._load_registry()
    doc_exists = (
        doc_id in reg.get("documents", {}) or
        doc_id in JOBS or
        os.path.exists(os.path.join(config.TEMP_FOLDER, "vector_stores", f"{doc_id}.faiss"))
    )
    if not doc_exists:
        return jsonify({"success": False, "error": f"Document '{doc_id}' not found."}), 404

    DocumentManager.set_active_document(doc_id)
    try:
        get_or_create_rag_retriever(doc_id)
    except Exception:
        pass

    return jsonify({"success": True, "active_document_id": doc_id})

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document_session(doc_id):
    """Deletes a single document session from registry and cache."""
    DocumentManager.delete_document(doc_id)
    JOBS.pop(doc_id, None)
    RAG_INDEXES.pop(doc_id, None)
    ConversationMemory.clear_session(doc_id)
    return jsonify({"success": True, "message": "Document session deleted."})

@app.route('/api/documents/clear_all', methods=['POST'])
def clear_all_document_sessions():
    """Clears all registered document sessions and caches."""
    reg = DocumentManager._load_registry()
    for d_id in list(reg.get("documents", {}).keys()):
        DocumentManager.delete_document(d_id)
        JOBS.pop(d_id, None)
        RAG_INDEXES.pop(d_id, None)
        ConversationMemory.clear_session(d_id)
    return jsonify({"success": True, "message": "All document sessions cleared."})

@app.route('/api/chat/clear', methods=['POST'])
def clear_chat():
    """Resets chatbot conversation memory."""
    data = request.get_json() or {}
    session_id = data.get("session_id", "default")
    ConversationMemory.clear_session(session_id)
    return jsonify({"success": True, "message": "Conversation history cleared."})

@app.route('/api/chat/history/<session_id>', methods=['GET'])
def get_chat_history(session_id):
    """Returns stored conversation history messages for session."""
    history = ConversationMemory.get_history(session_id)
    return jsonify({"success": True, "history": history})

@app.route('/api/settings', methods=['GET', 'POST'])
def manage_settings():
    """Gets or sets Groq API key and provider configuration."""
    if request.method == 'POST':
        data = request.get_json() or {}
        groq_key = data.get("groq_api_key", "").strip()
        if groq_key:
            os.environ["GROQ_API_KEY"] = groq_key
            env_path = os.path.join(config.BASE_DIR, ".env")
            try:
                with open(env_path, "w", encoding="utf-8") as f:
                    f.write(f"GROQ_API_KEY={groq_key}\nLLM_PROVIDER=groq\nLLM_MODEL=llama-3.3-70b-versatile\n")
            except Exception:
                pass
            return jsonify({
                "success": True,
                "provider": "groq",
                "message": "Groq API key saved! AI chatbot is now powered by Groq Llama 3.3 70B."
            })
        return jsonify({"success": False, "error": "Groq API key cannot be empty."}), 400

    return jsonify({
        "success": True,
        "provider": LLMProvider.get_provider_name(),
        "has_groq_key": bool(os.getenv("GROQ_API_KEY"))
    })

@app.route('/api/export/<format_type>', methods=['POST'])
def export_document(format_type):
    """Exports extracted result to .txt or .docx file."""
    data = request.get_json()
    if not data or "result" not in data:
        return jsonify({"success": False, "error": "Missing extraction data."}), 400

    result = data["result"]
    filename_base = secure_filename(data.get("filename", "extracted_document")).rsplit('.', 1)[0]

    if format_type == "txt":
        out_path = os.path.join(config.TEMP_FOLDER, f"{filename_base}_{uuid.uuid4().hex[:6]}.txt")
        DocumentExporter.generate_txt(result, out_path)
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{filename_base}_extracted.txt",
            mimetype="text/plain"
        )
    elif format_type == "docx":
        out_path = os.path.join(config.TEMP_FOLDER, f"{filename_base}_{uuid.uuid4().hex[:6]}.docx")
        DocumentExporter.generate_docx(result, out_path)
        return send_file(
            out_path,
            as_attachment=True,
            download_name=f"{filename_base}_extracted.docx",
            mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        return jsonify({"success": False, "error": "Unsupported export format."}), 400

@app.route('/api/clear/<job_id>', methods=['POST'])
def clear_job(job_id):
    """Deletes uploaded file, FAISS vector index, and job state."""
    DocumentManager.delete_document(job_id)
    if job_id in RAG_INDEXES:
        retriever = RAG_INDEXES.pop(job_id)
        if retriever and retriever.vector_store:
            retriever.vector_store.delete()

    if job_id in JOBS:
        job = JOBS.pop(job_id)
        if os.path.exists(job.get("pdf_path", "")):
            try:
                os.remove(job["pdf_path"])
            except Exception:
                pass
    return jsonify({"success": True, "message": "Job cleared safely."})

# ------------------------------------------------------------------------------
# PDF COMPRESSOR API ROUTES
# ------------------------------------------------------------------------------
@app.route('/api/compress/analyze', methods=['POST'])
def handle_pdf_analysis():
    if 'pdf_file' not in request.files:
        return jsonify({"success": False, "error": "No PDF file attached."}), 400

    file = request.files['pdf_file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({"success": False, "error": "Please attach a valid PDF file."}), 400

    comp_id = str(uuid.uuid4())[:8]
    safe_name = secure_filename(file.filename)
    input_path = os.path.join(config.TEMP_FOLDER, f"analyze_{comp_id}_{safe_name}")
    os.makedirs(config.TEMP_FOLDER, exist_ok=True)
    file.save(input_path)

    analysis = analyze_pdf(input_path)
    return jsonify({
        "success": True,
        "filename": safe_name,
        "analysis": analysis
    })

@app.route('/api/compress/process', methods=['POST'])
def handle_pdf_compression():

    if 'pdf_file' not in request.files:
        return jsonify({"success": False, "error": "No PDF file attached."}), 400

    file = request.files['pdf_file']
    mode = request.form.get("mode", "recommended")

    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({"success": False, "error": "Please attach a valid PDF file."}), 400

    comp_id = str(uuid.uuid4())[:8]
    safe_name = secure_filename(file.filename)
    input_path = os.path.join(config.TEMP_FOLDER, f"input_{comp_id}_{safe_name}")
    os.makedirs(config.TEMP_FOLDER, exist_ok=True)
    file.save(input_path)

    # Analyze document structure first
    analysis = analyze_pdf(input_path)

    # Process compression
    out_filename = f"Compressed_{comp_id}_{safe_name}"
    output_path = os.path.join(config.TEMP_FOLDER, out_filename)
    
    res = compress_pdf(input_path, output_path, mode=mode)
    
    return jsonify({
        "success": True,
        "filename": out_filename,
        "download_url": f"/api/compress/download/{out_filename}",
        "original_size": res["original_size"],
        "compressed_size": res["compressed_size"],
        "space_saved": res["space_saved"],
        "saved_percent": res["saved_percent"],
        "processing_time": res["processing_time"],
        "page_count": analysis["page_count"],
        "is_scanned": analysis["is_scanned"],
        "has_selectable_text": analysis["has_selectable_text"]
    })

@app.route('/api/compress/download/<filename>', methods=['GET'])
def download_compressed_pdf(filename):
    safe_name = secure_filename(filename)
    file_path = os.path.join(config.TEMP_FOLDER, safe_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Compressed file not found or expired."}), 404
    return send_file(file_path, as_attachment=True, download_name=safe_name, mimetype="application/pdf")

# ------------------------------------------------------------------------------
# PDF COMBINER API ROUTES
# ------------------------------------------------------------------------------
COMBINER_SESSIONS = {}

@app.route('/api/combiner/upload', methods=['POST'])
def upload_combiner_files():
    files = []
    for key in request.files.keys():
        files.extend(request.files.getlist(key))

    files = [f for f in files if f and f.filename]

    if not files:
        return jsonify({"success": False, "error": "No files uploaded."}), 400

    session_id = request.form.get("session_id") or str(uuid.uuid4())[:8]
    if session_id not in COMBINER_SESSIONS:
        COMBINER_SESSIONS[session_id] = []

    thumb_dir = os.path.join(config.TEMP_FOLDER, "thumbnails", session_id)
    os.makedirs(thumb_dir, exist_ok=True)

    new_pages = []
    errors = []

    for file in files:
        if not file or file.filename == '':
            continue
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ('.pdf', '.docx', '.doc', '.jpg', '.jpeg', '.png', '.webp', '.bmp'):
            errors.append(f"Unsupported format for '{file.filename}'. Allowed: PDF, DOCX, DOC, JPG, PNG, WEBP, BMP.")
            continue

        safe_name = secure_filename(file.filename) or f"file_{uuid.uuid4().hex[:6]}"
        unique_name = f"{uuid.uuid4().hex[:6]}_{safe_name}"
        saved_path = os.path.join(config.TEMP_FOLDER, unique_name)
        os.makedirs(config.TEMP_FOLDER, exist_ok=True)

        try:
            file.save(saved_path)
            pages = process_file_into_pages(saved_path, file.filename, thumb_dir)
            new_pages.extend(pages)
        except Exception as e:
            errors.append(str(e))
            if os.path.exists(saved_path):
                try:
                    os.remove(saved_path)
                except Exception:
                    pass

    COMBINER_SESSIONS[session_id].extend(new_pages)

    if not new_pages and errors:
        return jsonify({"success": False, "error": "\n".join(errors)}), 400

    return jsonify({
        "success": True,
        "session_id": session_id,
        "pages": COMBINER_SESSIONS[session_id],
        "new_pages": new_pages,
        "added_count": len(new_pages),
        "errors": errors
    })

@app.route('/api/combiner/clear', methods=['POST'])
def clear_combiner_session():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    if session_id and session_id in COMBINER_SESSIONS:
        COMBINER_SESSIONS.pop(session_id, None)
        thumb_dir = os.path.join(config.TEMP_FOLDER, "thumbnails", session_id)
        if os.path.exists(thumb_dir):
            import shutil
            try:
                shutil.rmtree(thumb_dir)
            except Exception:
                pass
    return jsonify({"success": True})

@app.route('/api/combiner/pages/<session_id>', methods=['GET'])
def get_combiner_pages(session_id):
    """Return the current page list for a combiner session (no upload needed)."""
    pages = COMBINER_SESSIONS.get(session_id, [])
    return jsonify({"success": True, "session_id": session_id, "pages": pages})

@app.route('/api/combiner/thumbnail/<session_id>/<filename>', methods=['GET'])
def get_combiner_thumbnail(session_id, filename):
    safe_session = secure_filename(session_id)
    safe_file = secure_filename(filename)
    thumb_path = os.path.join(config.TEMP_FOLDER, "thumbnails", safe_session, safe_file)
    if not os.path.exists(thumb_path):
        return jsonify({"error": "Thumbnail not found."}), 404
    return send_file(thumb_path, mimetype="image/jpeg")

@app.route('/api/combiner/generate', methods=['POST'])
def generate_combined_pdf():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    page_specs = data.get("page_specs") or []

    if not page_specs:
        return jsonify({"success": False, "error": "No pages selected for PDF combination."}), 400

    comb_id = str(uuid.uuid4())[:8]
    out_filename = f"Combined_{comb_id}.pdf"
    output_path = os.path.join(config.TEMP_FOLDER, out_filename)
    os.makedirs(config.TEMP_FOLDER, exist_ok=True)

    res = combine_pages_to_pdf(page_specs, output_path)

    return jsonify({
        "success": True,
        "filename": out_filename,
        "download_url": f"/api/combiner/download/{out_filename}",
        "total_pages": res["total_pages"],
        "file_size": res["file_size"],
        "processing_time": res["processing_time"]
    })

@app.route('/api/combiner/download/<filename>', methods=['GET'])
def download_combined_pdf(filename):
    safe_name = secure_filename(filename)
    file_path = os.path.join(config.TEMP_FOLDER, safe_name)
    if not os.path.exists(file_path):
        return jsonify({"error": "Combined file not found or expired."}), 404
    return send_file(file_path, as_attachment=True, download_name=safe_name, mimetype="application/pdf")

# --------------------------------------------------------------------------
# PRODUCT FINDER API ENDPOINTS
# --------------------------------------------------------------------------
from product_finder.service import ProductFinderService
product_finder_service = ProductFinderService()

@app.route('/api/product-finder/tender-equipment', methods=['GET'])
def get_tender_equipment():
    """Fetches detected equipment and specifications from active tender document."""
    doc_id = (request.args.get("document_id") or DocumentManager.get_active_document_id() or "").strip()
    if not doc_id:
        return jsonify({
            "success": False,
            "error": "No tender document is currently active. Please upload or select a tender document first."
        }), 400

    retriever = get_or_create_rag_retriever(doc_id)
    result = product_finder_service.get_tender_equipment(doc_id, rag_retriever=retriever)
    return jsonify(result)

@app.route('/api/product-finder/search', methods=['POST'])
def search_products():
    """Searches web for matching products using Gemini Search Grounding or Free Fallback."""
    data = request.get_json(silent=True) or {}
    item_name = data.get("item_name", "").strip()
    specifications = data.get("specifications", [])
    quantity = int(data.get("quantity", 1))
    force_refresh = bool(data.get("refresh", False))

    if not item_name:
        return jsonify({"success": False, "error": "Item name is required for product search."}), 400

    if isinstance(specifications, str):
        specifications = [s.strip() for s in specifications.split("\n") if s.strip()]

    result = product_finder_service.search_for_item(
        item_name=item_name,
        specifications=specifications,
        quantity=quantity,
        force_refresh=force_refresh
    )
    return jsonify(result)

@app.route('/api/product-finder/compare', methods=['POST'])
def compare_products():
    """Generates side-by-side comparison matrix for selected products."""
    data = request.get_json(silent=True) or {}
    required_specs = data.get("required_specs", [])
    products = data.get("products", [])

    if not products:
        return jsonify({"success": False, "error": "At least one product is required for comparison."}), 400

    result = product_finder_service.compare_products(required_specs, products)
    return jsonify({"success": True, "comparison": result})

# --------------------------------------------------------------------------
# TENDER DEADLINE REMINDER API ENDPOINTS
# --------------------------------------------------------------------------
@app.route('/api/deadlines/detect/<doc_id>', methods=['GET'])
def detect_document_deadline(doc_id):
    """Extracts tender submission deadline and metadata from document."""
    try:
        retriever = RAG_INDEXES.get(doc_id)
        result = DeadlineExtractor.extract_from_document(doc_id, rag_retriever=retriever)
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines/confirm', methods=['POST'])
def confirm_tender_deadline():
    """Confirms/saves a tender deadline, creates reminder schedules, and notifies user."""
    data = request.get_json(silent=True) or {}
    tender_id = data.get("tender_id") or str(uuid.uuid4())
    title = data.get("title", "").strip()
    organization = data.get("organization", "").strip()
    submission_deadline = data.get("submission_deadline", "").strip()
    opening_datetime = data.get("opening_datetime")
    tz_name = data.get("timezone", "Asia/Karachi")
    source_page = int(data.get("source_page", 1))
    reminder_config = data.get("reminder_config")
    custom_reminders = data.get("custom_reminders")
    notification_channels = data.get("notification_channels", ["in_app", "browser"])
    file_name = data.get("file_name")
    detected_raw = data.get("detected_raw", {})

    if not title:
        return jsonify({"success": False, "error": "Tender title is required."}), 400
    if not submission_deadline:
        return jsonify({"success": False, "error": "Submission deadline is required."}), 400

    try:
        tender = DeadlineDB.save_tender_deadline(
            tender_id=tender_id,
            title=title,
            organization=organization,
            submission_deadline=submission_deadline,
            tz_name=tz_name,
            file_name=file_name,
            opening_datetime=opening_datetime,
            source_page=source_page,
            reminder_config=reminder_config,
            custom_reminders=custom_reminders,
            notification_channels=notification_channels,
            detected_raw=detected_raw
        )

        # Emit an in-app confirmation notification
        DeadlineDB.create_notification(
            title="✓ Tender Deadline Confirmed",
            message=f'Reminder schedule active for "{title}" (Due: {tender["display"]["formatted"]}).',
            tender_id=tender_id,
            notif_type="success"
        )

        return jsonify({"success": True, "tender": tender})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines', methods=['GET'])
def list_tender_deadlines():
    """Lists all saved tender deadlines with filter, search, and sorting."""
    filter_status = request.args.get("filter", "all")
    search_query = request.args.get("search", "").strip() or None
    sort_by = request.args.get("sort", "nearest")

    try:
        tenders = DeadlineDB.list_tenders(
            filter_status=filter_status,
            search_query=search_query,
            sort_by=sort_by
        )
        return jsonify({"success": True, "tenders": tenders})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines/summary', methods=['GET'])
def get_deadlines_summary():
    """Returns dynamic KPI counts (Due Tomorrow, Due This Week, Upcoming, Expired)."""
    try:
        summary = DeadlineDB.get_summary_counts()
        return jsonify({"success": True, "summary": summary})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines/<tender_id>', methods=['GET'])
def get_single_tender_deadline(tender_id):
    """Retrieves a single tender deadline record and its scheduled reminders."""
    tender = DeadlineDB.get_tender_deadline(tender_id)
    if not tender:
        return jsonify({"success": False, "error": "Tender not found."}), 404
    return jsonify({"success": True, "tender": tender})

@app.route('/api/deadlines/<tender_id>', methods=['PUT'])
def update_tender_deadline(tender_id):
    """Updates deadline, recalculates reminder schedules, and cancels obsolete unsent reminders."""
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    organization = data.get("organization", "").strip()
    submission_deadline = data.get("submission_deadline", "").strip()
    opening_datetime = data.get("opening_datetime")
    tz_name = data.get("timezone", "Asia/Karachi")
    source_page = int(data.get("source_page", 1))
    reminder_config = data.get("reminder_config")
    custom_reminders = data.get("custom_reminders")
    notification_channels = data.get("notification_channels", ["in_app", "browser"])
    file_name = data.get("file_name")

    if not title or not submission_deadline:
        return jsonify({"success": False, "error": "Title and submission deadline are required."}), 400

    try:
        tender = DeadlineDB.save_tender_deadline(
            tender_id=tender_id,
            title=title,
            organization=organization,
            submission_deadline=submission_deadline,
            tz_name=tz_name,
            file_name=file_name,
            opening_datetime=opening_datetime,
            source_page=source_page,
            reminder_config=reminder_config,
            custom_reminders=custom_reminders,
            notification_channels=notification_channels
        )

        DeadlineDB.create_notification(
            title="✏️ Tender Deadline Updated",
            message=f'Deadline updated for "{title}" (New date: {tender["display"]["formatted"]}).',
            tender_id=tender_id,
            notif_type="info"
        )

        return jsonify({"success": True, "tender": tender})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines/all', methods=['DELETE', 'POST'])
def delete_all_tender_deadlines():
    """Deletes all tracked tender deadlines and scheduled reminders."""
    try:
        count = DeadlineDB.delete_all_tender_deadlines()
        return jsonify({"success": True, "message": f"Successfully deleted {count} deadlines and all scheduled reminders.", "deleted_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/deadlines/<tender_id>', methods=['DELETE'])
def delete_tender_deadline(tender_id):
    """Deletes tender deadline and reminder schedules without deleting the underlying document."""
    success = DeadlineDB.delete_tender_deadline(tender_id)
    if success:
        return jsonify({"success": True, "message": "Tender deadline and reminders removed."})
    return jsonify({"success": False, "error": "Tender not found."}), 404

@app.route('/api/deadlines/manual', methods=['POST'])
def create_manual_tender_deadline():
    """Manually registers an external tender deadline."""
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip()
    organization = data.get("organization", "").strip()
    submission_deadline = data.get("submission_deadline", "").strip()
    opening_datetime = data.get("opening_datetime")
    tz_name = data.get("timezone", "Asia/Karachi")
    reminder_config = data.get("reminder_config")
    custom_reminders = data.get("custom_reminders")
    notification_channels = data.get("notification_channels", ["in_app", "browser"])

    if not title:
        return jsonify({"success": False, "error": "Tender title is required."}), 400
    if not submission_deadline:
        return jsonify({"success": False, "error": "Submission deadline date and time are required."}), 400

    try:
        tender_id = f"manual_{uuid.uuid4().hex[:10]}"
        tender = DeadlineDB.save_tender_deadline(
            tender_id=tender_id,
            title=title,
            organization=organization,
            submission_deadline=submission_deadline,
            tz_name=tz_name,
            file_name="External / Manual Tender",
            opening_datetime=opening_datetime,
            source_page=1,
            reminder_config=reminder_config,
            custom_reminders=custom_reminders,
            notification_channels=notification_channels
        )

        DeadlineDB.create_notification(
            title="✓ Manual Tender Added",
            message=f'Manual deadline tracked for "{title}" (Due: {tender["display"]["formatted"]}).',
            tender_id=tender_id,
            notif_type="success"
        )

        return jsonify({"success": True, "tender": tender})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --------------------------------------------------------------------------
# NOTIFICATION API ENDPOINTS
# --------------------------------------------------------------------------
@app.route('/api/notifications', methods=['GET'])
def get_user_notifications():
    """Returns list of notifications and total unread count."""
    try:
        notifs = DeadlineDB.get_notifications(limit=50)
        unread = DeadlineDB.get_unread_notification_count()
        return jsonify({"success": True, "notifications": notifs, "unread_count": unread})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/notifications/mark-read', methods=['POST'])
def mark_notifications_read():
    """Marks specific notifications or all notifications as read."""
    data = request.get_json(silent=True) or {}
    notif_ids = data.get("notification_ids")
    try:
        DeadlineDB.mark_notifications_read(notif_ids)
        unread = DeadlineDB.get_unread_notification_count()
        return jsonify({"success": True, "unread_count": unread})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/notifications/clear', methods=['DELETE'])
def clear_all_notifications():
    """Clears notification history."""
    try:
        DeadlineDB.clear_notifications()
        return jsonify({"success": True, "message": "Notifications cleared."})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/notifications/poll', methods=['GET'])
def poll_notifications():
    """Fast lightweight polling endpoint for real-time header bell updates."""
    try:
        unread = DeadlineDB.get_unread_notification_count()
        return jsonify({"success": True, "unread_count": unread})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"success": False, "error": "File size exceeds the maximum limit."}), 413

# Start the background reminder scheduler
DeadlineScheduler.start(check_interval=20)

# Pre-warm the embedding model in background so first upload is instant
def _prewarm_embedding_model():
    try:
        EmbeddingGenerator.get_model()
        print("[Startup] Embedding model pre-warmed and ready.")
    except Exception as e:
        print(f"[Startup] Embedding pre-warm skipped: {e}")

_prewarm_thread = threading.Thread(target=_prewarm_embedding_model, daemon=True)
_prewarm_thread.start()

if __name__ == '__main__':
    print(f"Starting TenderMind AI server on http://{config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, use_reloader=False)
