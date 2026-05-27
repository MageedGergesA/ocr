"""Document extraction — provider-agnostic.

Two modes:
  - auto   : model detects the document type and extracts whatever fields belong to it.
  - schema : caller supplies an exact field list (used by the Odoo module to map to model fields).

The actual model call lives in `llm` (Gemini or Anthropic, chosen by config), so cost/quality
routing happens there. Easy docs -> cheap model, hard/handwritten -> stronger model.
"""
import json

from . import llm


def _strip_code_fence(text: str) -> str:
    """Models sometimes wrap JSON in ```json ... ``` fences. Peel them off."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _call_model(file_bytes: bytes, media_type: str, prompt: str, hard: bool):
    """One vision call via the configured provider. Returns (text, truncated)."""
    return llm.generate_from_document(file_bytes, media_type, prompt, hard)


def _run(file_bytes: bytes, media_type: str, prompt: str, hard: bool) -> dict:
    """Call the model and parse a JSON object out of the reply."""
    text, truncated = _call_model(file_bytes, media_type, prompt, hard)
    try:
        return json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        if truncated:
            raise ValueError(
                "the response was truncated — this document is unusually large/complex. "
                "Try splitting the PDF or extracting fewer fields."
            )
        raise


def run_text(file_bytes: bytes, media_type: str, prompt: str, hard: bool = False) -> str:
    """Run a service whose output is plain text (OCR, translation, summary…)."""
    text, _ = _call_model(file_bytes, media_type, prompt, hard)
    return _strip_code_fence(text) if text.strip().startswith("```") else text.strip()


def chat(document_text: str, question: str, history: list | None = None) -> str:
    """Answer a question about a document, using its already-extracted text.
    Text-only call (no re-OCR) so it's cheap and fast."""
    system = (
        "You are a helpful assistant answering questions about a document. "
        "Use ONLY the document content below; if the answer isn't there, say so honestly. "
        "Reply in the user's language (Arabic or English), concisely.\n\n"
        f"=== DOCUMENT ===\n{document_text}"
    )
    return llm.generate_text(system, question, hard=True, max_tokens=1024, history=history)


def compare(text_a: str, text_b: str) -> str:
    """Compare two documents' text and report differences."""
    system = ("You compare two documents. Report clearly: what CHANGED, what is MISSING in "
              "either, and what MATCHES. Be specific and concise. Reply in the documents' language.")
    user = (f"=== DOCUMENT A ===\n{text_a}\n\n=== DOCUMENT B ===\n{text_b}\n\nCompare A and B.")
    return llm.generate_text(system, user, hard=True, max_tokens=1500)


def run_table(file_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Extract tabular data. Returns {"columns": [...], "rows": [[...], ...]}."""
    prompt = (
        "Extract the main table(s) from this document. Combine into ONE table. "
        "Keep cell text in its original language (Arabic/English). "
        'Return ONLY valid JSON in this shape: {"columns": ["..."], "rows": [["..."], ...]}. '
        "If there are no clear columns, use the first row's cells as columns."
    )
    data = _run(file_bytes, media_type, prompt, hard)
    return {"columns": data.get("columns", []), "rows": data.get("rows", [])}


def split_pdf_pages(pdf_bytes: bytes) -> list[bytes]:
    """Split a PDF into a list of single-page PDF byte blobs (for batch mode)."""
    import io

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        writer = PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        pages.append(buf.getvalue())
    return pages


def extract_auto(image_bytes: bytes, media_type: str, hard: bool = True) -> dict:
    """Detect the document type and extract every meaningful field automatically.

    Returns: {"document_type": str, "fields": {name: {"value": ..., "confidence": 0-1}}}
    """
    prompt = (
        "You are a document data-extraction system. Look at this document and:\n"
        "1. Identify its type (e.g., passport, national ID, invoice, receipt, contract, "
        "prescription, business card, OR a freeform letter / note / handwritten paragraph).\n"
        "2. Choose the right output form:\n"
        "   - If it is a STRUCTURED document (invoice, ID, form, receipt, card, etc.), "
        "extract its individual named fields. Choose names that fit the document; "
        "do not invent fields that are not present.\n"
        "   - If it is FREEFORM TEXT (a letter, note, essay, or any narrative prose with no "
        "structured fields), do NOT split it into invented fields. Instead return a single "
        'field named "full_text" whose value is the COMPLETE transcription, preserving line breaks.\n'
        "The document may be in Arabic, English, or handwritten. Keep every value EXACTLY in the "
        "document's original language and script — do NOT translate, transliterate, or add another "
        "language in parentheses. Be thorough and give your best reading for everything — do not skip "
        "unclear parts.\n"
        "Return ONLY valid JSON, no other text, in exactly this shape:\n"
        '{"document_type": "<type>", "fields": {"<field name>": '
        '{"value": <value>, "confidence": <0-1>}, ...}}'
    )
    return _run(image_bytes, media_type, prompt, hard)


def extract_schema(image_bytes: bytes, media_type: str, target_schema: dict,
                   hard: bool = True, hint: str = "") -> dict:
    """Extract a caller-defined set of fields.

    target_schema: {field_name: human description}
    hint: optional domain context prepended to the prompt (e.g. a prescription drug list).
    Returns: {field_name: {"value": ..., "confidence": 0-1}, ...}
    """
    field_list = "\n".join(f"- {k}: {v}" for k, v in target_schema.items())
    prompt = (
        (hint.strip() + "\n\n" if hint else "")
        + "Extract the following fields from this document. "
        "The document may be in Arabic, English, or handwritten. "
        "Keep every value EXACTLY in the document's original language and script — "
        "do NOT translate, transliterate, or add another language. "
        "Return ONLY valid JSON, no other text. "
        "For each field, return an object with 'value' and 'confidence' (0-1). "
        "If a field is not present, set its value to null.\n\n"
        f"Fields:\n{field_list}"
    )
    return _run(image_bytes, media_type, prompt, hard)
