from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

load_dotenv()

# Paths are relative to the backend/ directory (one level up from app/)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_APP_DIR)

CHROMA_DIR = os.path.join(BASE_DIR, ".chroma")
COLLECTION_NAME = "vedic_astrology"

KB_DIR = os.path.join(BASE_DIR, "knowledge_base")
PDF_PATH = os.path.join(KB_DIR, "Vedic_Astro_Corpus_pdf.pdf")
RAASHI_PATH = os.path.join(KB_DIR, "Raashi_Corpus.md")
NAKSHATRA_PATH = os.path.join(KB_DIR, "Nakshatra_Corpus.md")
NOTES_PATH = os.path.join(KB_DIR, "vedic_astrology_notes.md")


def ingest(force: bool = False) -> Chroma:
    """Load, split, embed and persist all knowledge-base documents.

    On subsequent calls the cached store is returned immediately unless force=True.
    """
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    if os.path.exists(CHROMA_DIR) and not force:
        vs = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=CHROMA_DIR,
        )
        count = vs._collection.count()
        if count > 0:
            print(f"[ingest] Vector store loaded from disk ({count} chunks).")
            return vs
        print("[ingest] Store directory found but empty — re-ingesting...")

    print("[ingest] Loading documents...")

    # --- 27 Nakshatras (PDF — structural/astronomical reference) ---
    if not os.path.exists(PDF_PATH):
        print(f"[ingest] ERROR: PDF not found at {PDF_PATH}")
        sys.exit(1)
    pdf_docs = PyPDFLoader(PDF_PATH).load()
    for doc in pdf_docs:
        doc.metadata["source"] = "nakshatra"
        doc.metadata["file_name"] = "Vedic_Astro_Corpus_pdf.pdf"

    # --- 27 Nakshatras (Markdown — detailed characteristics) ---
    if not os.path.exists(NAKSHATRA_PATH):
        print(f"[ingest] ERROR: Nakshatra corpus not found at {NAKSHATRA_PATH}")
        sys.exit(1)
    nakshatra_md_docs = TextLoader(NAKSHATRA_PATH, encoding="utf-8").load()
    for doc in nakshatra_md_docs:
        doc.metadata["source"] = "nakshatra"
        doc.metadata["file_name"] = "Nakshatra_Corpus.md"

    # --- 12 Raashi signs (Markdown) ---
    if not os.path.exists(RAASHI_PATH):
        print(f"[ingest] ERROR: Raashi corpus not found at {RAASHI_PATH}")
        sys.exit(1)
    raashi_docs = TextLoader(RAASHI_PATH, encoding="utf-8").load()
    for doc in raashi_docs:
        doc.metadata["source"] = "raashi"
        doc.metadata["file_name"] = "Raashi_Corpus.md"

    # --- Chart / house basics (Markdown) ---
    if not os.path.exists(NOTES_PATH):
        print(f"[ingest] ERROR: Notes not found at {NOTES_PATH}")
        sys.exit(1)
    notes_docs = TextLoader(NOTES_PATH, encoding="utf-8").load()
    for doc in notes_docs:
        doc.metadata["source"] = "general"
        doc.metadata["file_name"] = "vedic_astrology_notes.md"

    # --- Split ---
    # Larger chunks keep each nakshatra/raashi section intact for better retrieval
    pdf_splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100)
    md_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=120,
        separators=["\n---\n", "\n## ", "\n### ", "\n\n", "\n", " "],
    )

    pdf_chunks = pdf_splitter.split_documents(pdf_docs)
    nakshatra_md_chunks = md_splitter.split_documents(nakshatra_md_docs)
    raashi_chunks = md_splitter.split_documents(raashi_docs)
    notes_chunks = md_splitter.split_documents(notes_docs)

    all_chunks = pdf_chunks + nakshatra_md_chunks + raashi_chunks + notes_chunks

    print(f"[ingest]   Nakshatra PDF chunks    : {len(pdf_chunks)}")
    print(f"[ingest]   Nakshatra MD chunks     : {len(nakshatra_md_chunks)}")
    print(f"[ingest]   Raashi chunks           : {len(raashi_chunks)}")
    print(f"[ingest]   Notes chunks            : {len(notes_chunks)}")
    print(f"[ingest]   Total                   : {len(all_chunks)}")
    print("[ingest] Embedding and persisting (first run ~15–30 s)...")

    vectorstore = Chroma.from_documents(
        documents=all_chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=CHROMA_DIR,
    )
    print("[ingest] Done.\n")
    return vectorstore


def verify() -> None:
    """Print a breakdown of the stored collection."""
    from collections import Counter
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    vs = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR,
    )
    result = vs.get()
    sources = [m.get("source", "unknown") for m in result["metadatas"]]
    print("Collection contents:")
    for src, count in Counter(sources).items():
        print(f"  {src}: {count} chunks")
    print(f"  TOTAL: {len(sources)} chunks")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify()
    else:
        ingest(force="--force" in sys.argv)
