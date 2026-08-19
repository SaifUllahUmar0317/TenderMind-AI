import sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
import config
from services.text_extractor import TextExtractor
from rag.adapter import ExtractionAdapter
from rag.chunker import SemanticChunker
from rag.vector_store import VectorStore
from rag.embeddings import EmbeddingGenerator
from rag.keyword_search import BM25Search
from rag.retriever import HybridRetriever
from documents.summarizer import DocumentSummarizer
from llm.provider import LLMProvider

pdf_path = "uploads/2811823b-2a66-4fd4-895d-2f2de9c9fc60_tender2.pdf"
doc_id = "integration_test_t2"

# --- Extract & index the document ---
extracted = TextExtractor.extract_document_fast(pdf_path)
adapted = ExtractionAdapter.adapt_extraction_payload(extracted, doc_id, "tender2.pdf")
chunker = SemanticChunker(target_chunk_size=600, chunk_overlap=100)
chunks = chunker.create_chunks(adapted)
vstore = VectorStore(doc_id)
embeds = EmbeddingGenerator.embed_texts([c["text"] for c in chunks])
vstore.add_chunks(chunks, embeds)
bm25 = BM25Search()
bm25.index_chunks(chunks)
retriever = HybridRetriever(vstore, bm25)
summary_data = DocumentSummarizer.generate_hierarchical_summary(adapted)
summary_data["doc_id"] = doc_id

print("=== TEST 1: TENDER DEADLINE ===")
r = retriever.retrieve("what is the tender deadline?", top_k=6, intent="TENDER_DEADLINE")
answer1 = LLMProvider._call_offline_rag(r["chunks"], "what is the tender deadline?", summary_data, "TENDER_DEADLINE")
print(answer1)

print("\n=== TEST 2: EQUIPMENT SCHEDULE ===")
# Get structured_equipment from summary
from documents.equipment_parser import EquipmentScheduleParser
items = EquipmentScheduleParser.stitch_and_extract_items(extracted.get("pages", []))
summary_data["structured_equipment"] = items
answer2 = LLMProvider._call_offline_rag([], "extract equipment schedule", summary_data, "EQUIPMENT_SPECIFICATIONS")
print(answer2[:800])

print("\n=== TEST 3: TENDER SUMMARY ===")
r3 = retriever.retrieve("summarize tender requirements", top_k=18, intent="TENDER_SUMMARY")
answer3 = LLMProvider._call_offline_rag(r3["chunks"], "summarize tender requirements", summary_data, "TENDER_SUMMARY")
print(answer3)
