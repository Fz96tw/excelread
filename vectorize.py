#!/usr/bin/env python3
import argparse
import os
import json
import faiss
import numpy as np
import re
import pickle
from pathlib import Path
from typing import List

import torch
import httpx
from rank_bm25 import BM25Okapi

# ---------------------------
# Environment / device setup
# ---------------------------

print("🔧 Initializing environment...")

IS_WSL = "microsoft" in os.uname().release.lower()

if not torch.cuda.is_available():
    print("⚠️  PyTorch GPU not available — using CPU only.")
    torch_device = "cpu"
else:
    print("🚀 GPU detected — using CUDA")
    torch_device = "cuda"

if IS_WSL and torch_device == "cpu":
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    print("🧊 CUDA disabled explicitly for WSL")

# ---------------------------
# Embedding Provider Interface
# ---------------------------

class Embedder:
    model_name: str
    provider: str

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

# ------------------------------------------------
# OpenAI Embedder
# ------------------------------------------------

class OpenAIEmbedder(Embedder):
    def __init__(self, model="text-embedding-3-small", api_key=None):
        print("🔑 Initializing OpenAI embedder...")
        from openai import OpenAI

        self.client = OpenAI(
            api_key=api_key,
            timeout=httpx.Timeout(
                connect=30.0,
                read=300.0,
                write=30.0,
                pool=30.0,
            ),
        )
        self.model_name = model
        self.provider = "openai"
        print(f"✅ OpenAI embedder ready ({model})")

    def embed(self, texts: List[str]) -> List[List[float]]:
        print(f"🧠 Embedding {len(texts)} chunks via OpenAI...")
        res = self.client.embeddings.create(
            model=self.model_name,
            input=texts
        )
        print("✅ OpenAI embeddings complete")
        return [d.embedding for d in res.data]

# ------------------------------------------------
# HuggingFace Embedder
# ------------------------------------------------

class HFEmbedder(Embedder):
    def __init__(self, model="sentence-transformers/all-MiniLM-L6-v2"):
        print("🧠 Initializing HuggingFace embedder...")
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model, device=torch_device)
        self.model_name = model
        self.provider = "hf"
        print(f"✅ HF embedder ready ({model})")

    def embed(self, texts: List[str]) -> List[List[float]]:
        print(f"🧠 Encoding {len(texts)} chunks with HF model...")
        vecs = self.model.encode(texts)
        print("✅ HF embeddings complete")
        return vecs.tolist()

# ---------------------------
# Utility
# ---------------------------

def normalize_name(text: str) -> str:
    base = text.lower()
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_")

def chunk_text(text: str, max_chars: int) -> List[str]:
    return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

# ---------------------------
# Build vector store
# ---------------------------

def build_vector_store(
    filepath: str,
    embedder: Embedder,
    out_root: Path,
    chunk_size: int
):
    try:
        print("=" * 80)
        print(f"📄 Processing file: {filepath}")

        file_stem = normalize_name(Path(filepath).stem)
        model_stem = normalize_name(embedder.model_name)
        out_dir = out_root / f"{file_stem}__{model_stem}"
        # ✅ Wipe the old index files before rebuilding
        if out_dir.exists():
            for stale in ["index.faiss", "chunks.pkl", "bm25.pkl", "metadata.json"]:
                (out_dir / stale).unlink(missing_ok=True)
            print("🗑️  Cleared stale index files for re-vectorization")

        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"📂 Output directory: {out_dir}")

        # ---- Load file ----
        print("📖 Reading file...")
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        print(f"✅ File loaded ({len(text)} characters)")

        # ---- Chunk ----
        print("✂️  Chunking text...")
        chunks_text = chunk_text(text, chunk_size)
        print(f"✅ Created {len(chunks_text)} chunks")

        # ---- Build chunk objects ----
        chunks = []
        for i, chunk in enumerate(chunks_text):
            chunks.append({
                "id": i,
                "text": chunk,
                "source_file": filepath,
            })

        # ---- Save chunks.pkl ----
        print("💾 Saving chunks.pkl...")
        with open(out_dir / "chunks.pkl", "wb") as f:
            pickle.dump(chunks, f)
        print("✅ chunks.pkl saved")

        # ---- BM25 ----
        print("📚 Building BM25 index...")
        tokenized_chunks = [
            c["text"].lower().split() for c in chunks
        ]
        bm25 = BM25Okapi(tokenized_chunks)

        with open(out_dir / "bm25.pkl", "wb") as f:
            pickle.dump(bm25, f)
        print("✅ BM25 index saved")

        # ---- Embeddings ----
        print("🧠 Embedding chunks...")
        embeddings = embedder.embed([c["text"] for c in chunks])
        xb = np.array(embeddings, dtype="float32")
        dim = xb.shape[1]
        print(f"✅ Embeddings complete (dimension={dim})")

        # ---- FAISS ----
        print("📐 Building FAISS index...")
        index = faiss.IndexFlatL2(dim)
        index.add(xb)

        faiss.write_index(index, str(out_dir / "index.faiss"))
        print("✅ FAISS index saved")

        # ---- Metadata ----
        print("📝 Writing metadata.json...")
        metadata = {
            "file": filepath,
            "provider": embedder.provider,
            "model": embedder.model_name,
            "num_chunks": len(chunks),
            "dimension": dim,
            "chunk_size": chunk_size,
            "has_bm25": True,
        }

        with open(out_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        print("✅ metadata.json saved")
        print("🎉 Vector store build complete")

    except Exception as e:
        print("❌ ERROR while processing file")
        print(e)
        raise

# ---------------------------
# CLI
# ---------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build FAISS + BM25 vector stores"
    )

    parser.add_argument("--files", nargs="+", required=True)
    parser.add_argument("--provider", required=True, choices=["openai", "hf"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--out", default="vectorstore")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--api-key")

    args = parser.parse_args()

    print("🚀 Starting vectorization")
    out_root = Path(args.out)
    out_root.mkdir(exist_ok=True)

    if args.provider == "openai":
        model = args.model or "text-embedding-3-small"
        embedder = OpenAIEmbedder(model=model, api_key=args.api_key)
    else:
        model = args.model or "sentence-transformers/all-MiniLM-L6-v2"
        embedder = HFEmbedder(model=model)

    for f in args.files:
        build_vector_store(
            filepath=f,
            embedder=embedder,
            out_root=out_root,
            chunk_size=args.chunk_size,
        )

    print("✅ All files processed successfully")

if __name__ == "__main__":
    main()
