"""Document extraction (PDFs, Word, images, plain text).

`extractor.py` exposes one async function that takes raw bytes + a
filename and returns per-page text blocks. `doc_analyst` feeds these
blocks into the chunker before they go into the vector store.
"""
