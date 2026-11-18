"""Text extraction from uploads: .txt, .pdf (text layer) and .docx.
Scanned PDFs and images need OCR, which is not included."""
import io
import zipfile


def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except PdfReadError as e:
            raise ValueError(f"Could not read this PDF: {e}")
        if not text:
            raise ValueError("No text found in this PDF. It may be a scan; scanned PDFs need OCR first.")
        return text
    if name.endswith(".docx"):
        from docx import Document
        try:
            doc = Document(io.BytesIO(data))
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            raise ValueError(f"Could not read this DOCX file: {e}")
        parts = [p.text for p in doc.paragraphs]
        # Also extract text from tables (legal contracts often put clauses in tables)
        for table in doc.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        return "\n".join(parts).strip()
    if name.endswith(".txt") or not name:
        # Try BOM-marked encodings first, then fall back to UTF-8
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            try:
                return data.decode("utf-16").strip()
            except UnicodeDecodeError:
                pass
        try:
            return data.decode("utf-8-sig").strip()
        except UnicodeDecodeError:
            return data.decode("utf-8", errors="replace").strip()
    raise ValueError("Unsupported file type. Use .txt, .pdf or .docx.")
