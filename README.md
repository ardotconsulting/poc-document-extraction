# poc-document-extraction

Proof of concept for **AI-Powered Document Extraction with Tesseract and Ollama**.

🔗 Blog post: https://www.ardotconsulting.com/blog/2026/11/08/ai-powered-document-extraction-turn-pdfs-into-structured-data-with-tesseract-and-ollama/

## What it does

A small web app that demonstrates OCR with Tesseract. Users pick from bundled
sample documents (invoice, receipt, form) and see the extracted OCR text plus
heuristically extracted fields (invoice number, date, total, etc.).

The blog post's LLM-based extraction step (Ollama) is not included — it's too
heavy for a shared demo server. Instead, lightweight regex heuristics pull out
common fields.
