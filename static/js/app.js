/**
 * TenderMind AI — Swiss Editorial Enterprise Application Controller
 * 3 Core Features: Tender Assistant | PDF Compressor | PDF Combiner
 */

document.addEventListener('DOMContentLoaded', () => {
    // --------------------------------------------------------------------------
    // 1. GLOBAL STATE & HANDLES
    // --------------------------------------------------------------------------
    let activeDocumentId = null;    // Single Source of Truth for the active tender document
    let currentJobId = null;        // Synchronized alias for activeDocumentId
    let activeChatSessionId = null; // Synchronized alias for activeDocumentId
    let currentPdfDoc = null;
    let currentPdfPage = 1;
    let pdfZoomScale = 1.0;

    let activeTab = 'assistant';
    let activityHistory = [];

    // Chat history sessions (ChatGPT-style)
    let chatSessions = [];

    /**
     * Unified State Mutator:
     * Sets the active document ID across all handles and synchronizes with backend.
     */
    function setActiveDocument(docId) {
        if (!docId) return;
        activeDocumentId = docId;
        currentJobId = docId;
        activeChatSessionId = docId;

        // Synchronize backend active document state
        fetch('/api/documents/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ document_id: docId })
        }).catch(() => {});
    }

    // PDF Combiner State
    let combinerSessionId = null;
    let combinerPages = []; // [{ page_id, file_path, file_name, is_image, source_page_idx, page_num, thumbnail_filename, rotation }]
    let draggedPageIndex = null;
    let combinerInsertTargetIndex = null;

    // DOM Handles
    const themeToggleBtn = document.getElementById('themeToggleBtn');
    const themeIcon = document.getElementById('themeIcon');
    const brandHomeBtn = document.getElementById('brandHomeBtn');

    // Navigation & Views
    const navLinks = document.querySelectorAll('.nav-link');
    const viewSections = document.querySelectorAll('.view-section');

    // Assistant Upload & Stepper
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const browseBtn = document.getElementById('browseBtn');
    const heroUploadBtn = document.getElementById('heroUploadBtn');
    const newExtractBtn = document.getElementById('newExtractBtn');

    const processingState = document.getElementById('processingState');
    const fileName = document.getElementById('fileName');
    const fileSize = document.getElementById('fileSize');
    const progressBar = document.getElementById('progressBar');
    const progressStatusText = document.getElementById('progressStatusText');
    const progressPercent = document.getElementById('progressPercent');


    // PDF Controls
    const prevPageBtn = document.getElementById('prevPageBtn');
    const nextPageBtn = document.getElementById('nextPageBtn');
    const pageNumberInput = document.getElementById('pageNumberInput');
    const pageCountSpan = document.getElementById('pageCountSpan');
    const zoomInBtn = document.getElementById('zoomInBtn');
    const zoomOutBtn = document.getElementById('zoomOutBtn');
    const zoomPercentSpan = document.getElementById('zoomPercentSpan');

    // Workspace & Chat
    const activeDocTitle = document.getElementById('activeDocTitle');
    const chatFeed = document.getElementById('chatFeed');
    const chatForm = document.getElementById('chatForm');
    const chatInput = document.getElementById('chatInput');
    const clearChatBtn = document.getElementById('clearChatBtn');
    const errorAlert = document.getElementById('errorAlert');
    const errorMessage = document.getElementById('errorMessage');
    const closeAlertBtn = document.getElementById('closeAlertBtn');

    // Global Search Modal
    const searchTriggerBtn = document.getElementById('searchTriggerBtn');
    const searchModal = document.getElementById('searchModal');
    const searchInput = document.getElementById('searchInput');

    // PDF Compressor Handles
    const compressorDropZone = document.getElementById('compressorDropZone');
    const compressorFileInput = document.getElementById('compressorFileInput');
    const compressorBrowseBtn = document.getElementById('compressorBrowseBtn');
    const compressorSettingsBox = document.getElementById('compressorSettingsBox');
    const startCompressBtn = document.getElementById('startCompressBtn');
    const compressorResultCard = document.getElementById('compressorResultCard');
    const resetCompressorBtn = document.getElementById('resetCompressorBtn');
    let selectedCompressFile = null;

    // PDF Combiner Handles
    const combinerFileInput = document.getElementById('combinerFileInput');
    const combinerAddBtn = document.getElementById('combinerAddBtn');
    const combinerDropZone = document.getElementById('combinerDropZone');
    const combinerControlsBar = document.querySelector('.combiner-controls-bar');
    const combinerCanvas = document.getElementById('combinerCanvas');
    const pageThumbnailsGrid = document.getElementById('pageThumbnailsGrid');
    const combinerStatsText = document.getElementById('combinerStatsText');
    const generateCombinedPdfBtn = document.getElementById('generateCombinedPdfBtn');
    const clearCombinerBtn = document.getElementById('clearCombinerBtn');
    const combinerResultCard = document.getElementById('combinerResultCard');
    const combinerProgressBox = document.getElementById('combinerProgressBox');
    const combinerProgressTitle = document.getElementById('combinerProgressTitle');
    const combinerProgressBar = document.getElementById('combinerProgressBar');
    const combinerProgressStatusText = document.getElementById('combinerProgressStatusText');
    const combinerProgressPercent = document.getElementById('combinerProgressPercent');
    const cancelCombinerBtn = document.getElementById('cancelCombinerBtn');
    
    let isCombinerUploading = false;
    let combinerCancelRequested = false;

    // --------------------------------------------------------------------------
    // 2. INITIALIZATION
    // --------------------------------------------------------------------------
    initTheme();
    initNavigation();
    initChatHistorySidebar();
    initRecentSessionsMenu();
    initResizers();
    initCompressorUI();
    initCombinerUI();
    initDeadlineCenter();
    initNotificationsSystem();
    initDeadlineModals();
    startDeadlineCountdownTicker();
    loadDocumentsLibrary();

    function initTheme() {
        const savedTheme = localStorage.getItem('tenderly_theme') || 'light';
        document.documentElement.setAttribute('data-theme', savedTheme);
        updateThemeIcon(savedTheme);

        if (themeToggleBtn) {
            themeToggleBtn.addEventListener('click', () => {
                const current = document.documentElement.getAttribute('data-theme');
                const newTheme = current === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', newTheme);
                localStorage.setItem('tenderly_theme', newTheme);
                updateThemeIcon(newTheme);
            });
        }
    }

    function updateThemeIcon(theme) {
        if (!themeIcon) return;
        themeIcon.setAttribute('data-lucide', theme === 'dark' ? 'sun' : 'moon');
        if (window.lucide) lucide.createIcons();
    }

    // --------------------------------------------------------------------------
    // 3. NAVIGATION CONTROLLER
    // --------------------------------------------------------------------------
    function initNavigation() {
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                const tab = link.dataset.tab;
                if (tab) switchTab(tab);
            });
        });

        if (brandHomeBtn) {
            brandHomeBtn.addEventListener('click', () => switchTab('assistant'));
        }
    }

    function initChatHistorySidebar() {
        const toggleBtn = document.getElementById('toggleChatHistoryBtn');
        const sidebar = document.getElementById('chatHistorySidebar');
        const newChatBtn = document.getElementById('newChatBtn');

        if (toggleBtn && sidebar) {
            toggleBtn.addEventListener('click', () => {
                sidebar.classList.toggle('collapsed');
            });
        }

        if (newChatBtn) {
            newChatBtn.addEventListener('click', () => {
                startNewChatSession();
            });
        }
    }

    function switchTab(tabName) {
        activeTab = tabName;

        navLinks.forEach(link => {
            if (link.dataset.tab === tabName) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });

        viewSections.forEach(section => {
            if (section.id === `${tabName}View`) {
                section.classList.add('active');
                section.classList.remove('hidden');
            } else {
                section.classList.remove('active');
                section.classList.add('hidden');
            }
        });

        // Manage Recent Sessions sidebar visibility based on active view
        const sidebar = document.getElementById('heroRecentSidebar');
        if (sidebar) {
            if (tabName === 'assistant') {
                const savedState = localStorage.getItem('tendermind_sidebar_collapsed');
                if (savedState === 'true') {
                    sidebar.classList.remove('sidebar-hidden');
                    sidebar.classList.add('sidebar-collapsed');
                } else {
                    sidebar.classList.remove('sidebar-hidden', 'sidebar-collapsed');
                }
            } else {
                // Compressor, Combiner, Deadlines, Workspace take full width
                sidebar.classList.add('sidebar-hidden');
            }
        }

        // Trigger Deadline Center data refresh when navigated to
        if (tabName === 'deadlines') {
            loadDeadlines();
            loadDeadlinesSummary();
        }

        // Show floating scroll buttons ONLY on combiner tab (and only when pages are loaded)
        const floatScroll = document.getElementById('combinerFloatScroll');
        if (floatScroll) {
            if (tabName === 'combiner' && combinerPages && combinerPages.length > 0) {
                floatScroll.classList.remove('hidden');
            } else {
                floatScroll.classList.add('hidden');
            }
        }
    }

    // --------------------------------------------------------------------------
    // 5. TENDER ASSISTANT (RAG CHATBOT & UPLOAD)
    // --------------------------------------------------------------------------
    const uploadBtns = [browseBtn, heroUploadBtn, newExtractBtn];
    uploadBtns.forEach(btn => {
        if (btn) {
            btn.addEventListener('click', () => {
                if (fileInput) fileInput.click();
            });
        }
    });

    if (fileInput) {
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) processFileUpload(e.target.files[0]);
        });
    }

    if (dropZone) {
        dropZone.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON' && !e.target.closest('button')) {
                if (fileInput) fileInput.click();
            }
        });
        ['dragenter', 'dragover'].forEach(name => {
            dropZone.addEventListener(name, (e) => {
                e.preventDefault();
                dropZone.classList.add('dragover');
            });
        });
        ['dragleave', 'drop'].forEach(name => {
            dropZone.addEventListener(name, (e) => {
                e.preventDefault();
                dropZone.classList.remove('dragover');
            });
        });
        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) processFileUpload(files[0]);
        });
    }

    function processFileUpload(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showError('Invalid file type. Only PDF documents (.pdf) are supported.');
            return;
        }

        hideError();
        isExtracting = true;

        if (fileName) fileName.textContent = file.name;
        if (fileSize) fileSize.textContent = formatBytes(file.size);
        if (processingState) processingState.classList.remove('hidden');

        showGlobeLoader('Processing Tender Document...', file.name);

        updateStepStatus('stepUpload', 'active');
        updateProgress(5, 'Preparing document analyzer...');

        const formData = new FormData();
        formData.append('pdf_file', file);

        fetch('/api/upload', {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                setActiveDocument(data.job_id);
                
                updateStepStatus('stepUpload', 'complete');
                updateStepStatus('stepStructure', 'active');
                pollJobStatus(data.job_id);
            } else {
                showError(data.error || 'Failed to upload document.');
                resetProcessingState();
            }
        })
        .catch(() => {
            showError('Network error uploading file. Please try again.');
            resetProcessingState();
        });
    }

    function pollJobStatus(jobId) {
        const interval = setInterval(() => {
            fetch(`/api/status/${jobId}`)
                .then(res => res.json())
                .then(data => {
                    if (!data.success) {
                        clearInterval(interval);
                        showError(data.error || 'Error during extraction.');
                        resetProcessingState();
                        return;
                    }

                    updateProgress(data.progress, data.logs[data.logs.length - 1] || 'Processing document...');

                    if (data.progress >= 30) {
                        updateStepStatus('stepStructure', 'complete');
                        updateStepStatus('stepRequirements', 'active');
                    }
                    if (data.progress >= 70) {
                        updateStepStatus('stepRequirements', 'complete');
                        updateStepStatus('stepIndexing', 'active');
                    }

                    if (data.status === 'completed') {
                        clearInterval(interval);
                        updateStepStatus('stepIndexing', 'complete');
                        updateProgress(100, 'Processing & indexing complete!');
                        setTimeout(() => fetchJobResult(jobId, 0), 200);
                    } else if (data.status === 'error') {
                        clearInterval(interval);
                        showError(data.error || 'Extraction failed.');
                        resetProcessingState();
                    }
                })
                .catch(() => {
                    clearInterval(interval);
                    showError('Connection lost while polling job status.');
                    resetProcessingState();
                });
        }, 400);
    }

    function fetchJobResult(jobId, attempt) {
        if (attempt === undefined) attempt = 0;
        const MAX_ATTEMPTS = 20;
        const RETRY_DELAYS = [800, 1000, 1500, 2000, 2500, 3000, 3000, 3000, 3000, 3000, 4000, 4000, 4000, 5000, 5000, 5000, 5000, 5000, 5000, 5000];

        fetch(`/api/result/${jobId}`)
            .then(res => {
                // HTTP 202 = still processing (job not ready yet) — retry
                if (res.status === 202) {
                    if (attempt < MAX_ATTEMPTS) {
                        updateProgress(100, `Finalizing workspace${'.'.repeat((attempt % 3) + 1)}`);
                        setTimeout(() => fetchJobResult(jobId, attempt + 1), RETRY_DELAYS[attempt] || 5000);
                    } else {
                        hideGlobeLoader();
                        showError('Processing is taking longer than expected. Please refresh or re-upload.');
                        resetProcessingState();
                    }
                    return;
                }
                return res.json();
            })
            .then(data => {
                if (!data) return; // 202 case — already handled above
                hideGlobeLoader();
                if (data.success) {
                    enterWorkspace(data.data);
                    // Check if structured deadline was already saved synchronously
                    if (data.data && data.data.deadline_saved) {
                        setTimeout(() => showToast('\u2713 Deadline extracted & reminders scheduled (3d & 1d before)'), 1500);
                    }
                    loadDocumentsLibrary();
                    loadDeadlines();
                    loadDeadlinesSummary();
                    pollNotifications();
                    // Delayed refreshes: background deadline thread may still be running (5-15s).
                    // Re-check at 8s and 18s so sidebar badge & Deadline Center update automatically.
                    setTimeout(() => {
                        loadDocumentsLibrary();
                        loadDeadlines();
                        loadDeadlinesSummary();
                    }, 8000);
                    setTimeout(() => {
                        loadDocumentsLibrary();
                        loadDeadlines();
                        loadDeadlinesSummary();
                        // Show deadline toast if now detected
                        const result = data.data;
                        if (result && !result.deadline_saved) {
                            fetch(`/api/result/${result.job_id}`)
                                .then(r => r.ok ? r.json() : null)
                                .then(d => {
                                    if (d && d.success && d.data && d.data.deadline_saved) {
                                        showToast('\u2713 Deadline extracted & reminders scheduled (3d & 1d before)');
                                    }
                                }).catch(() => {});
                        }
                    }, 18000);
                } else if (data.status === 'processing' || data.progress != null) {
                    // Backend says still processing — retry
                    if (attempt < MAX_ATTEMPTS) {
                        updateProgress(data.progress || 99, 'Almost there...');
                        setTimeout(() => fetchJobResult(jobId, attempt + 1), RETRY_DELAYS[attempt] || 5000);
                    } else {
                        showError('Processing timed out. Please re-upload the document.');
                        resetProcessingState();
                    }
                } else {
                    showError(data.error || 'Failed to retrieve result.');
                    resetProcessingState();
                }
            })
            .catch(() => {
                if (attempt < 5) {
                    // Network blip — retry a few times
                    setTimeout(() => fetchJobResult(jobId, attempt + 1), RETRY_DELAYS[attempt] || 3000);
                } else {
                    hideGlobeLoader();
                    resetProcessingState();
                }
            });
    }

    function updateStepStatus(stepId, state) {
        const el = document.getElementById(stepId);
        if (el) el.className = `proc-step ${state}`;
    }

    function updateProgress(pct, statusText) {
        if (progressBar) progressBar.style.width = `${pct}%`;
        if (progressPercent) progressPercent.textContent = `${pct}%`;
        if (progressStatusText) progressStatusText.textContent = statusText;
        updateGlobeLoader(pct, statusText);
    }

    function resetProcessingState() {
        isExtracting = false;
        if (processingState) processingState.classList.add('hidden');
        if (progressBar) progressBar.style.width = '0%';
        hideGlobeLoader();
    }

    function enterWorkspace(result) {
        switchTab('workspace');

        const docId = result.job_id || result.document_id;
        setActiveDocument(docId);

        if (activeDocTitle) activeDocTitle.textContent = `${result.filename} (${result.page_count} pages)`;

        // Register / activate chat session
        const exists = chatSessions.find(s => s.id === docId);
        if (!exists) {
            chatSessions.unshift({
                id: docId,
                title: result.filename,
                pages: result.page_count,
                time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            });
        }
        renderChatHistorySidebar();
        loadPdfViewer(`/api/pdf/${docId}`);

        // Fetch stored chat history so user can continue conversation from exact last step
        fetch(`/api/chat/history/${docId}`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.history && data.history.length > 0) {
                    if (!chatFeed) return;
                    chatFeed.innerHTML = '';
                    data.history.forEach(msg => {
                        if (msg.role === 'user') {
                            appendUserMessage(msg.content);
                        } else if (msg.role === 'assistant') {
                            appendAssistantMessage(msg.content, msg.citations || []);
                        }
                    });
                } else {
                    if (chatFeed) {
                        chatFeed.innerHTML = `
                            <div class="chat-welcome-block">
                                <div class="welcome-label">01 / DOCUMENT ANALYST</div>
                                <h3>Tender document ready for analysis.</h3>
                                <p>I have processed <strong>${escapeHtml(result.filename)}</strong> (${result.page_count} pages). Ask technical questions or select a quick query below to extract key requirements and equipment schedules.</p>
                                
                                <div class="quick-prompts-list">
                                    <button class="quick-prompt-item primary-item" onclick="sendQuickQuery('Summarize tender requirements and submission deadlines.', 'summary')">
                                        ➔ Summarize Tender Requirements &amp; Deadlines
                                    </button>
                                    <button class="quick-prompt-item" onclick="sendQuickQuery('what is the tender deadline for this tender?', 'deadline')">
                                        ➔ What is the tender deadline for this tender?
                                    </button>
                                    <button class="quick-prompt-item" onclick="sendQuickQuery('what is the earnest money, call deposit or bid security?', 'bid_security')">
                                        ➔ What is the earnest money, call deposit or bid security?
                                    </button>
                                    <button class="quick-prompt-item" onclick="sendQuickQuery('List all equipment items, quantities, and technical specifications.', 'equipment_specs')">
                                        ➔ Extract Equipment Schedule &amp; Specifications
                                    </button>
                                    <button class="quick-prompt-item" onclick="sendQuickQuery('Give me the official links for all the equipments in this tender document.', 'equipment_links')">
                                        ➔ Official Links for all Equipments
                                    </button>
                                </div>
                            </div>
                        `;
                    }
                }
            })
            .catch(() => {
                if (chatFeed) {
                    chatFeed.innerHTML = `
                        <div class="chat-welcome-block">
                            <div class="welcome-label">01 / DOCUMENT ANALYST</div>
                            <h3>Tender document ready for analysis.</h3>
                            <p>I have processed <strong>${escapeHtml(result.filename)}</strong> (${result.page_count} pages).</p>
                            <div class="quick-prompts-list">
                                <button class="quick-prompt-item primary-item" onclick="sendQuickQuery('Summarize tender requirements and submission deadlines.', 'summary')">
                                    ➔ Summarize Tender Requirements &amp; Deadlines
                                </button>
                                <button class="quick-prompt-item" onclick="sendQuickQuery('what is the tender deadline for this tender?', 'deadline')">
                                    ➔ What is the tender deadline for this tender?
                                </button>
                                <button class="quick-prompt-item" onclick="sendQuickQuery('what is the earnest money, call deposit or bid security?', 'bid_security')">
                                    ➔ What is the earnest money, call deposit or bid security?
                                </button>
                                <button class="quick-prompt-item" onclick="sendQuickQuery('List all equipment items, quantities, and technical specifications.', 'equipment_specs')">
                                    ➔ Extract Equipment Schedule &amp; Specifications
                                </button>
                                <button class="quick-prompt-item" onclick="sendQuickQuery('Give me the official links for all the equipments in this tender document.', 'equipment_links')">
                                    ➔ Official Links for all Equipments
                                </button>
                            </div>
                        </div>
                    `;
                }
            });
    }

    function renderChatHistorySidebar() {
        const list = document.getElementById('chatHistoryList');
        if (!list) return;

        if (chatSessions.length === 0) {
            list.innerHTML = `<div class="chat-history-empty">No conversations yet.<br>Upload a tender to start.</div>`;
            return;
        }

        const curActiveId = activeDocumentId || currentJobId || activeChatSessionId;

        list.innerHTML = chatSessions.map(session => `
            <div class="chat-history-item ${session.id === curActiveId ? 'active-chat' : ''}"
                 onclick="selectChatSession('${session.id}')">
                <i data-lucide="message-square"></i>
                <div style="overflow: hidden; min-width: 0;">
                    <div style="font-size: 0.78rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(session.title)}</div>
                    <div style="font-size: 0.68rem; opacity: 0.5;">${session.pages} pages · ${session.time}</div>
                </div>
            </div>
        `).join('');
        if (window.lucide) lucide.createIcons();
    }

    window.selectChatSession = function(sessionId) {
        if (!sessionId) return;
        setActiveDocument(sessionId);
        renderChatHistorySidebar();
        showGlobeLoader('Loading session...', '');
        fetch(`/api/result/${sessionId}`)
            .then(res => res.json())
            .then(r => {
                hideGlobeLoader();
                if (r.success) {
                    enterWorkspace(r.data);
                    loadDocumentsLibrary();
                } else {
                    showError(r.error || 'Could not load session. The document may need to be re-uploaded.');
                }
            })
            .catch(() => {
                hideGlobeLoader();
                showError('Network error loading session. Please try again.');
            });
    };

    function startNewChatSession() {
        // Go back to assistant view for new upload
        switchTab('assistant');
        navLinks.forEach(link => {
            link.classList.toggle('active', link.dataset.tab === 'assistant');
        });
    }

    function loadPdfViewer(url) {
        if (typeof pdfjsLib === 'undefined') return;

        pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';

        pdfjsLib.getDocument(url).promise.then(pdf => {
            currentPdfDoc = pdf;
            currentPdfPage = 1;
            if (pageCountSpan) pageCountSpan.textContent = pdf.numPages;
            if (pageNumberInput) pageNumberInput.max = pdf.numPages;
            renderPdfPage(currentPdfPage);
        }).catch(() => {});
    }

    function renderPdfPage(num) {
        if (!currentPdfDoc) return;
        currentPdfDoc.getPage(num).then(page => {
            const canvas = document.getElementById('pdfRenderCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const viewport = page.getViewport({ scale: pdfZoomScale });

            canvas.height = viewport.height;
            canvas.width = viewport.width;

            page.render({
                canvasContext: ctx,
                viewport: viewport
            });

            if (pageNumberInput) pageNumberInput.value = num;
        });
    }

    if (prevPageBtn) prevPageBtn.addEventListener('click', () => { if (currentPdfPage > 1) renderPdfPage(--currentPdfPage); });
    if (nextPageBtn) nextPageBtn.addEventListener('click', () => { if (currentPdfDoc && currentPdfPage < currentPdfDoc.numPages) renderPdfPage(++currentPdfPage); });
    if (pageNumberInput) pageNumberInput.addEventListener('change', (e) => {
        const val = parseInt(e.target.value) || 1;
        if (currentPdfDoc && val >= 1 && val <= currentPdfDoc.numPages) renderPdfPage(currentPdfPage = val);
    });

    if (zoomInBtn) zoomInBtn.addEventListener('click', () => {
        pdfZoomScale = Math.min(pdfZoomScale + 0.2, 2.5);
        if (zoomPercentSpan) zoomPercentSpan.textContent = `${Math.round(pdfZoomScale * 100)}%`;
        renderPdfPage(currentPdfPage);
    });

    if (zoomOutBtn) zoomOutBtn.addEventListener('click', () => {
        pdfZoomScale = Math.max(pdfZoomScale - 0.2, 0.6);
        if (zoomPercentSpan) zoomPercentSpan.textContent = `${Math.round(pdfZoomScale * 100)}%`;
        renderPdfPage(currentPdfPage);
    });

    function autoResizeChatInput() {
        if (!chatInput) return;
        chatInput.style.height = 'auto';
        const scrollH = chatInput.scrollHeight;
        const newH = Math.max(24, Math.min(scrollH, 200));
        chatInput.style.height = `${newH}px`;
        if (scrollH > 200) {
            chatInput.style.overflowY = 'auto';
        } else {
            chatInput.style.overflowY = 'hidden';
        }
    }

    if (chatInput) {
        chatInput.addEventListener('input', autoResizeChatInput);
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                if (e.shiftKey) {
                    // Shift + Enter: Allow new line and auto-expand height
                    setTimeout(autoResizeChatInput, 0);
                } else {
                    // Enter alone: Submit message
                    e.preventDefault();
                    if (chatForm) {
                        if (chatForm.requestSubmit) {
                            chatForm.requestSubmit();
                        } else {
                            chatForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                        }
                    }
                }
            }
        });
    }

    if (chatForm) {
        chatForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const text = chatInput.value.trim();
            if (text) {
                sendChatMessage(text);
                chatInput.value = '';
                autoResizeChatInput();
            }
        });
    }

    window.sendQuickQuery = function(query, questionType = null) {
        sendChatMessage(query, questionType);
    };

    function sendChatMessage(question, questionType = null) {
        if (!question) return;

        const docId = activeDocumentId || currentJobId || activeChatSessionId;
        if (!docId) {
            showError('No active tender document is selected. Please select or upload a document first.');
            return;
        }

        appendUserMessage(question);
        const loadingId = appendLoadingMessage();

        const payload = {
            question: question,
            document_id: docId,
            session_id: docId
        };
        if (questionType) {
            payload.question_type = questionType;
        }

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            removeLoadingMessage(loadingId);
            if (data.success) {
                appendAssistantMessage(data.answer_text, data.citations, data.answer_html);
            } else {
                showError(data.error || 'Failed to generate answer.');
            }
        })
        .catch(() => {
            removeLoadingMessage(loadingId);
            showError('Network error connecting to assistant.');
        });
    }

    function appendUserMessage(text) {
        const div = document.createElement('div');
        div.className = 'chat-message user-message';
        div.innerHTML = `<div class="message-bubble">${escapeHtml(text)}</div>`;
        chatFeed.appendChild(div);
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }

    function appendAssistantMessage(rawText, citations = [], rawHtml = null) {
        const div = document.createElement('div');
        div.className = 'chat-message assistant-message';

        // Only bypass Markdown parsing if this is a specialized rich HTML card response (e.g. Product Finder)
        if (rawHtml && (rawHtml.includes('chat-product-card') || rawHtml.includes('chat-product-search-response'))) {
            div.innerHTML = `<div class="message-bubble">${rawHtml}</div>`;
        } else {
            const contentToRender = rawText || rawHtml || '';
            const safeMarkdown = renderMarkdownSafely(contentToRender);
            div.innerHTML = `<div class="message-bubble">${safeMarkdown}</div>`;
        }
        chatFeed.appendChild(div);

        div.querySelectorAll('.citation-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const pageNum = parseInt(btn.dataset.page, 10);
                if (pageNum) renderPdfPage(pageNum);
            });
        });

        if (window.lucide) lucide.createIcons();
        chatFeed.scrollTop = chatFeed.scrollHeight;
    }

    function appendLoadingMessage() {
        const id = 'msg_' + Date.now();
        const div = document.createElement('div');
        div.id = id;
        div.className = 'chat-message assistant-message';
        div.innerHTML = `<div class="message-bubble" style="color: var(--text-muted);">Analyzing tender document...</div>`;
        chatFeed.appendChild(div);
        chatFeed.scrollTop = chatFeed.scrollHeight;
        return id;
    }

    function removeLoadingMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    if (clearChatBtn) {
        clearChatBtn.addEventListener('click', () => {
            const docId = activeDocumentId || currentJobId || activeChatSessionId;
            if (!docId) return;
            fetch('/api/chat/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: docId })
            })
            .then(() => {
                if (chatFeed) chatFeed.innerHTML = '';
                showToast('Chat history cleared.');
            });
        });
    }

    // --------------------------------------------------------------------------
    // 6. FEATURE 2: PDF COMPRESSOR CONTROLLER
    // --------------------------------------------------------------------------
    function initCompressorUI() {
        if (compressorBrowseBtn) compressorBrowseBtn.addEventListener('click', () => compressorFileInput.click());

        if (compressorFileInput) {
            compressorFileInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) setupCompressorFile(e.target.files[0]);
            });
        }

        if (compressorDropZone) {
            compressorDropZone.addEventListener('click', (e) => {
                if (e.target.tagName !== 'BUTTON' && !e.target.closest('button')) {
                    if (compressorFileInput) compressorFileInput.click();
                }
            });
            ['dragenter', 'dragover'].forEach(name => {
                compressorDropZone.addEventListener(name, (e) => {
                    e.preventDefault();
                    compressorDropZone.classList.add('dragover');
                });
            });
            ['dragleave', 'drop'].forEach(name => {
                compressorDropZone.addEventListener(name, (e) => {
                    e.preventDefault();
                    compressorDropZone.classList.remove('dragover');
                });
            });
            compressorDropZone.addEventListener('drop', (e) => {
                const files = e.dataTransfer.files;
                if (files.length > 0) setupCompressorFile(files[0]);
            });
        }

        // Mode cards selection toggle
        document.querySelectorAll('.mode-card').forEach(card => {
            card.addEventListener('click', () => {
                document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('active'));
                card.classList.add('active');
                const radio = card.querySelector('input[type="radio"]');
                if (radio) radio.checked = true;
            });
        });

        if (startCompressBtn) {
            startCompressBtn.addEventListener('click', () => {
                if (!selectedCompressFile) return;
                const modeRadio = document.querySelector('input[name="compMode"]:checked');
                const mode = modeRadio ? modeRadio.value : 'recommended';

                startCompressBtn.disabled = true;
                startCompressBtn.textContent = 'COMPRESSING PDF...';
                showGlobeLoader('Compressing PDF...', selectedCompressFile.name);

                // Phase weights: 0-60% = real upload, 60-92% = server processing ticker, 92-100% = done
                const UPLOAD_END  = 60;
                const SERVER_END  = 92;

                const setCompressProgress = (pct, label) => {
                    const clamped = Math.max(0, Math.min(100, Math.round(pct)));
                    updateGlobeLoader(clamped, label || getCompressLabel(clamped));
                };

                function getCompressLabel(pct) {
                    if (pct < 20)  return 'Uploading document…';
                    if (pct < 40)  return 'Transferring to server…';
                    if (pct < 60)  return 'Upload complete, processing…';
                    if (pct < 75)  return 'Analyzing PDF structure…';
                    if (pct < 85)  return 'Optimizing fonts & images…';
                    if (pct < 92)  return 'Compressing stream data…';
                    return 'Finalizing output…';
                }

                setCompressProgress(0, 'Uploading document…');

                const formData = new FormData();
                formData.append('pdf_file', selectedCompressFile);
                formData.append('mode', mode);

                // Use XHR for real byte-level upload progress
                const xhr = new XMLHttpRequest();

                // Real upload progress: 0 → UPLOAD_END%
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable && e.total > 0) {
                        const pct = (e.loaded / e.total) * UPLOAD_END;
                        setCompressProgress(pct);
                    }
                });

                xhr.upload.addEventListener('load', () => {
                    setCompressProgress(UPLOAD_END, 'Analyzing PDF structure…');
                });

                // Server processing ticker: UPLOAD_END → SERVER_END% (slow logarithmic creep)
                let tickPct = UPLOAD_END;
                const ticker = setInterval(() => {
                    const remaining = SERVER_END - tickPct;
                    tickPct += remaining * 0.055;
                    setCompressProgress(tickPct);
                }, 280);

                xhr.onload = () => {
                    clearInterval(ticker);
                    setCompressProgress(SERVER_END, 'Finalizing output…');

                    // Small delay so user sees the bar reach ~92% before jump to 100
                    setTimeout(() => {
                        hideGlobeLoader();
                        startCompressBtn.disabled = false;
                        startCompressBtn.textContent = 'COMPRESS PDF NOW';

                        try {
                            const data = JSON.parse(xhr.responseText);
                            if (data.success) {
                                renderCompressorResults(data);
                            } else {
                                showError(data.error || 'Compression failed.');
                            }
                        } catch {
                            showError('Invalid response from server.');
                        }
                    }, 300);
                };

                xhr.onerror = () => {
                    clearInterval(ticker);
                    hideGlobeLoader();
                    startCompressBtn.disabled = false;
                    startCompressBtn.textContent = 'COMPRESS PDF NOW';
                    showError('Network error compressing file.');
                };

                xhr.open('POST', '/api/compress/process');
                xhr.send(formData);
            });
        }

        if (resetCompressorBtn) {
            resetCompressorBtn.addEventListener('click', () => {
                selectedCompressFile = null;
                if (compressorSettingsBox) compressorSettingsBox.classList.add('hidden');
                if (compressorResultCard) compressorResultCard.classList.add('hidden');
                if (compressorDropZone) compressorDropZone.classList.remove('hidden');
            });
        }
    }

    function setupCompressorFile(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            showError('Invalid file type. Please select a valid PDF file.');
            return;
        }
        selectedCompressFile = file;
        if (compressorSettingsBox) compressorSettingsBox.classList.remove('hidden');
        if (compressorResultCard) compressorResultCard.classList.add('hidden');

        const anaFileName = document.getElementById('analysisFileName');
        const anaPageCount = document.getElementById('anaPageCount');
        const anaFileSize = document.getElementById('anaFileSize');
        const anaTextType = document.getElementById('anaTextType');
        const anaImagesFonts = document.getElementById('anaImagesFonts');
        const anaEstSavings = document.getElementById('anaEstSavings');

        // Immediately update known file metadata locally
        if (anaFileName) anaFileName.textContent = file.name;
        if (anaFileSize) anaFileSize.textContent = formatBytes(file.size);
        if (anaPageCount) anaPageCount.textContent = 'Analyzing...';
        if (anaTextType) anaTextType.textContent = 'Detecting...';
        if (anaImagesFonts) anaImagesFonts.textContent = 'Scanning PDF structure...';
        if (anaEstSavings) anaEstSavings.textContent = '30% – 65%';

        showToast(`Analyzing ${file.name}...`);

        const formData = new FormData();
        formData.append('pdf_file', file);

        fetch('/api/compress/analyze', {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.success && data.analysis) {
                const a = data.analysis;
                if (anaFileName) anaFileName.textContent = data.filename || file.name;
                if (anaPageCount) anaPageCount.textContent = a.page_count;
                if (anaFileSize) anaFileSize.textContent = formatBytes(a.original_size || file.size);
                if (anaTextType) anaTextType.textContent = a.has_selectable_text ? 'Selectable Text' : (a.is_scanned ? 'Scanned PDF' : 'Mixed PDF');
                if (anaImagesFonts) anaImagesFonts.textContent = `${a.total_images} image(s) (${(a.image_formats||[]).join('/')}) • ${a.font_count} font(s)`;
                if (anaEstSavings) anaEstSavings.textContent = a.est_reduction;
            } else {
                if (anaPageCount) anaPageCount.textContent = 'Ready';
                if (anaTextType) anaTextType.textContent = 'PDF Document';
                if (anaImagesFonts) anaImagesFonts.textContent = 'Ready for compression';
            }
        })
        .catch(() => {
            if (anaPageCount) anaPageCount.textContent = 'Ready';
            if (anaTextType) anaTextType.textContent = 'PDF Document';
            if (anaImagesFonts) anaImagesFonts.textContent = 'Ready for compression';
        });
    }

    function renderCompressorResults(data) {
        document.getElementById('compOrigSize').textContent = formatBytes(data.original_size);
        document.getElementById('compNewSize').textContent = formatBytes(data.compressed_size);
        document.getElementById('compSavedPct').textContent = `${data.saved_percent}% (${formatBytes(data.space_saved)})`;
        document.getElementById('compProcTime').textContent = `${data.processing_time}s`;

        const downloadBtn = document.getElementById('downloadCompressedBtn');
        if (downloadBtn) downloadBtn.href = data.download_url;

        if (compressorResultCard) compressorResultCard.classList.remove('hidden');
    }

    // --------------------------------------------------------------------------
    // 7. FEATURE 3: PDF COMBINER CONTROLLER
    // --------------------------------------------------------------------------
    function initCombinerUI() {
        if (combinerAddBtn) combinerAddBtn.addEventListener('click', () => {
            combinerInsertTargetIndex = null; // Add btn always appends at end
            combinerFileInput.click();
        });

        if (combinerFileInput) {
            combinerFileInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) {
                    // Pass the stored insertion index (null = append)
                    uploadCombinerFilesSequential(Array.from(e.target.files), combinerInsertTargetIndex);
                    combinerInsertTargetIndex = null;
                }
            });
        }

        if (combinerDropZone) {
            combinerDropZone.addEventListener('click', (e) => {
                if (e.target.tagName !== 'BUTTON' && !e.target.closest('button')) {
                    if (combinerFileInput) combinerFileInput.click();
                }
            });
            ['dragenter', 'dragover'].forEach(name => {
                combinerDropZone.addEventListener(name, (e) => {
                    e.preventDefault();
                    combinerDropZone.classList.add('dragover');
                });
            });
            ['dragleave', 'drop'].forEach(name => {
                combinerDropZone.addEventListener(name, (e) => {
                    e.preventDefault();
                    combinerDropZone.classList.remove('dragover');
                });
            });
            combinerDropZone.addEventListener('drop', (e) => {
                const files = e.dataTransfer.files;
                if (files.length > 0) uploadCombinerFilesSequential(Array.from(files));
            });
        }

        if (cancelCombinerBtn) {
            cancelCombinerBtn.addEventListener('click', () => {
                combinerCancelRequested = true;
                showToast('Cancelling processing...');
            });
        }

        if (clearCombinerBtn) {
            clearCombinerBtn.addEventListener('click', () => {
                if (combinerSessionId) {
                    fetch('/api/combiner/clear', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: combinerSessionId })
                    }).catch(() => {});
                }
                combinerPages = [];
                combinerSessionId = null;
                renderCombinerCanvas();
                if (combinerResultCard) combinerResultCard.classList.add('hidden');
                if (combinerProgressBox) combinerProgressBox.classList.add('hidden');
            });
        }

        // Combiner: floating scroll navigation — use delegation so order-of-DOM doesn't matter
        // The real scrollable container is .main-content-panel (overflow-y: auto), not window
        document.addEventListener('click', (e) => {
            if (e.target.closest('#combinerScrollTopBtn')) {
                const panel = document.querySelector('.main-content-panel');
                if (panel) panel.scrollTo({ top: 0, behavior: 'smooth' });
                return;
            }
            if (e.target.closest('#combinerScrollBottomBtn')) {
                const panel = document.querySelector('.main-content-panel');
                if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' });
            }
        });

        if (generateCombinedPdfBtn) {
            generateCombinedPdfBtn.addEventListener('click', () => {
                if (combinerPages.length === 0) {
                    showError('No pages in canvas to combine.');
                    return;
                }

                generateCombinedPdfBtn.disabled = true;
                generateCombinedPdfBtn.textContent = 'COMBINING PDF...';
                showGlobeLoader('Generating Combined PDF...', `${combinerPages.length} pages in session`);
                updateGlobeLoader(50, 'Assembling page streams & vector graphics...');

                const pageSpecs = combinerPages.map(p => ({
                    file_path: p.file_path,
                    is_image: p.is_image,
                    source_page_idx: p.source_page_idx,
                    rotation: p.rotation || 0
                }));

                fetch('/api/combiner/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: combinerSessionId,
                        page_specs: pageSpecs
                    })
                })
                .then(res => res.json())
                .then(data => {
                    hideGlobeLoader();
                    generateCombinedPdfBtn.disabled = false;
                    generateCombinedPdfBtn.textContent = 'COMBINE PDF';

                    if (data.success) {
                        renderCombinerResult(data);
                    } else {
                        showError(data.error || 'Failed to combine PDF.');
                    }
                })
                .catch(() => {
                    hideGlobeLoader();
                    generateCombinedPdfBtn.disabled = false;
                    generateCombinedPdfBtn.textContent = 'COMBINE PDF';
                    showError('Network error generating combined PDF.');
                });
            });
        }
    }

    async function uploadCombinerFilesSequential(files, insertAtIndex) {
        if (isCombinerUploading) return;
        hideError();
        isCombinerUploading = true;
        combinerCancelRequested = false;

        // Capture insertion index (null = append at end)
        const targetIndex = (insertAtIndex !== null && insertAtIndex !== undefined)
            ? insertAtIndex
            : null;

        if (combinerProgressBox) combinerProgressBox.classList.remove('hidden');

        let totalAdded = 0;
        const totalFiles = files.length;
        const fileErrors = [];

        // Collect all newly-processed pages across all uploaded files
        const collectedNewPages = [];
        // Track the full server page list from the last successful upload (safe fallback)
        let lastServerPages = combinerPages.slice();

        for (let i = 0; i < totalFiles; i++) {
            if (combinerCancelRequested) {
                showToast('Combiner processing cancelled.');
                break;
            }

            const file = files[i];

            if (combinerProgressTitle) combinerProgressTitle.textContent = `Processing file ${i + 1} of ${totalFiles}...`;
            if (combinerProgressStatusText) combinerProgressStatusText.textContent = `${file.name} (${formatBytes(file.size)})`;

            // ── Phase weights: 0-70% = upload bytes, 70-95% = server processing, 95-100% = done ──
            const FILE_UPLOAD_END = 70;   // real upload bytes go 0 → 70%
            const SERVER_END      = 95;   // simulated processing ticker goes 70 → 95%

            const setProgress = (pct) => {
                const clamped = Math.max(0, Math.min(100, Math.round(pct)));
                if (combinerProgressBar) combinerProgressBar.style.width = `${clamped}%`;
                if (combinerProgressPercent) combinerProgressPercent.textContent = `${clamped}%`;
            };

            setProgress(0);

            const formData = new FormData();
            if (combinerSessionId) formData.append('session_id', combinerSessionId);
            formData.append('files', file);

            // Upload the file using XHR so we get real byte-level progress events
            const result = await new Promise((resolve) => {
                const xhr = new XMLHttpRequest();

                // ── Real upload progress (0 → FILE_UPLOAD_END%) ──
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable && e.total > 0) {
                        const uploadPct = (e.loaded / e.total) * FILE_UPLOAD_END;
                        setProgress(uploadPct);
                    }
                });

                xhr.upload.addEventListener('load', () => {
                    // Upload done; hold at FILE_UPLOAD_END% until server responds
                    setProgress(FILE_UPLOAD_END);
                });

                // ── Simulated server-processing ticker (FILE_UPLOAD_END → SERVER_END%) ──
                let tickerPct = FILE_UPLOAD_END;
                const ticker = setInterval(() => {
                    // Slow logarithmic creep so it never hits SERVER_END on its own
                    const remaining = SERVER_END - tickerPct;
                    tickerPct += remaining * 0.06;  // ~6% of remaining gap per tick
                    setProgress(tickerPct);
                }, 250);

                xhr.onload = () => {
                    clearInterval(ticker);
                    try {
                        const data = JSON.parse(xhr.responseText);
                        resolve({ ok: xhr.status >= 200 && xhr.status < 300, data });
                    } catch {
                        resolve({ ok: false, data: { error: 'Invalid server response' } });
                    }
                };

                xhr.onerror = () => {
                    clearInterval(ticker);
                    resolve({ ok: false, data: { error: 'Network error uploading file.' } });
                };

                xhr.open('POST', '/api/combiner/upload');
                xhr.send(formData);
            });

            // ── Snap to SERVER_END% before reconciliation ──
            setProgress(SERVER_END);

            if (result.ok && result.data.success) {
                combinerSessionId = result.data.session_id;
                const newPages = result.data.new_pages || [];
                collectedNewPages.push(...newPages);
                totalAdded += (result.data.added_count || 0);
                if (result.data.pages && result.data.pages.length > 0) {
                    lastServerPages = result.data.pages;
                }
                if (result.data.errors && result.data.errors.length > 0) {
                    fileErrors.push(...result.data.errors);
                }
            } else {
                fileErrors.push(`${file.name}: ${result.data.error || 'Failed to process'}`);
            }

            // Small pause so user sees SERVER_END% before moving to next file
            await new Promise(r => setTimeout(r, 120));
        }

        // Reconcile: try the dedicated pages endpoint; fall back to lastServerPages from upload
        let serverPages = lastServerPages;
        if (combinerSessionId) {
            try {
                const pagesRes = await fetch(`/api/combiner/pages/${combinerSessionId}`);
                if (pagesRes.ok) {
                    const pagesData = await pagesRes.json();
                    if (pagesData.pages && pagesData.pages.length > 0) {
                        serverPages = pagesData.pages;
                    }
                }
            } catch (_) { /* use lastServerPages fallback */ }
        }

        if (targetIndex !== null && collectedNewPages.length > 0) {
            // Server appended new pages at the end; split existing from new, then splice into position
            const existingPages = serverPages.slice(0, serverPages.length - collectedNewPages.length);
            const clampedIndex = Math.max(0, Math.min(targetIndex, existingPages.length));
            combinerPages = [
                ...existingPages.slice(0, clampedIndex),
                ...collectedNewPages,
                ...existingPages.slice(clampedIndex)
            ];
        } else {
            combinerPages = serverPages.length > 0 ? serverPages : combinerPages;
        }

        renderCombinerCanvas();

        if (combinerProgressBar) combinerProgressBar.style.width = '100%';
        if (combinerProgressPercent) combinerProgressPercent.textContent = '100%';

        setTimeout(() => {
            if (combinerProgressBox) combinerProgressBox.classList.add('hidden');
            isCombinerUploading = false;
            combinerInsertTargetIndex = null;

            if (combinerFileInput) combinerFileInput.value = '';

            if (totalAdded > 0) {
                const where = (targetIndex !== null) ? ` at position ${targetIndex + 1}` : '';
                showToast(`Inserted ${totalAdded} new page(s)${where}.`);
            }

            if (fileErrors.length > 0) {
                showError(fileErrors.join('\n'));
            }
        }, 500);
    }

    // Helper: create an insert-slot element
    function _makeCombinerInsertSlot(insertIndex) {
        const slot = document.createElement('div');
        slot.className = 'combiner-insert-slot';
        slot.dataset.insertIndex = insertIndex;
        slot.innerHTML = `
            <div class="insert-line"></div>
            <button type="button" class="insert-btn" title="Insert pages here">+</button>
            <span class="insert-tooltip">Insert here</span>
        `;

        // Click: open file picker at this index
        slot.addEventListener('click', (e) => {
            e.stopPropagation();
            combinerInsertTargetIndex = insertIndex;
            if (combinerFileInput) {
                combinerFileInput.value = '';
                combinerFileInput.click();
            }
        });

        // Drag-over: allow a dragged page-card to drop between pages
        slot.addEventListener('dragenter', (e) => {
            e.preventDefault();
            if (draggedPageIndex !== null) slot.classList.add('drag-target');
        });
        slot.addEventListener('dragover', (e) => {
            e.preventDefault();
            if (draggedPageIndex !== null) {
                e.dataTransfer.dropEffect = 'move';
                slot.classList.add('drag-target');
            }
        });
        slot.addEventListener('dragleave', () => slot.classList.remove('drag-target'));
        slot.addEventListener('drop', (e) => {
            e.preventDefault();
            slot.classList.remove('drag-target');
            if (draggedPageIndex !== null) {
                const movedPage = combinerPages.splice(draggedPageIndex, 1)[0];
                // After removal the insertion index may shift by 1
                let targetIdx = insertIndex;
                if (draggedPageIndex < insertIndex) targetIdx -= 1;
                targetIdx = Math.max(0, Math.min(targetIdx, combinerPages.length));
                combinerPages.splice(targetIdx, 0, movedPage);
                draggedPageIndex = null;
                renderCombinerCanvas();
            }
        });

        return slot;
    }

    function renderCombinerCanvas() {
        if (!pageThumbnailsGrid) return;
        pageThumbnailsGrid.innerHTML = '';

        if (combinerPages.length === 0) {
            if (combinerDropZone) combinerDropZone.classList.remove('hidden');
            if (combinerCanvas) combinerCanvas.classList.add('hidden');
            if (combinerControlsBar) combinerControlsBar.classList.add('hidden');
            if (combinerStatsText) combinerStatsText.textContent = '0 pages loaded';
            // Hide floating scroll navigator
            const floatScrollHide = document.getElementById('combinerFloatScroll');
            if (floatScrollHide) floatScrollHide.classList.add('hidden');
            return;
        }

        if (combinerDropZone) combinerDropZone.classList.add('hidden');
        if (combinerCanvas) combinerCanvas.classList.remove('hidden');
        if (combinerControlsBar) combinerControlsBar.classList.remove('hidden');
        if (combinerStatsText) combinerStatsText.textContent = `${combinerPages.length} page(s) loaded`;

        // Show floating scroll navigator
        const floatScroll = document.getElementById('combinerFloatScroll');
        if (floatScroll) {
            floatScroll.classList.remove('hidden');
            lucide.createIcons();
        }

        // Insert slot BEFORE first page (index 0)
        pageThumbnailsGrid.appendChild(_makeCombinerInsertSlot(0));

        combinerPages.forEach((page, index) => {
            const card = document.createElement('div');
            card.className = 'page-thumb-card';
            card.draggable = true;
            card.dataset.index = index;

            const thumbUrl = `/api/combiner/thumbnail/${combinerSessionId}/${page.thumbnail_filename}`;

            card.innerHTML = `
                <div class="thumb-image-wrapper">
                    <img src="${thumbUrl}" style="transform: rotate(${page.rotation || 0}deg);">
                </div>
                <div class="thumb-footer">
                    <span class="thumb-page-badge">#${index + 1}</span>
                    <span style="max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(page.file_name)}</span>
                    <div class="thumb-controls">
                        <button type="button" class="thumb-action-btn" title="Rotate 90\u00b0" onclick="rotateCombinerPage(${index})">\u21bb</button>
                        <button type="button" class="thumb-action-btn delete" title="Delete Page" onclick="deleteCombinerPage(${index})">\u2715</button>
                    </div>
                </div>
            `;

            // HTML5 Drag and Drop Events on card
            card.addEventListener('dragstart', (e) => {
                draggedPageIndex = index;
                card.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            });

            card.addEventListener('dragend', () => {
                card.classList.remove('dragging');
                document.querySelectorAll('.page-thumb-card').forEach(c => c.classList.remove('drag-over'));
                document.querySelectorAll('.combiner-insert-slot').forEach(s => s.classList.remove('drag-target'));
            });

            // Keep card-to-card drop for backwards-compat swapping
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                card.classList.add('drag-over');
            });

            card.addEventListener('dragleave', () => card.classList.remove('drag-over'));

            card.addEventListener('drop', (e) => {
                e.preventDefault();
                card.classList.remove('drag-over');
                if (draggedPageIndex !== null && draggedPageIndex !== index) {
                    const movedPage = combinerPages.splice(draggedPageIndex, 1)[0];
                    combinerPages.splice(index, 0, movedPage);
                    draggedPageIndex = null;
                    renderCombinerCanvas();
                }
            });

            pageThumbnailsGrid.appendChild(card);

            // Insert slot AFTER this page (i.e. before next page = index+1)
            pageThumbnailsGrid.appendChild(_makeCombinerInsertSlot(index + 1));
        });
    }

    window.rotateCombinerPage = function(index) {
        if (combinerPages[index]) {
            combinerPages[index].rotation = ((combinerPages[index].rotation || 0) + 90) % 360;
            renderCombinerCanvas();
        }
    };

    window.deleteCombinerPage = function(index) {
        if (combinerPages[index]) {
            combinerPages.splice(index, 1);
            renderCombinerCanvas();
        }
    };

    function renderCombinerResult(data) {
        document.getElementById('combTotalPages').textContent = data.total_pages;
        document.getElementById('combFileSize').textContent = formatBytes(data.file_size);
        document.getElementById('combProcTime').textContent = `${data.processing_time}s`;

        const downloadBtn = document.getElementById('downloadCombinedBtn');
        if (downloadBtn) downloadBtn.href = data.download_url;

        if (combinerResultCard) combinerResultCard.classList.remove('hidden');
    }

    // --------------------------------------------------------------------------
    // 8. DOCUMENTS LIBRARY & HISTORY
    // --------------------------------------------------------------------------
    function loadDocumentsLibrary() {
        fetch('/api/documents')
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const docs = data.documents || [];
                    // Synchronize chatSessions from backend
                    chatSessions = docs.map(doc => ({
                        id: doc.document_id,
                        title: doc.filename,
                        pages: doc.page_count,
                        time: 'Indexed'
                    }));

                    // Initialize activeDocumentId if not yet set and an active document exists
                    const activeDoc = docs.find(d => d.is_active);
                    if (activeDoc && !activeDocumentId) {
                        activeDocumentId = activeDoc.document_id;
                        currentJobId = activeDoc.document_id;
                        activeChatSessionId = activeDoc.document_id;
                    }

                    renderChatHistorySidebar();
                    renderHeroSessions(docs);
                }
            })
            .catch(() => {});
    }

    function renderHeroSessions(docs) {
        const sidebar = document.getElementById('heroRecentSidebar');
        const countBadge = document.getElementById('sessionCountBadge');
        const floatingBadge = document.getElementById('floatingSessionCountBadge');
        const emptyState = document.getElementById('rssEmptyState');
        const list = document.getElementById('heroSessionsList');
        const railIcons = document.getElementById('rssRailIcons');

        const sessionCount = docs ? docs.length : 0;

        if (countBadge) countBadge.textContent = sessionCount;
        if (floatingBadge) floatingBadge.textContent = sessionCount;

        if (sidebar && activeTab === 'assistant') {
            sidebar.classList.remove('sidebar-hidden');
            const savedState = localStorage.getItem('tendermind_sidebar_collapsed');
            if (savedState === 'true') {
                sidebar.classList.add('sidebar-collapsed');
            } else {
                sidebar.classList.remove('sidebar-collapsed');
            }
        }

        if (!docs || docs.length === 0) {
            if (emptyState) emptyState.classList.remove('hidden');
            if (list) list.innerHTML = '';
            if (railIcons) railIcons.innerHTML = `
                <button type="button" class="rss-rail-doc-icon" title="No sessions yet - Click to upload" onclick="document.getElementById('fileInput').click()">
                    <i data-lucide="plus"></i>
                </button>
            `;
            if (window.lucide) lucide.createIcons();
            return;
        }

        if (emptyState) emptyState.classList.add('hidden');

        const curActiveId = activeDocumentId || currentJobId || activeChatSessionId;

        // Render Expanded Session Cards
        if (list) {
            list.innerHTML = docs.map(doc => {
                const isActive = (curActiveId === doc.document_id);
                const safeName = escapeHtml(doc.filename);
                let dlBadgeHtml = '';
                if (doc.deadline && doc.deadline.has_deadline) {
                    dlBadgeHtml = `<div class="rss-deadline-badge ${doc.deadline.urgency}"><span class="rss-dl-dot"></span>${escapeHtml(doc.deadline.urgency_text || 'Deadline')}</div>`;
                } else {
                    dlBadgeHtml = `<div class="rss-deadline-badge none">No deadline detected</div>`;
                }

                return `
                    <div class="hero-session-card ${isActive ? 'session-active' : ''}" onclick="selectDocument('${doc.document_id}')" title="${safeName}">
                        <div class="hero-session-top-row">
                            <div class="hero-session-clickable">
                                <div class="hero-session-icon">
                                    <i data-lucide="file-text"></i>
                                </div>
                                <div class="hero-session-info">
                                    <div class="hero-session-name" title="${safeName}">${safeName}</div>
                                    <div class="hero-session-meta-row">
                                        <span class="hero-session-meta">${doc.page_count} pages</span>
                                        <span class="session-status-dot"></span>
                                        <span class="session-status-label">Ready</span>
                                    </div>
                                    ${dlBadgeHtml}
                                </div>
                            </div>
                            <div class="hero-session-actions">
                                <button type="button" class="hero-session-del-btn" title="Delete session" aria-label="Delete session" onclick="event.stopPropagation(); deleteDocumentSession('${doc.document_id}')">
                                    <i data-lucide="trash-2"></i>
                                </button>
                                <div class="hero-session-arrow" title="Open session">
                                    <i data-lucide="arrow-right"></i>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        // Render Collapsed Rail Icons
        if (railIcons) {
            railIcons.innerHTML = docs.map(doc => {
                const isActive = (curActiveId === doc.document_id);
                const safeName = escapeHtml(doc.filename);
                return `
                    <button type="button" class="rss-rail-doc-icon ${isActive ? 'active' : ''}" title="${safeName} (${doc.page_count} pages)" onclick="selectDocument('${doc.document_id}')">
                        <i data-lucide="file-text"></i>
                    </button>
                `;
            }).join('');
        }

        if (window.lucide) lucide.createIcons();
    }

    function initRecentSessionsMenu() {
        const sidebar = document.getElementById('heroRecentSidebar');
        const closeBtn = document.getElementById('closeRecentSidebarBtn');
        const openBtn = document.getElementById('openRecentSidebarBtn');
        const clearBtn = document.getElementById('clearAllSessionsBtn');
        const newSessionBtn = document.getElementById('rssNewSessionBtn');

        // Apply saved collapse state on startup
        const savedState = localStorage.getItem('tendermind_sidebar_collapsed');
        if (sidebar && savedState === 'true') {
            sidebar.classList.add('sidebar-collapsed');
        }

        if (closeBtn && sidebar) {
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                sidebar.classList.add('sidebar-collapsed');
                localStorage.setItem('tendermind_sidebar_collapsed', 'true');
            });
        }

        if (openBtn && sidebar) {
            openBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                sidebar.classList.remove('sidebar-collapsed');
                localStorage.setItem('tendermind_sidebar_collapsed', 'false');
            });
        }

        if (newSessionBtn) {
            newSessionBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                switchTab('assistant');
                if (fileInput) fileInput.click();
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                if (confirm('Clear all recent document sessions?')) {
                    fetch('/api/documents/clear_all', { method: 'POST' })
                        .then(res => res.json())
                        .then(data => {
                            if (data.success) {
                                chatSessions = [];
                                activeDocumentId = null;
                                currentJobId = null;
                                activeChatSessionId = null;
                                renderChatHistorySidebar();
                                renderHeroSessions([]);
                                showToast('Recent sessions cleared.');
                            }
                        })
                        .catch(() => showError('Failed to clear sessions.'));
                }
            });
        }
    }

    function deleteDocumentSession(docId) {
        fetch(`/api/documents/${docId}`, { method: 'DELETE' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    chatSessions = chatSessions.filter(s => s.id !== docId);
                    if (activeDocumentId === docId || currentJobId === docId) {
                        activeDocumentId = chatSessions.length > 0 ? chatSessions[0].id : null;
                        currentJobId = activeDocumentId;
                        activeChatSessionId = activeDocumentId;
                    }
                    loadDocumentsLibrary();
                    showToast('Session removed.');
                }
            })
            .catch(() => showError('Failed to delete session.'));
    }

    window.deleteDocumentSession = deleteDocumentSession;

    function selectDocument(docId) {
        if (!docId) return;
        setActiveDocument(docId);
        showGlobeLoader('Loading document session...', '');
        fetch(`/api/result/${docId}`)
            .then(res => res.json())
            .then(r => {
                hideGlobeLoader();
                if (r.success) {
                    enterWorkspace(r.data);
                    loadDocumentsLibrary();
                } else {
                    showError(r.error || 'Could not open session. The document may need to be re-uploaded.');
                }
            })
            .catch(() => {
                hideGlobeLoader();
                showError('Network error loading session. Please try again.');
            });
    }

    window.selectDocument = selectDocument;


    // --------------------------------------------------------------------------
    // 9. RESIZABLE PANES & HELPERS
    // --------------------------------------------------------------------------
    function initResizers() {
        const chatGutter = document.getElementById('resizerChatGutter');
        const rightPane = document.querySelector('.pane-right');
        const workspaceGrid = document.querySelector('.workspace-grid');

        if (!workspaceGrid) return;

        if (chatGutter && rightPane) {
            let isDragging = false;
            let startX = 0;
            let startW = 0;

            chatGutter.addEventListener('mousedown', (e) => {
                isDragging = true;
                startX = e.clientX;
                startW = rightPane.getBoundingClientRect().width;
                document.body.style.cursor = 'col-resize';

                const onMove = (ev) => {
                    if (!isDragging) return;
                    let w = startW - (ev.clientX - startX);
                    w = Math.max(280, Math.min(w, 650));
                    rightPane.style.width = `${w}px`;
                };

                const onUp = () => {
                    isDragging = false;
                    document.body.style.cursor = '';
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                };

                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            });
        }
    }

    // -----------------------------------------------------------------------
    // Markdown Rendering Pipeline
    // -----------------------------------------------------------------------

    // preprocessMarkdownText: Strips think blocks, whole-response fences, and thought preambles
    function preprocessMarkdownText(text) {
        if (!text) return '';

        let cleaned = text;

        // 1. Strip <think>...</think> reasoning blocks
        cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();

        // 2. Remove ``` outer fence that wraps the ENTIRE response
        //    e.g. ```markdown ... ``` or ``` ... ```
        const fenceMatch = cleaned.match(/^```[a-z]*\n([\s\S]*?)\n```$/m);
        if (fenceMatch) {
            cleaned = fenceMatch[1].trim();
        } else {
            // Simpler check: starts with ```..., ends with ```
            const trimmed = cleaned.trim();
            if (trimmed.startsWith('```')) {
                const firstNl = trimmed.indexOf('\n');
                if (firstNl !== -1) {
                    const rest = trimmed.slice(firstNl + 1);
                    if (rest.trimEnd().endsWith('```')) {
                        cleaned = rest.trimEnd().slice(0, -3).trim();
                    }
                }
            }
        }

        // 3. Strip LLM reasoning preamble lines before the real answer
        const thoughtRegex = /(?:Here'?s a thinking process|Analyze User (?:Input|Request|Query|Prompt)|Analyze (?:Input|Request|Query|Prompt|User)|Check (?:System Prompt|Formatting|Constraints|Mandates)|Scan (?:Retrieved )?Context|Extract (?:Information|Data|Items|Specs) from Context|Thought Process:|Thinking Process:|Draft Response|Mental Refinement|Let'?s (?:parse|extract|check|scan|analyze))/i;
        if (thoughtRegex.test(cleaned.substring(0, 800))) {
            const lines = cleaned.split('\n');
            const cleanLines = [];
            let skipping = true;
            for (let i = 0; i < lines.length; i++) {
                const l = lines[i].trim();
                if (skipping) {
                    // Stop skipping at the first real content line
                    if (l.startsWith('#') || l.startsWith('**') || l.startsWith('- ') || l.startsWith('* ') || /^\d+\.\s/.test(l)) {
                        skipping = false;
                        cleanLines.push(lines[i]);
                    } else if (l.length > 0 && !thoughtRegex.test(l) && !l.startsWith('```')) {
                        skipping = false;
                        cleanLines.push(lines[i]);
                    }
                } else {
                    cleanLines.push(lines[i]);
                }
            }
            if (cleanLines.length > 0) cleaned = cleanLines.join('\n').trim();
        }

        // 4. Normalise excessive blank lines (max 2 consecutive)
        cleaned = cleaned.replace(/\n{3,}/g, '\n\n');

        return cleaned;
    }

    // renderMarkdownSafely: parses Markdown, sanitizes HTML, and embeds citation buttons
    function renderMarkdownSafely(rawText) {
        if (!rawText) return '';

        // Stage 1: pre-process
        const normalizedText = preprocessMarkdownText(rawText);

        // Stage 2: extract page citations into placeholders so they survive
        // marked.js parsing (which might otherwise mangle the brackets)
        const citationPlaceholders = [];
        const citationPattern = /(?:\[\s*(?:Page|p\.)\s*(\d+)\s*\]|\(\s*(?:Page|p\.)\s*(\d+)\s*\)|\*\(\s*(?:Page|p\.)\s*(\d+)\s*\)\*|(?:—|–|-)\s*(?:Page|p\.)\s*(\d+)\b|\b(?:Page|p\.)\s*(\d+)(?=\s*$|[\.,;\)\n]))/gi;

        let processed = normalizedText.replace(citationPattern, (match, p1, p2, p3, p4, p5) => {
            const pageNum = p1 || p2 || p3 || p4 || p5;
            if (pageNum) {
                const idx = citationPlaceholders.length;
                citationPlaceholders.push(pageNum);
                return `\x01CIT${idx}\x01`;
            }
            return match;
        });

        // Stage 3: parse Markdown with a custom renderer
        let parsedHtml = '';
        if (typeof marked !== 'undefined') {
            const renderer = new marked.Renderer();

            // Links -> open safely in new tab
            renderer.link = function (hrefOrToken, title, text) {
                let href = hrefOrToken, t = title, linkText = text;
                if (typeof hrefOrToken === 'object' && hrefOrToken !== null) {
                    href = hrefOrToken.href || '';
                    t = hrefOrToken.title || '';
                    linkText = hrefOrToken.text || hrefOrToken.raw || '';
                }
                const safeHref = escapeHtml(href || '#');
                const titleAttr = t ? ` title="${escapeHtml(t)}"` : '';
                return `<a href="${safeHref}" target="_blank" rel="noopener noreferrer" class="chat-link"${titleAttr}>${linkText || href || 'Link'}</a>`;
            };

            // Tables -> wrap in horizontal-scroll container
            renderer.table = function (headerOrToken, body) {
                if (typeof headerOrToken === 'object' && headerOrToken !== null
                        && typeof headerOrToken.header !== 'undefined') {
                    // marked v5+ passes a token object
                    const headerHtml = headerOrToken.header
                        .map(h => `<th>${h.text}</th>`).join('');
                    const bodyHtml = (headerOrToken.rows || [])
                        .map(row => `<tr>${row.map(c => `<td>${c.text}</td>`).join('')}</tr>`)
                        .join('');
                    return `<div class="chat-table-wrapper"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
                }
                // Legacy (marked v4)
                return `<div class="chat-table-wrapper"><table><thead>${headerOrToken}</thead><tbody>${body}</tbody></table></div>`;
            };

            // Headings -- add CSS class for styling
            renderer.heading = function (textOrToken, level) {
                let headingText = textOrToken;
                let headingLevel = level;
                if (typeof textOrToken === 'object' && textOrToken !== null) {
                    headingText = textOrToken.text || textOrToken.raw || '';
                    headingLevel = textOrToken.depth || level;
                }
                const tag = `h${headingLevel}`;
                const cls = `md-h${headingLevel}`;
                return `<${tag} class="${cls}">${headingText}</${tag}>`;
            };

            try {
                marked.setOptions({
                    renderer: renderer,
                    breaks: true,
                    gfm: true,
                    headerIds: false,
                    mangle: false
                });
                parsedHtml = marked.parse(processed);
            } catch (e) {
                // Fallback: escape and display as plain text
                parsedHtml = `<p>${escapeHtml(processed)}</p>`;
            }
        } else {
            // No marked.js -- escape everything
            parsedHtml = `<p>${escapeHtml(processed).replace(/\n\n/g, '</p><p>').replace(/\n/g, '<br>')}</p>`;
        }

        // Stage 4: sanitise with DOMPurify
        let safeHtml = parsedHtml;
        if (typeof DOMPurify !== 'undefined') {
            safeHtml = DOMPurify.sanitize(parsedHtml, {
                ADD_TAGS: ['button', 'i', 'mark', 'div', 'span',
                           'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                           'p', 'strong', 'b', 'em', 'u', 's', 'a',
                           'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
                           'colgroup', 'col', 'ul', 'ol', 'li',
                           'pre', 'code', 'blockquote', 'hr', 'br',
                           'svg', 'path'],
                ADD_ATTR: ['data-page', 'data-doc', 'data-lucide', 'class', 'id',
                           'type', 'title', 'href', 'download', 'target', 'rel',
                           'colspan', 'rowspan', 'align', 'valign', 'scope']
            });
        }

        // Stage 5: replace citation placeholders with interactive jump buttons
        safeHtml = safeHtml.replace(/\x01CIT(\d+)\x01/g, (_, idx) => {
            const pageNum = citationPlaceholders[parseInt(idx, 10)];
            return `<button type="button" class="citation-btn" data-page="${pageNum}" title="Jump to Page ${pageNum} in PDF preview"><i data-lucide="file-text"></i> Page ${pageNum}</button>`;
        });

        return safeHtml;
    }

    function showError(msg) {
        if (errorMessage) errorMessage.textContent = msg;
        if (errorAlert) errorAlert.classList.remove('hidden');
    }

    function hideError() {
        if (errorAlert) errorAlert.classList.add('hidden');
    }

    if (closeAlertBtn) closeAlertBtn.addEventListener('click', hideError);

    function showToast(msg) {
        const container = document.getElementById('toastContainer');
        if (!container) return;
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    function formatBytes(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // --------------------------------------------------------------------------
    // 7. TENDER DEADLINE REMINDER SYSTEM CONTROLLER
    // --------------------------------------------------------------------------
    let currentDeadlines = [];
    let deadlineFilter = 'all';
    let deadlineSearchQuery = '';
    let deadlineSortBy = 'nearest';
    let pendingDeadlineConfirmData = null;
    let pendingDeleteTenderId = null;
    let pendingSettingsTenderId = null;

    function initDeadlineCenter() {
        const searchInput = document.getElementById('deadlineSearchInput');
        const clearSearchBtn = document.getElementById('clearDeadlineSearchBtn');
        const filterPills = document.querySelectorAll('.df-pill');
        const sortSelect = document.getElementById('deadlineSortSelect');
        const addBtn = document.getElementById('addManualDeadlineBtn');
        const emptyAddBtn = document.getElementById('emptyAddDeadlineBtn');
        const kpiCards = document.querySelectorAll('.kpi-card');

        // Search Input
        if (searchInput) {
            let searchTimeout = null;
            searchInput.addEventListener('input', () => {
                const val = searchInput.value.trim();
                deadlineSearchQuery = val;
                if (clearSearchBtn) {
                    if (val) clearSearchBtn.classList.remove('hidden');
                    else clearSearchBtn.classList.add('hidden');
                }
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => loadDeadlines(), 300);
            });
        }

        if (clearSearchBtn && searchInput) {
            clearSearchBtn.addEventListener('click', () => {
                searchInput.value = '';
                deadlineSearchQuery = '';
                clearSearchBtn.classList.add('hidden');
                loadDeadlines();
            });
        }

        // Filter Pills
        filterPills.forEach(pill => {
            pill.addEventListener('click', () => {
                filterPills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                deadlineFilter = pill.dataset.filter || 'all';
                loadDeadlines();
            });
        });

        // KPI Card Clicks (Filter shortcuts)
        kpiCards.forEach(card => {
            card.addEventListener('click', () => {
                const kpiFilter = card.dataset.filter;
                filterPills.forEach(p => {
                    if (p.dataset.filter === (kpiFilter === 'due_tomorrow' || kpiFilter === 'due_week' ? 'due_soon' : kpiFilter)) {
                        p.classList.add('active');
                    } else {
                        p.classList.remove('active');
                    }
                });
                if (kpiFilter === 'due_tomorrow' || kpiFilter === 'due_week') {
                    deadlineFilter = 'due_soon';
                } else {
                    deadlineFilter = kpiFilter || 'all';
                }
                loadDeadlines();
            });
        });

        // Sort Select
        if (sortSelect) {
            sortSelect.addEventListener('change', () => {
                deadlineSortBy = sortSelect.value;
                loadDeadlines();
            });
        }

        // Add Manual Deadline
        const openAddModal = () => openDeadlineEditModal(null, true);
        if (addBtn) addBtn.addEventListener('click', openAddModal);
        if (emptyAddBtn) emptyAddBtn.addEventListener('click', openAddModal);

        // Delete All Deadlines at once — custom modal
        const deleteAllBtn = document.getElementById('deleteAllDeadlinesBtn');
        const deleteAllModal = document.getElementById('deleteAllModal');
        const delAllCancelBtn = document.getElementById('delAllCancelBtn');
        const delAllConfirmBtn = document.getElementById('delAllConfirmBtn');

        const openDelAllModal = () => {
            if (deleteAllModal) {
                deleteAllModal.classList.add('open');
                lucide.createIcons();
            }
        };
        const closeDelAllModal = () => {
            if (deleteAllModal) deleteAllModal.classList.remove('open');
        };

        if (deleteAllBtn) deleteAllBtn.addEventListener('click', openDelAllModal);
        if (delAllCancelBtn) delAllCancelBtn.addEventListener('click', closeDelAllModal);

        // Close on backdrop click
        if (deleteAllModal) {
            deleteAllModal.addEventListener('click', (e) => {
                if (e.target === deleteAllModal) closeDelAllModal();
            });
        }

        if (delAllConfirmBtn) {
            delAllConfirmBtn.addEventListener('click', () => {
                delAllConfirmBtn.disabled = true;
                delAllConfirmBtn.innerHTML = 'Deleting…';
                fetch('/api/deadlines/all', { method: 'DELETE' })
                    .then(res => res.json())
                    .then(data => {
                        closeDelAllModal();
                        delAllConfirmBtn.disabled = false;
                        delAllConfirmBtn.innerHTML = 'Yes, Delete All';
                        if (data.success) {
                            const n = data.deleted_count > 0 ? data.deleted_count + ' ' : '';
                            showToast(`All ${n}deadline(s) deleted successfully.`, 'success');
                            loadDeadlines();
                            loadDeadlinesSummary();
                        } else {
                            showToast(data.error || 'Failed to delete all deadlines.', 'error');
                        }
                    })
                    .catch(() => {
                        closeDelAllModal();
                        delAllConfirmBtn.disabled = false;
                        delAllConfirmBtn.innerHTML = 'Yes, Delete All';
                        showToast('Error connecting to server.', 'error');
                    });
            });
        }
    }

    function loadDeadlines() {
        const url = `/api/deadlines?filter=${encodeURIComponent(deadlineFilter)}&search=${encodeURIComponent(deadlineSearchQuery)}&sort=${encodeURIComponent(deadlineSortBy)}`;
        fetch(url)
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    currentDeadlines = data.tenders || [];
                    renderDeadlinesGrid(currentDeadlines);
                }
            })
            .catch(() => {});
    }

    function loadDeadlinesSummary() {
        fetch('/api/deadlines/summary')
            .then(res => res.json())
            .then(data => {
                if (data.success && data.summary) {
                    const s = data.summary;
                    const elTomorrow = document.getElementById('kpiDueTomorrow');
                    const elWeek = document.getElementById('kpiDueThisWeek');
                    const elUpcoming = document.getElementById('kpiUpcoming');
                    const elExpired = document.getElementById('kpiExpired');

                    if (elTomorrow) elTomorrow.textContent = s.due_tomorrow || 0;
                    if (elWeek) elWeek.textContent = s.due_this_week || 0;
                    if (elUpcoming) elUpcoming.textContent = s.upcoming || 0;
                    if (elExpired) elExpired.textContent = s.expired || 0;
                }
            })
            .catch(() => {});
    }

    function renderDeadlinesGrid(tenders) {
        const list = document.getElementById('deadlinesList');
        const emptyState = document.getElementById('deadlinesEmptyState');
        const emptySub = document.getElementById('deadlinesEmptySub');

        if (!list) return;

        if (!tenders || tenders.length === 0) {
            list.innerHTML = '';
            if (emptyState) {
                emptyState.classList.remove('hidden');
                if (deadlineSearchQuery && emptySub) {
                    emptySub.textContent = `No deadlines match "${escapeHtml(deadlineSearchQuery)}". Try clearing your search.`;
                } else if (emptySub) {
                    emptySub.textContent = 'Upload a tender document or manually track an external bidding deadline.';
                }
            }
            return;
        }

        if (emptyState) emptyState.classList.add('hidden');

        list.innerHTML = tenders.map(t => {
            const safeTitle = escapeHtml(t.title);
            const safeOrg = escapeHtml(t.organization || 'Procuring Entity');
            const safeDeadlineFormatted = escapeHtml(t.display ? t.display.formatted : t.submission_deadline);
            const borderClass = `border-${t.urgency || 'blue'}`;
            const urgencyBadgeClass = t.urgency || 'blue';
            const urgencyText = escapeHtml(t.urgency_text || 'Upcoming');
            const pageNum = t.submission_deadline_source_page || 1;
            const hasDocument = !t.id.startsWith('manual_');

            return `
                <div class="deadline-card ${borderClass}" data-tender-id="${t.id}" data-deadline-utc="${t.submission_deadline_utc}">
                    <div class="dc-header">
                        <div style="overflow: hidden; min-width: 0;">
                            <div class="dc-org-badge" title="${safeOrg}">${safeOrg}</div>
                            <h3 class="dc-title" title="${safeTitle}">${safeTitle}</h3>
                        </div>
                        <div class="dc-urgency-badge ${urgencyBadgeClass}">
                            <span class="dc-urgency-dot"></span>
                            <span>${urgencyText}</span>
                        </div>
                    </div>

                    <!-- Live Dynamic Countdown -->
                    <div class="dc-countdown-box">
                        <span class="dc-countdown-lbl">
                            <i data-lucide="hourglass"></i>
                            <span>Remaining:</span>
                        </span>
                        <span class="dc-countdown-val ${t.urgency}" id="countdown-${t.id}">
                            ${escapeHtml(t.remaining_human || 'Calculating...')}
                        </span>
                    </div>

                    <!-- Metadata Rows -->
                    <div class="dc-meta-rows">
                        <div class="dc-meta-row">
                            <span class="dc-meta-key">Submission Deadline:</span>
                            <span class="dc-meta-val">${safeDeadlineFormatted}</span>
                        </div>
                        ${t.opening_display && t.opening_display.formatted !== 'Not specified' ? `
                        <div class="dc-meta-row">
                            <span class="dc-meta-key">Tender Opening:</span>
                            <span class="dc-meta-val">${escapeHtml(t.opening_display.formatted)}</span>
                        </div>
                        ` : ''}
                        <div class="dc-meta-row">
                            <span class="dc-meta-key">Source &amp; Reminders:</span>
                            <div style="display: flex; align-items: center; gap: 0.4rem;">
                                ${hasDocument ? `
                                <button type="button" class="dc-source-link" onclick="viewTenderDocumentPage('${t.id}', ${pageNum})" title="Jump to Page ${pageNum} in PDF preview">
                                    <i data-lucide="file-text"></i> Page ${pageNum}
                                </button>
                                ` : '<span class="dc-meta-val">Manual</span>'}
                                <span style="font-size: 0.72rem; color: var(--text-muted);">• ${t.pending_reminders_count || 0} scheduled</span>
                            </div>
                        </div>
                    </div>

                    <!-- Actions Row -->
                    <div class="dc-actions">
                        <button type="button" class="btn btn-primary btn-sm dc-btn-view" onclick="openTenderFromDeadline('${t.id}')">
                            <i data-lucide="external-link"></i>
                            ${hasDocument ? 'View Tender' : 'Open Details'}
                        </button>
                        <button type="button" class="dc-icon-btn" title="Reminder Settings" aria-label="Reminder Settings" onclick="openReminderSettingsModal('${t.id}')">
                            <i data-lucide="bell"></i>
                        </button>
                        <button type="button" class="dc-icon-btn" title="Edit Deadline" aria-label="Edit Deadline" onclick="editTenderDeadlineById('${t.id}')">
                            <i data-lucide="edit-3"></i>
                        </button>
                        <button type="button" class="dc-icon-btn danger" title="Delete Deadline" aria-label="Delete Deadline" onclick="openDeleteDeadlineModal('${t.id}', '${safeTitle}')">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        if (window.lucide) lucide.createIcons();
    }

    // --------------------------------------------------------------------------
    // LIVE REAL-TIME COUNTDOWN TICKER
    // --------------------------------------------------------------------------
    function startDeadlineCountdownTicker() {
        setInterval(() => {
            const cards = document.querySelectorAll('.deadline-card');
            const now = new Date().getTime();

            cards.forEach(card => {
                const deadlineUtcStr = card.dataset.deadlineUtc;
                const tenderId = card.dataset.tenderId;
                if (!deadlineUtcStr || !tenderId) return;

                const countdownEl = document.getElementById(`countdown-${tenderId}`);
                if (!countdownEl) return;

                const deadlineTime = new Date(deadlineUtcStr).getTime();
                const diffMs = deadlineTime - now;

                if (diffMs <= 0) {
                    countdownEl.textContent = 'DEADLINE PASSED';
                    countdownEl.className = 'dc-countdown-val passed';
                } else {
                    const totalSecs = Math.floor(diffMs / 1000);
                    const days = Math.floor(totalSecs / 86400);
                    const hours = Math.floor((totalSecs % 86400) / 3600);
                    const minutes = Math.floor((totalSecs % 3600) / 60);
                    const seconds = totalSecs % 60;

                    let text = '';
                    if (days > 0) {
                        text = `${days}d ${hours}h ${minutes}m ${seconds}s`;
                    } else if (hours > 0) {
                        text = `${hours}h ${minutes}m ${seconds}s`;
                    } else {
                        text = `${minutes}m ${seconds}s`;
                    }
                    countdownEl.textContent = text;
                }
            });
        }, 1000);
    }

    // --------------------------------------------------------------------------
    // 8. NOTIFICATION SYSTEM & WEBSOCKET/POLL CONTROLLER
    // --------------------------------------------------------------------------
    function initNotificationsSystem() {
        const bellBtn = document.getElementById('notifBellBtn');
        const notifPanel = document.getElementById('notifPanel');
        const markAllReadBtn = document.getElementById('markAllReadBtn');
        const clearNotifsBtn = document.getElementById('clearNotifsBtn');

        if (bellBtn && notifPanel) {
            bellBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const isHidden = notifPanel.classList.contains('hidden');
                if (isHidden) {
                    notifPanel.classList.remove('hidden');
                    loadNotificationList();
                } else {
                    notifPanel.classList.add('hidden');
                }
            });

            // Close panel when clicking outside
            document.addEventListener('click', (e) => {
                if (!notifPanel.contains(e.target) && !bellBtn.contains(e.target)) {
                    notifPanel.classList.add('hidden');
                }
            });
        }

        if (markAllReadBtn) {
            markAllReadBtn.addEventListener('click', () => {
                fetch('/api/notifications/mark-read', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        updateNotificationBadge(data.unread_count || 0);
                        loadNotificationList();
                    }
                });
            });
        }

        if (clearNotifsBtn) {
            clearNotifsBtn.addEventListener('click', () => {
                fetch('/api/notifications/clear', { method: 'DELETE' })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) {
                            updateNotificationBadge(0);
                            loadNotificationList();
                            showToast('Notification history cleared.');
                        }
                    });
            });
        }

        // Initial poll and recurring poll every 15s
        pollNotifications();
        setInterval(pollNotifications, 15000);
    }

    function pollNotifications() {
        fetch('/api/notifications/poll')
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const count = data.unread_count || 0;
                    const prevBadge = parseInt(localStorage.getItem('tendermind_last_unread_count') || '0', 10);
                    updateNotificationBadge(count);

                    // If unread count increased, fire desktop notification if permitted
                    if (count > prevBadge && count > 0) {
                        checkAndTriggerDesktopAlert();
                    }
                    localStorage.setItem('tendermind_last_unread_count', count.toString());
                }
            })
            .catch(() => {});
    }

    function updateNotificationBadge(unreadCount) {
        const badge = document.getElementById('notifBadge');
        const countPill = document.getElementById('notifPanelCount');

        if (badge) {
            if (unreadCount > 0) {
                badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
                badge.classList.remove('hidden');
            } else {
                badge.classList.add('hidden');
            }
        }
        if (countPill) {
            countPill.textContent = `${unreadCount} unread`;
        }
    }

    function loadNotificationList() {
        const list = document.getElementById('notifList');
        const emptyState = document.getElementById('notifEmptyState');
        if (!list) return;

        fetch('/api/notifications')
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    const notifs = data.notifications || [];
                    updateNotificationBadge(data.unread_count || 0);

                    if (notifs.length === 0) {
                        list.innerHTML = '';
                        if (emptyState) emptyState.classList.remove('hidden');
                        return;
                    }

                    if (emptyState) emptyState.classList.add('hidden');

                    list.innerHTML = notifs.map(n => {
                        const isUnread = n.is_read === 0;
                        const notifType = n.type || 'info';
                        let iconName = 'bell';
                        if (notifType === 'urgent') iconName = 'alert-triangle';
                        else if (notifType === 'warning') iconName = 'clock';
                        else if (notifType === 'success') iconName = 'check-circle';
                        else if (notifType === 'expired') iconName = 'check-circle-2';

                        const timeAgo = formatTimeAgo(n.created_at);

                        return `
                            <div class="notif-item ${isUnread ? 'unread' : ''}" onclick="handleNotificationClick('${n.id}', '${n.tender_id || ''}')">
                                <div class="notif-item-icon ${notifType}">
                                    <i data-lucide="${iconName}"></i>
                                </div>
                                <div class="notif-item-content">
                                    <div class="notif-item-title">${escapeHtml(n.title)}</div>
                                    <div class="notif-item-msg">${escapeHtml(n.message)}</div>
                                    <div class="notif-item-time">${timeAgo}</div>
                                </div>
                            </div>
                        `;
                    }).join('');

                    if (window.lucide) lucide.createIcons();
                }
            })
            .catch(() => {});
    }

    window.handleNotificationClick = function(notifId, tenderId) {
        fetch('/api/notifications/mark-read', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notification_ids: [notifId] })
        }).then(() => {
            pollNotifications();
            if (tenderId) {
                const notifPanel = document.getElementById('notifPanel');
                if (notifPanel) notifPanel.classList.add('hidden');
                openTenderFromDeadline(tenderId);
            }
        });
    };

    function formatTimeAgo(isoString) {
        if (!isoString) return 'Just now';
        const diffMs = new Date().getTime() - new Date(isoString).getTime();
        const mins = Math.floor(diffMs / 60000);
        if (mins < 1) return 'Just now';
        if (mins < 60) return `${mins}m ago`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours}h ago`;
        const days = Math.floor(hours / 24);
        return `${days}d ago`;
    }

    function checkAndTriggerDesktopAlert() {
        if (!('Notification' in window)) return;
        if (Notification.permission === 'granted') {
            fetch('/api/notifications')
                .then(res => res.json())
                .then(data => {
                    if (data.success && data.notifications && data.notifications.length > 0) {
                        const latest = data.notifications[0];
                        new Notification(`TenderMind AI: ${latest.title}`, {
                            body: latest.message,
                            icon: '/static/favicon.ico'
                        });
                    }
                });
        }
    }

    // --------------------------------------------------------------------------
    // 9. DEADLINE MODALS & USER ACTIONS
    // --------------------------------------------------------------------------
    function initDeadlineModals() {
        // Confirm Modal
        const closeConfirmBtn = document.getElementById('closeDeadlineConfirmModalBtn');
        const confirmBtn = document.getElementById('dcmConfirmBtn');
        const editDetailsBtn = document.getElementById('dcmEditBtn');

        if (closeConfirmBtn) {
            closeConfirmBtn.addEventListener('click', () => {
                const modal = document.getElementById('deadlineConfirmModal');
                if (modal) modal.classList.add('hidden');
            });
        }

        if (confirmBtn) {
            confirmBtn.addEventListener('click', () => {
                if (!pendingDeadlineConfirmData) return;
                const payload = {
                    tender_id: pendingDeadlineConfirmData.doc_id,
                    title: pendingDeadlineConfirmData.tender_title,
                    organization: pendingDeadlineConfirmData.organization,
                    submission_deadline: pendingDeadlineConfirmData.submission_deadline,
                    opening_datetime: pendingDeadlineConfirmData.opening_datetime,
                    timezone: pendingDeadlineConfirmData.timezone || 'Asia/Karachi',
                    source_page: pendingDeadlineConfirmData.submission_deadline_source_page || 1,
                    file_name: pendingDeadlineConfirmData.file_name,
                    detected_raw: pendingDeadlineConfirmData
                };

                fetch('/api/deadlines/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(data => {
                    const modal = document.getElementById('deadlineConfirmModal');
                    if (modal) modal.classList.add('hidden');

                    if (data.success) {
                        showToast(`✓ Deadline confirmed for "${payload.title}"`);
                        loadDeadlines();
                        loadDeadlinesSummary();
                        loadDocumentsLibrary();
                        pollNotifications();
                    } else {
                        showError(data.error || 'Failed to confirm deadline.');
                    }
                })
                .catch(() => showError('Network error confirming deadline.'));
            });
        }

        if (editDetailsBtn) {
            editDetailsBtn.addEventListener('click', () => {
                const modal = document.getElementById('deadlineConfirmModal');
                if (modal) modal.classList.add('hidden');
                if (pendingDeadlineConfirmData) {
                    openDeadlineEditModal({
                        id: pendingDeadlineConfirmData.doc_id,
                        title: pendingDeadlineConfirmData.tender_title,
                        organization: pendingDeadlineConfirmData.organization,
                        submission_deadline: pendingDeadlineConfirmData.submission_deadline,
                        opening_datetime: pendingDeadlineConfirmData.opening_datetime,
                        timezone: pendingDeadlineConfirmData.timezone || 'Asia/Karachi',
                        submission_deadline_source_page: pendingDeadlineConfirmData.submission_deadline_source_page || 1,
                        file_name: pendingDeadlineConfirmData.file_name
                    }, false);
                }
            });
        }

        // Edit / Manual Modal
        const closeEditBtn = document.getElementById('closeDeadlineEditModalBtn');
        const cancelEditBtn = document.getElementById('demCancelBtn');
        const editForm = document.getElementById('deadlineEditForm');

        if (closeEditBtn) closeEditBtn.addEventListener('click', () => document.getElementById('deadlineEditModal').classList.add('hidden'));
        if (cancelEditBtn) cancelEditBtn.addEventListener('click', () => document.getElementById('deadlineEditModal').classList.add('hidden'));

        if (editForm) {
            editForm.addEventListener('submit', (e) => {
                e.preventDefault();
                const tenderId = document.getElementById('demTenderId') ? document.getElementById('demTenderId').value : '';
                const title = document.getElementById('demTitle') ? document.getElementById('demTitle').value.trim() : '';
                const org = (document.getElementById('demOrg') ? document.getElementById('demOrg').value.trim() : '') || 'Not specified';
                const dateVal = document.getElementById('demDate') ? document.getElementById('demDate').value : '';
                const timeVal = (document.getElementById('demTime') ? document.getElementById('demTime').value : '') || '12:00';
                const tz = (document.getElementById('demTimezone') ? document.getElementById('demTimezone').value : '') || 'Asia/Karachi';
                const pageNum = parseInt((document.getElementById('demSourcePage') ? document.getElementById('demSourcePage').value : '1') || '1', 10);

                const submission_deadline = `${dateVal}T${timeVal}:00`;

                // Reminder checkboxes
                const reminder_config = [
                    { offset: '7d', label: '7 days before', hours: 24 * 7, enabled: document.getElementById('remCheck7d').checked },
                    { offset: '3d', label: '3 days before', hours: 24 * 3, enabled: document.getElementById('remCheck3d').checked },
                    { offset: '24h', label: '24 hours before', hours: 24, enabled: document.getElementById('remCheck24h').checked },
                    { offset: '6h', label: '6 hours before', hours: 6, enabled: document.getElementById('remCheck6h').checked },
                    { offset: '1h', label: '1 hour before', hours: 1, enabled: document.getElementById('remCheck1h').checked }
                ];

                const customEnabled = document.getElementById('remCustomEnable').checked;
                const customVal = parseFloat(document.getElementById('remCustomValue').value || '1');
                const customUnit = document.getElementById('remCustomUnit').value || 'hours';
                const custom_reminders = customEnabled ? [{ value: customVal, unit: customUnit, enabled: true }] : [];

                const notification_channels = ['in_app'];
                if (document.getElementById('chanBrowser').checked) {
                    notification_channels.push('browser');
                    // Request browser permission if needed
                    if ('Notification' in window && Notification.permission === 'default') {
                        Notification.requestPermission();
                    }
                }

                const payload = {
                    title,
                    organization: org,
                    submission_deadline,
                    timezone: tz,
                    source_page: pageNum,
                    reminder_config,
                    custom_reminders,
                    notification_channels
                };

                const isNew = !tenderId;
                const url = isNew ? '/api/deadlines/manual' : `/api/deadlines/${tenderId}`;
                const method = isNew ? 'POST' : 'PUT';

                fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(data => {
                    document.getElementById('deadlineEditModal').classList.add('hidden');
                    if (data.success) {
                        showToast(`✓ Deadline saved for "${title}"`);
                        loadDeadlines();
                        loadDeadlinesSummary();
                        loadDocumentsLibrary();
                        pollNotifications();
                    } else {
                        showError(data.error || 'Failed to save deadline.');
                    }
                })
                .catch(() => showError('Network error saving deadline.'));
            });
        }

        // Reminder Settings Modal
        const closeSettingsBtn = document.getElementById('closeReminderSettingsModalBtn');
        const cancelSettingsBtn = document.getElementById('rsmCancelBtn');
        const saveSettingsBtn = document.getElementById('rsmSaveBtn');
        const reqPermBtn = document.getElementById('rsmReqPermBtn');

        if (closeSettingsBtn) closeSettingsBtn.addEventListener('click', () => document.getElementById('reminderSettingsModal').classList.add('hidden'));
        if (cancelSettingsBtn) cancelSettingsBtn.addEventListener('click', () => document.getElementById('reminderSettingsModal').classList.add('hidden'));

        if (reqPermBtn) {
            reqPermBtn.addEventListener('click', () => {
                if ('Notification' in window) {
                    Notification.requestPermission().then(p => {
                        if (p === 'granted') {
                            reqPermBtn.classList.add('hidden');
                            showToast('Browser notification permission granted.');
                        }
                    });
                }
            });
        }

        if (saveSettingsBtn) {
            saveSettingsBtn.addEventListener('click', () => {
                if (!pendingSettingsTenderId) return;

                fetch(`/api/deadlines/${pendingSettingsTenderId}`)
                    .then(res => res.json())
                    .then(data => {
                        if (!data.success || !data.tender) return;
                        const t = data.tender;

                        const reminder_config = [
                            { offset: '7d', label: '7 days before', hours: 24 * 7, enabled: document.getElementById('rsmCheck7d').checked },
                            { offset: '3d', label: '3 days before', hours: 24 * 3, enabled: document.getElementById('rsmCheck3d').checked },
                            { offset: '24h', label: '24 hours before', hours: 24, enabled: document.getElementById('rsmCheck24h').checked },
                            { offset: '6h', label: '6 hours before', hours: 6, enabled: document.getElementById('rsmCheck6h').checked },
                            { offset: '1h', label: '1 hour before', hours: 1, enabled: document.getElementById('rsmCheck1h').checked }
                        ];

                        const customEnabled = document.getElementById('rsmCustomEnable').checked;
                        const customVal = parseFloat(document.getElementById('rsmCustomValue').value || '1');
                        const customUnit = document.getElementById('rsmCustomUnit').value || 'hours';
                        const custom_reminders = customEnabled ? [{ value: customVal, unit: customUnit, enabled: true }] : [];

                        const notification_channels = ['in_app'];
                        if (document.getElementById('rsmBrowser').checked) {
                            notification_channels.push('browser');
                        }

                        return fetch(`/api/deadlines/${pendingSettingsTenderId}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                title: t.title,
                                organization: t.organization,
                                submission_deadline: t.submission_deadline,
                                opening_datetime: t.opening_datetime,
                                timezone: t.timezone,
                                source_page: t.submission_deadline_source_page,
                                reminder_config,
                                custom_reminders,
                                notification_channels
                            })
                        });
                    })
                    .then(res => res ? res.json() : null)
                    .then(resData => {
                        document.getElementById('reminderSettingsModal').classList.add('hidden');
                        if (resData && resData.success) {
                            showToast('✓ Reminder settings updated.');
                            loadDeadlines();
                        }
                    })
                    .catch(() => showError('Failed to update reminder settings.'));
            });
        }

        // Delete Modal
        const closeDelBtn = document.getElementById('closeDeleteDeadlineModalBtn');
        const cancelDelBtn = document.getElementById('cancelDeleteDeadlineBtn');
        const confirmDelBtn = document.getElementById('confirmDeleteDeadlineBtn');

        if (closeDelBtn) closeDelBtn.addEventListener('click', () => document.getElementById('deleteDeadlineModal').classList.add('hidden'));
        if (cancelDelBtn) cancelDelBtn.addEventListener('click', () => document.getElementById('deleteDeadlineModal').classList.add('hidden'));

        if (confirmDelBtn) {
            confirmDelBtn.addEventListener('click', () => {
                if (!pendingDeleteTenderId) return;
                fetch(`/api/deadlines/${pendingDeleteTenderId}`, { method: 'DELETE' })
                    .then(res => res.json())
                    .then(data => {
                        document.getElementById('deleteDeadlineModal').classList.add('hidden');
                        if (data.success) {
                            showToast('Tender deadline removed.');
                            loadDeadlines();
                            loadDeadlinesSummary();
                            loadDocumentsLibrary();
                        } else {
                            showError(data.error || 'Failed to remove deadline.');
                        }
                    })
                    .catch(() => showError('Network error removing deadline.'));
            });
        }
    }

    function showDeadlineConfirmModal(jobId, deadlineInfo, filename) {
        pendingDeadlineConfirmData = {
            ...deadlineInfo,
            doc_id: jobId,
            file_name: filename
        };

        const modal = document.getElementById('deadlineConfirmModal');
        const titleEl = document.getElementById('dcmTenderTitle');
        const orgEl = document.getElementById('dcmOrganization');
        const dateEl = document.getElementById('dcmDeadlineDate');
        const timeEl = document.getElementById('dcmDeadlineTime');
        const tzEl = document.getElementById('dcmTimezone');
        const pageEl = document.getElementById('dcmSourcePage');
        const sourceBadge = document.getElementById('dcmSourceBadge');
        const candidatesWrap = document.getElementById('dcmCandidatesWrap');
        const candidatesList = document.getElementById('dcmCandidatesList');

        if (titleEl) titleEl.textContent = deadlineInfo.tender_title || filename || 'Tender Document';
        if (orgEl) orgEl.textContent = deadlineInfo.organization || 'Institute of Management Sciences';

        // Parse date display
        if (deadlineInfo.submission_deadline) {
            const dt = new Date(deadlineInfo.submission_deadline);
            if (!isNaN(dt.getTime())) {
                if (dateEl) dateEl.textContent = dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
                if (timeEl) timeEl.textContent = dt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
            }
        }

        if (tzEl) tzEl.textContent = `${deadlineInfo.timezone || 'Asia/Karachi'} (UTC+05:00)`;
        if (pageEl) pageEl.textContent = `Page ${deadlineInfo.submission_deadline_source_page || 1}`;

        if (sourceBadge) {
            sourceBadge.onclick = () => {
                modal.classList.add('hidden');
                viewTenderDocumentPage(jobId, deadlineInfo.submission_deadline_source_page || 1);
            };
        }

        // Handle multiple candidate dates
        if (deadlineInfo.candidates && deadlineInfo.candidates.length > 1 && candidatesWrap && candidatesList) {
            candidatesWrap.classList.remove('hidden');
            candidatesList.innerHTML = deadlineInfo.candidates.map((c, idx) => `
                <div class="dcm-candidate-item ${idx === 0 ? 'selected' : ''}" onclick="selectDeadlineCandidate(${idx})">
                    <span>${escapeHtml(c.date_str)} at ${escapeHtml(c.time_str || '12:00 PM')} (Page ${c.page})</span>
                    <span style="font-size: 0.72rem; opacity: 0.7;">${escapeHtml(c.raw_text)}</span>
                </div>
            `).join('');
        } else if (candidatesWrap) {
            candidatesWrap.classList.add('hidden');
        }

        if (modal) {
            modal.classList.remove('hidden');
            if (window.lucide) lucide.createIcons();
        }
    }

    window.selectDeadlineCandidate = function(index) {
        if (!pendingDeadlineConfirmData || !pendingDeadlineConfirmData.candidates) return;
        const cand = pendingDeadlineConfirmData.candidates[index];
        if (!cand) return;

        const dateEl = document.getElementById('dcmDeadlineDate');
        const timeEl = document.getElementById('dcmDeadlineTime');
        const pageEl = document.getElementById('dcmSourcePage');

        if (dateEl) dateEl.textContent = cand.date_str;
        if (timeEl) timeEl.textContent = cand.time_str || '12:00 PM';
        if (pageEl) pageEl.textContent = `Page ${cand.page}`;

        // Update pending data
        pendingDeadlineConfirmData.submission_deadline_source_page = cand.page;

        const items = document.querySelectorAll('.dcm-candidate-item');
        items.forEach((it, idx) => {
            if (idx === index) it.classList.add('selected');
            else it.classList.remove('selected');
        });
    };

    function openDeadlineEditModal(tenderData, isNew = false) {
        const modal = document.getElementById('deadlineEditModal');
        const titleModal = document.getElementById('demModalTitle');
        const inputId = document.getElementById('demTenderId');
        const inputTitle = document.getElementById('demTitle');
        const inputOrg = document.getElementById('demOrg');
        const inputDate = document.getElementById('demDate');
        const inputTime = document.getElementById('demTime');
        const inputTz = document.getElementById('demTimezone');
        const inputPage = document.getElementById('demSourcePage');

        if (titleModal) titleModal.textContent = isNew ? 'Add Manual Tender Deadline' : 'Edit Tender Deadline';

        if (isNew) {
            if (inputId) inputId.value = '';
            if (inputTitle) inputTitle.value = '';
            if (inputOrg) inputOrg.value = '';
            if (inputDate) {
                // Default date to 7 days from now
                const future = new Date();
                future.setDate(future.getDate() + 7);
                inputDate.value = future.toISOString().split('T')[0];
            }
            if (inputTime) inputTime.value = '12:00';
            if (inputTz) inputTz.value = 'Asia/Karachi';
            if (inputPage) inputPage.value = '1';

            // Default checkboxes: 3 days and 1 day before only
            if (document.getElementById('remCheck7d')) document.getElementById('remCheck7d').checked = false;
            if (document.getElementById('remCheck3d')) document.getElementById('remCheck3d').checked = true;
            if (document.getElementById('remCheck24h')) document.getElementById('remCheck24h').checked = true;
            if (document.getElementById('remCheck6h')) document.getElementById('remCheck6h').checked = false;
            if (document.getElementById('remCheck1h')) document.getElementById('remCheck1h').checked = false;
        } else if (tenderData) {
            if (inputId) inputId.value = tenderData.id || '';
            if (inputTitle) inputTitle.value = tenderData.title || '';
            if (inputOrg) inputOrg.value = tenderData.organization || '';
            
            if (tenderData.submission_deadline && inputDate) {
                const parts = tenderData.submission_deadline.split('T');
                inputDate.value = parts[0];
                if (parts[1] && inputTime) {
                    inputTime.value = parts[1].slice(0, 5);
                }
            }
            if (inputTz) inputTz.value = tenderData.timezone || 'Asia/Karachi';
            if (inputPage) inputPage.value = tenderData.submission_deadline_source_page || 1;

            if (tenderData.reminders && Array.isArray(tenderData.reminders)) {
                const offsets = tenderData.reminders.map(r => r.reminder_offset || r.offset);
                if (document.getElementById('remCheck7d')) document.getElementById('remCheck7d').checked = offsets.includes('7d');
                if (document.getElementById('remCheck3d')) document.getElementById('remCheck3d').checked = offsets.includes('3d');
                if (document.getElementById('remCheck24h')) document.getElementById('remCheck24h').checked = offsets.includes('24h');
                if (document.getElementById('remCheck6h')) document.getElementById('remCheck6h').checked = offsets.includes('6h');
                if (document.getElementById('remCheck1h')) document.getElementById('remCheck1h').checked = offsets.includes('1h');
            }
        }

        if (modal) {
            modal.classList.remove('hidden');
            if (window.lucide) lucide.createIcons();
        }
    }

    window.editTenderDeadlineById = function(tenderId) {
        fetch(`/api/deadlines/${tenderId}`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.tender) {
                    openDeadlineEditModal(data.tender, false);
                }
            });
    };

    window.openReminderSettingsModal = function(tenderId) {
        pendingSettingsTenderId = tenderId;
        const modal = document.getElementById('reminderSettingsModal');
        const titleEl = document.getElementById('rsmTenderTitle');
        const dlEl = document.getElementById('rsmDeadlineText');
        const permBtn = document.getElementById('rsmReqPermBtn');

        if ('Notification' in window && Notification.permission !== 'granted' && permBtn) {
            permBtn.classList.remove('hidden');
        } else if (permBtn) {
            permBtn.classList.add('hidden');
        }

        fetch(`/api/deadlines/${tenderId}`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.tender) {
                    const t = data.tender;
                    if (titleEl) titleEl.textContent = t.title;
                    if (dlEl) dlEl.textContent = `Submission Deadline: ${t.display ? t.display.formatted : t.submission_deadline}`;

                    if (t.reminders && Array.isArray(t.reminders)) {
                        const offsets = t.reminders.map(r => r.reminder_offset || r.offset);
                        if (document.getElementById('rsmCheck7d')) document.getElementById('rsmCheck7d').checked = offsets.includes('7d');
                        if (document.getElementById('rsmCheck3d')) document.getElementById('rsmCheck3d').checked = offsets.includes('3d');
                        if (document.getElementById('rsmCheck24h')) document.getElementById('rsmCheck24h').checked = offsets.includes('24h');
                        if (document.getElementById('rsmCheck6h')) document.getElementById('rsmCheck6h').checked = offsets.includes('6h');
                        if (document.getElementById('rsmCheck1h')) document.getElementById('rsmCheck1h').checked = offsets.includes('1h');
                    } else {
                        if (document.getElementById('rsmCheck7d')) document.getElementById('rsmCheck7d').checked = false;
                        if (document.getElementById('rsmCheck3d')) document.getElementById('rsmCheck3d').checked = true;
                        if (document.getElementById('rsmCheck24h')) document.getElementById('rsmCheck24h').checked = true;
                        if (document.getElementById('rsmCheck6h')) document.getElementById('rsmCheck6h').checked = false;
                        if (document.getElementById('rsmCheck1h')) document.getElementById('rsmCheck1h').checked = false;
                    }

                    if (modal) {
                        modal.classList.remove('hidden');
                        if (window.lucide) lucide.createIcons();
                    }
                }
            });
    };

    window.openDeleteDeadlineModal = function(tenderId, tenderTitle) {
        pendingDeleteTenderId = tenderId;
        const modal = document.getElementById('deleteDeadlineModal');
        const titleEl = document.getElementById('delModalTenderTitle');
        if (titleEl) titleEl.textContent = tenderTitle;
        if (modal) {
            modal.classList.remove('hidden');
            if (window.lucide) lucide.createIcons();
        }
    };

    window.openTenderFromDeadline = function(tenderId) {
        if (tenderId.startsWith('manual_')) {
            showToast('This is an external manual tender entry.');
            return;
        }
        selectDocument(tenderId);
    };

    window.viewTenderDocumentPage = function(docId, pageNum) {
        if (docId.startsWith('manual_')) return;
        selectDocument(docId);
        setTimeout(() => {
            if (typeof goToPage === 'function') {
                goToPage(pageNum);
            }
        }, 600);
    };

    window.showDeadlineConfirmModal = showDeadlineConfirmModal;
    window.loadDeadlines = loadDeadlines;
    window.loadDeadlinesSummary = loadDeadlinesSummary;

    // --------------------------------------------------------------------------
    // GLOBE BUFFERING LOADER CONTROLLER (GLOBAL IT SOLUTIONS)
    // --------------------------------------------------------------------------
    const globalGlobeLoader = document.getElementById('globalGlobeLoader');
    const globeLoaderTitle = document.getElementById('globeLoaderTitle');
    const globeLoaderSub = document.getElementById('globeLoaderSub');
    const globeLoaderFill = document.getElementById('globeLoaderFill');
    const globeLoaderStatus = document.getElementById('globeLoaderStatus');
    const globeLoaderPercent = document.getElementById('globeLoaderPercent');

    function showGlobeLoader(title = 'Processing Document...', subtitle = 'GLOBAL IT SOLUTIONS AI ENGINE') {
        if (globeLoaderTitle && title) globeLoaderTitle.textContent = title;
        if (globeLoaderSub && subtitle) globeLoaderSub.textContent = subtitle;
        updateGlobeLoader(0, 'Initializing...');
        if (globalGlobeLoader) globalGlobeLoader.classList.remove('hidden');
        if (window.lucide) lucide.createIcons();
    }

    function updateGlobeLoader(percent, statusText) {
        const pct = Math.min(100, Math.max(0, Math.round(percent)));
        if (globeLoaderFill) globeLoaderFill.style.width = `${pct}%`;
        if (globeLoaderPercent) globeLoaderPercent.textContent = `${pct}%`;
        if (globeLoaderStatus && statusText) globeLoaderStatus.textContent = statusText;
    }

    function hideGlobeLoader() {
        if (globalGlobeLoader) globalGlobeLoader.classList.add('hidden');
    }

    window.showGlobeLoader = showGlobeLoader;
    window.updateGlobeLoader = updateGlobeLoader;
    window.hideGlobeLoader = hideGlobeLoader;
});

