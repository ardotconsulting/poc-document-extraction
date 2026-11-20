#!/usr/bin/env python3
"""Document Extraction POC — a small web app that demonstrates OCR with Tesseract.

Users pick from bundled sample documents (invoice, receipt, form) and see the
OCR text plus some heuristically extracted fields. No uploads, no LLM — the
blog post's Ollama step is noted on the page but not part of the demo.
"""
import http.server
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from PIL import Image, ImageEnhance

PORT = 8000
BASE_DIR = Path(__file__).parent
SAMPLES_DIR = BASE_DIR / "samples"

# ── OCR ──────────────────────────────────────────────────────────────────────

def run_ocr(image_path: str) -> str:
    """Run tesseract on an image and return the text."""
    result = subprocess.run(
        ["tesseract", image_path, "stdout", "--psm", "6"],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()

def preprocess_image(src: str) -> str:
    """Grayscale + contrast enhancement to improve OCR results."""
    img = Image.open(src).convert("L")
    img = ImageEnhance.Contrast(img).enhance(1.8)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return tmp.name

# ── Field extraction heuristics ──────────────────────────────────────────────

def extract_fields(text: str, doc_type: str) -> list:
    """Heuristically extract structured fields from OCR text."""
    fields = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    def find(patterns):
        for pat in patterns:
            for line in lines:
                m = re.search(pat, line, re.I)
                if m and m.lastindex:
                    return m.group(1)
        return None

    # Common fields
    invoice_no = find([
        r"(?:invoice|inv)\s*(?:no|number|#)\s*:?\s*([A-Z0-9\-]+)",
        r"(?:inv|invoice)\s*[:#]\s*([A-Z0-9\-]+)",
    ])
    if invoice_no:
        fields.append({"label": "Invoice Number", "value": invoice_no})

    date = find([
        r"(?:date|dated)\s*:?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})",
        r"(?:date|dated)\s*:?\s*(\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})",
    ])
    if date:
        fields.append({"label": "Date", "value": date})

    total = find([
        r"(?:total|amount due|balance due|grand total)\s*:?\s*\$?\s*([\d,]+\.?\d*)",
    ])
    if total:
        fields.append({"label": "Total", "value": f"${total}"})

    # Receipt-specific
    if doc_type == "receipt":
        store = lines[0] if lines else None
        if store:
            fields.append({"label": "Store", "value": store})
        subtotal = find([r"(?:subtotal|sub\s*total)\s*:?\s*\$?\s*([\d,]+\.?\d*)"])
        if subtotal:
            fields.append({"label": "Subtotal", "value": f"${subtotal}"})
        tax = find([r"(?:tax|sales tax)\s*:?\s*\$?\s*([\d,]+\.?\d*)"])
        if tax:
            fields.append({"label": "Tax", "value": f"${tax}"})
        change = find([r"(?:change|change due)\s*:?\s*\$?\s*([\d,]+\.?\d*)"])
        if change:
            fields.append({"label": "Change", "value": f"${change}"})

    # Invoice-specific
    if doc_type == "invoice":
        bill_to = find([r"(?:bill to|billed to|to)\s*:?\s*(.+)"])
        if bill_to:
            fields.append({"label": "Bill To", "value": bill_to})
        due = find([r"(?:due date|payment due)\s*:?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})"])
        if due:
            fields.append({"label": "Due Date", "value": due})

    # Form-specific
    if doc_type == "form":
        name = find([r"(?:name|full name)\s*:?\s*(.+)"])
        if name:
            fields.append({"label": "Name", "value": name})
        email = find([r"(?:email|e-mail)\s*:?\s*(\S+@\S+)"])
        if email:
            fields.append({"label": "Email", "value": email})
        phone = find([r"(?:phone|tel|telephone)\s*:?\s*([\d\-\(\)\s]+)"])
        if phone:
            fields.append({"label": "Phone", "value": phone.strip()})

    return fields

# ── Sample documents ─────────────────────────────────────────────────────────

def get_samples() -> list:
    samples = []
    if SAMPLES_DIR.exists():
        for f in sorted(SAMPLES_DIR.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".tiff", ".bmp"):
                meta_file = f.with_suffix(".json")
                doc_type = "document"
                label = f.stem.replace("_", " ").title()
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text())
                    doc_type = meta.get("type", "document")
                    label = meta.get("label", label)
                samples.append({
                    "id": f.stem,
                    "label": label,
                    "type": doc_type,
                    "image": f"/samples/{f.name}",
                })
    return samples

