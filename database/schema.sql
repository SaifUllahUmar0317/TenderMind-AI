-- =============================================================================
-- TenderMind AI — Neon PostgreSQL Database Schema
-- Matches all application screens & modules:
-- 1. Tender Assistant (Documents, Summaries, Equipment/BOQ, RAG Chat)
-- 2. Deadline Center (Tenders, Reminders, Notifications)
-- 3. PDF Tools (Compressor & Combiner execution history)
-- =============================================================================

-- Enable UUID extension if available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. DOCUMENTS TABLE (Screen 1: Document Library & Active Session)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(64) PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    page_count INTEGER NOT NULL DEFAULT 1,
    overall_type VARCHAR(50) DEFAULT 'digital', -- 'digital', 'scanned', 'mixed'
    status VARCHAR(50) DEFAULT 'indexing',       -- 'indexing', 'ready', 'failed'
    chunk_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT FALSE,
    file_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_active ON documents(is_active);

-- -----------------------------------------------------------------------------
-- 2. DOCUMENT SUMMARIES TABLE (Screen 1: AI Tender Analysis & Executive Overview)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS document_summaries (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tender_title TEXT,
    organization TEXT,
    executive_summary TEXT,
    hierarchical_summary JSONB DEFAULT '{}'::jsonb,
    section_summaries JSONB DEFAULT '[]'::jsonb,
    metadata_kv JSONB DEFAULT '[]'::jsonb,
    deadline_info JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_summaries_doc_id ON document_summaries(document_id);

-- -----------------------------------------------------------------------------
-- 3. EQUIPMENT ITEMS TABLE (Screen 1: Extracted BOQ / Equipment Specifications)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS equipment_items (
    id SERIAL PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    item_number VARCHAR(50),
    name TEXT NOT NULL,
    category VARCHAR(100) DEFAULT 'Main Equipment', -- 'Main Equipment', 'Installation & Accessories', etc.
    quantity VARCHAR(100),
    unit VARCHAR(50),
    specifications JSONB DEFAULT '[]'::jsonb,
    source_page INTEGER DEFAULT 1,
    raw_data JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_equipment_doc_id ON equipment_items(document_id);
CREATE INDEX IF NOT EXISTS idx_equipment_category ON equipment_items(category);

-- -----------------------------------------------------------------------------
-- 4. CHAT CONVERSATIONS TABLE (Screen 1: RAG Chat History & Citations)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_conversations (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    document_id VARCHAR(64) REFERENCES documents(id) ON DELETE SET NULL,
    role VARCHAR(20) NOT NULL, -- 'user', 'assistant'
    content TEXT NOT NULL,
    citations JSONB DEFAULT '[]'::jsonb,
    question_type VARCHAR(50), -- 'TENDER_SUMMARY', 'TENDER_DEADLINE', 'EQUIPMENT_SPECIFICATIONS', etc.
    provider VARCHAR(50) DEFAULT 'groq',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_chat_doc ON chat_conversations(document_id);
CREATE INDEX IF NOT EXISTS idx_chat_created ON chat_conversations(created_at ASC);

-- -----------------------------------------------------------------------------
-- 5. TENDERS TABLE (Screen 2: Deadline Center)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenders (
    id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) REFERENCES documents(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    organization TEXT DEFAULT 'Not specified',
    file_name TEXT,
    upload_date TEXT,
    submission_deadline TIMESTAMPTZ NOT NULL,
    submission_deadline_utc TIMESTAMPTZ NOT NULL,
    opening_datetime TIMESTAMPTZ,
    opening_datetime_utc TIMESTAMPTZ,
    timezone VARCHAR(50) DEFAULT 'Asia/Karachi',
    submission_deadline_source_page INTEGER DEFAULT 1,
    status VARCHAR(30) DEFAULT 'UPCOMING', -- 'UPCOMING', 'DUE_SOON', 'EXPIRED', 'COMPLETED'
    detected_raw JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tenders_deadline_utc ON tenders(submission_deadline_utc);
CREATE INDEX IF NOT EXISTS idx_tenders_status ON tenders(status);
CREATE INDEX IF NOT EXISTS idx_tenders_doc ON tenders(document_id);

-- -----------------------------------------------------------------------------
-- 6. REMINDERS TABLE (Screen 2: Scheduled Alerts)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reminders (
    id VARCHAR(64) PRIMARY KEY,
    tender_id VARCHAR(64) NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    reminder_time_utc TIMESTAMPTZ NOT NULL,
    reminder_offset VARCHAR(50) NOT NULL, -- '24h', '3d', '7d', etc.
    reminder_label TEXT NOT NULL,
    notification_type VARCHAR(30) DEFAULT 'in_app', -- 'in_app', 'email'
    sent BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(sent, reminder_time_utc);
CREATE INDEX IF NOT EXISTS idx_reminders_tender ON reminders(tender_id);

-- -----------------------------------------------------------------------------
-- 7. NOTIFICATIONS TABLE (Screen 2: In-App Alerts & Bell Counter)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(64) PRIMARY KEY,
    tender_id VARCHAR(64) REFERENCES tenders(id) ON DELETE CASCADE,
    reminder_id VARCHAR(64) REFERENCES reminders(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(30) DEFAULT 'info', -- 'info', 'warning', 'urgent'
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_tender ON notifications(tender_id);

-- -----------------------------------------------------------------------------
-- 8. PDF COMPRESSIONS TABLE (Screen 3: Compressor Logs)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pdf_compressions (
    id SERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    original_size BIGINT NOT NULL,
    compressed_size BIGINT NOT NULL,
    ratio_percent REAL NOT NULL,
    compression_mode VARCHAR(30) DEFAULT 'recommended',
    processing_time_seconds REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_compressions_created ON pdf_compressions(created_at DESC);

-- -----------------------------------------------------------------------------
-- 9. PDF COMBINER SESSIONS TABLE (Screen 4: Combiner Logs)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pdf_combiner_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL,
    output_filename TEXT NOT NULL,
    total_pages INTEGER NOT NULL,
    file_size BIGINT NOT NULL,
    processing_time_seconds REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_combiner_created ON pdf_combiner_sessions(created_at DESC);
