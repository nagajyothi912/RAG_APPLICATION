import os
import tempfile

TMP_DOCS = tempfile.mkdtemp(prefix="rag-docs-")
os.environ["DOCS_DIR"] = TMP_DOCS
os.environ.setdefault("GROQ_API_KEY", "")