# ── HTTP server ──────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_text(self, text, code=200, content_type="text/html; charset=utf-8"):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path == "":
            self.serve_index()
        elif self.path == "/api/samples":
            self.send_text(json.dumps(get_samples()), content_type="application/json")
        elif self.path.startswith("/api/ocr/"):
            sample_id = self.path.replace("/api/ocr/", "")
            self.serve_ocr(sample_id)
        elif self.path.startswith("/samples/"):
            filename = self.path.replace("/samples/", "")
            filepath = SAMPLES_DIR / filename
            if filepath.exists():
                ext = filepath.suffix.lower()
                ct = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                      "tiff": "image/tiff", "bmp": "image/bmp"}.get(ext.lstrip("."), "application/octet-stream")
                self.send_file(filepath, ct)
            else:
                self.send_text("Not found", 404)
        else:
            self.send_text("Not found", 404)

    def serve_index(self):
        self.send_text(PAGE_HTML)

    def serve_ocr(self, sample_id):
        for ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            filepath = SAMPLES_DIR / f"{sample_id}{ext}"
            if filepath.exists():
                meta_file = filepath.with_suffix(".json")
                doc_type = "document"
                if meta_file.exists():
                    meta = json.loads(meta_file.read_text())
                    doc_type = meta.get("type", "document")

                preprocessed = preprocess_image(str(filepath))
                ocr_text = run_ocr(preprocessed)
                os.unlink(preprocessed)

                fields = extract_fields(ocr_text, doc_type)

                response = {
                    "sample_id": sample_id,
                    "ocr_text": ocr_text,
                    "fields": fields,
                }
                self.send_text(json.dumps(response), content_type="application/json")
                return
        self.send_text(json.dumps({"error": "Sample not found"}), 404, "application/json")


PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Document Extraction — Tesseract OCR Demo</title>
<style>
:root{--bg:#1a1a2e;--card:#16213e;--accent:#0f3460;--text:#e0e0e0;--highlight:#e94560;--green:#4ecca3;--border:#233}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:20px}
.container{max-width:1100px;margin:0 auto}
h1{color:var(--highlight);margin-bottom:8px;font-size:1.6rem}
.subtitle{color:#888;margin-bottom:24px;font-size:.9rem}
.note{background:var(--accent);border-left:3px solid var(--highlight);padding:12px 16px;border-radius:4px;margin-bottom:24px;font-size:.85rem}
.note a{color:var(--highlight)}
.samples{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}
.sample-btn{background:var(--card);border:1px solid var(--border);color:var(--text);padding:10px 20px;border-radius:6px;cursor:pointer;font-size:.9rem;transition:all .2s}
.sample-btn:hover{border-color:var(--highlight);background:var(--accent)}
.sample-btn.active{border-color:var(--highlight);background:var(--accent)}
.results{display:grid;grid-template-columns:1fr 1fr;gap:20px}
@media(max-width:768px){.results{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;overflow:hidden}
.panel h2{font-size:1.1rem;color:var(--green);margin-bottom:12px}
.image-preview img{max-width:100%;border-radius:4px;border:1px solid var(--border)}
.ocr-text{white-space:pre-wrap;font-family:'Courier New',monospace;font-size:.8rem;background:var(--bg);padding:12px;border-radius:4px;border:1px solid var(--border);max-height:300px;overflow-y:auto}
.fields{list-style:none}
.field-item{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)}
.field-label{color:#888;font-size:.85rem}
.field-value{color:var(--highlight);font-weight:600;font-size:.9rem}
.loading{text-align:center;padding:20px;color:#888}
.empty{text-align:center;padding:40px;color:#666}
.source-link{margin-top:24px;text-align:center;font-size:.85rem}
.source-link a{color:var(--highlight)}
</style>
</head>
<body>
<div class="container">
<h1>📄 Document Extraction Demo</h1>
<p class="subtitle">OCR with Tesseract — pick a sample document to see the extracted text and fields</p>
<div class="note">
This demo shows the <strong>OCR step</strong> from our blog post
<a href="https://www.ardotconsulting.com/blog/2026/11/08/ai-powered-document-extraction-turn-pdfs-into-structured-data-with-tesseract-and-ollama/" target="_blank">AI-Powered Document Extraction with Tesseract and Ollama</a>.
The LLM-based field extraction (Ollama) is not included here — it's too heavy for a shared demo server.
Instead, we use lightweight heuristics to pull out common fields like invoice numbers, dates, and totals.
</div>
<div class="samples" id="samples"><span class="loading">Loading samples...</span></div>
<div class="results" id="results" style="display:none">
<div class="panel">
<h2>Original Image</h2>
<div class="image-preview" id="image-preview"></div>
</div>
<div class="panel">
<h2>OCR Output</h2>
<div class="ocr-text" id="ocr-text"></div>
<h2 style="margin-top:16px">Extracted Fields</h2>
<ul class="fields" id="fields"></ul>
</div>
</div>
<div class="empty" id="empty">Select a sample document above to begin.</div>
<div class="source-link"><a href="https://github.com/ardotconsulting/poc-document-extraction" target="_blank">View source on GitHub</a></div>
</div>
<script>
const samplesEl=document.getElementById('samples');
const resultsEl=document.getElementById('results');
const emptyEl=document.getElementById('empty');
const imagePreview=document.getElementById('image-preview');
const ocrText=document.getElementById('ocr-text');
const fieldsEl=document.getElementById('fields');

async function loadSamples(){
  const r=await fetch('/api/samples');
  const samples=await r.json();
  samplesEl.innerHTML='';
  samples.forEach(s=>{
    const btn=document.createElement('button');
    btn.className='sample-btn';
    btn.textContent=s.label;
    btn.onclick=()=>selectSample(s,btn);
    samplesEl.appendChild(btn);
  });
  if(!samples.length)samplesEl.innerHTML='<p>No sample documents found.</p>';
}

async function selectSample(sample,btn){
  document.querySelectorAll('.sample-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  emptyEl.style.display='none';
  resultsEl.style.display='grid';
  imagePreview.innerHTML='<p class="loading">Loading image...</p>';
  ocrText.textContent='Running OCR...';
  fieldsEl.innerHTML='<li class="loading">Extracting fields...</li>';

  imagePreview.innerHTML='<img src="'+sample.image+'" alt="'+sample.label+'">';

  try{
    const r=await fetch('/api/ocr/'+sample.id);
    const data=await r.json();
    ocrText.textContent=data.ocr_text||'(no text extracted)';
    fieldsEl.innerHTML='';
    if(data.fields&&data.fields.length){
      data.fields.forEach(f=>{
        const li=document.createElement('li');
        li.className='field-item';
        li.innerHTML='<span class="field-label">'+f.label+'</span><span class="field-value">'+f.value+'</span>';
        fieldsEl.appendChild(li);
      });
    }else{
      fieldsEl.innerHTML='<li class="loading">No fields detected.</li>';
    }
  }catch(e){
    ocrText.textContent='Error: '+e.message;
    fieldsEl.innerHTML='';
  }
}

loadSamples();
</script>
</body>
</html>"""

if __name__ == "__main__":
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Document Extraction POC running on port {PORT}")
    server.serve_forever()
