#!/usr/bin/env python3

import argparse
import json
import os
import pickle
import sys

import faiss
import numpy as np

# -----------------------------
# Embedders (shared with vectorize.py)
# -----------------------------

class Embedder:
    def encode(self, texts):
        raise NotImplementedError


class OpenAIEmbedder(Embedder):
    def __init__(self, model, api_key):
        print("🔑 Initializing OpenAI embedder")
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def encode(self, texts):
        print(f"🧠 Calling OpenAI embeddings API ({self.model})")
        resp = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        return [d.embedding for d in resp.data]


class HFEmbedder(Embedder):
    def __init__(self, model, device="cpu"):
        print("🧠 Initializing HuggingFace embedder")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model, device=device)
        self.model_name = model

    def encode(self, texts):
        print(f"🧠 Encoding with HF model ({self.model_name})")
        return self.model.encode(texts, convert_to_numpy=True).tolist()


# -----------------------------
# Embedder factory
# -----------------------------

def load_embedder(meta, api_key=None, device="cpu"):
    provider = meta.get("provider")

    # Backward compatibility
    if provider is None:
        if meta.get("model", "").startswith("text-embedding-"):
            provider = "openai"
        else:
            provider = "hf"

    print("🧠 Selecting embedder")
    print(f"   Provider: {provider}")
    print(f"   Model: {meta.get('model')}")

    if provider == "openai":
        if not api_key:
            raise RuntimeError("❌ OpenAI API key required for this vector store")
        return OpenAIEmbedder(meta["model"], api_key)

    if provider == "hf":
        return HFEmbedder(meta["model"], device=device)

    raise RuntimeError(f"❌ Unsupported embedding provider: {provider}")


# -----------------------------
# Main retrieval logic
# -----------------------------

def main():
    parser = argparse.ArgumentParser(description="Hybrid FAISS + BM25 retrieval")
    parser.add_argument("--store", required=True, help="Path to vector store folder")
    parser.add_argument("--query", required=True, help="Query string")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--api-key", help="OpenAI API key (if required)")

    args = parser.parse_args()

    store = args.store
    meta_path = os.path.join(store, "metadata.json")
    index_path = os.path.join(store, "index.faiss")
    chunks_path = os.path.join(store, "chunks.pkl")
    bm25_path = os.path.join(store, "bm25.pkl")

    print("📂 Vector store:", store)

    # ---- Metadata ----
    print("📄 Loading metadata...")
    if not os.path.exists(meta_path):
        print("❌ metadata.json not found")
        sys.exit(1)

    with open(meta_path) as f:
        meta = json.load(f)

    print("✅ Metadata loaded")
    print(f"   Model: {meta.get('model')}")
    print(f"   Dimension: {meta.get('dimension')}")

    # ---- FAISS ----
    print("🔍 Loading FAISS index...")
    index = faiss.read_index(index_path)
    print("✅ FAISS index loaded")

    # ---- Chunks ----
    print("📦 Loading chunks...")
    with open(chunks_path, "rb") as f:
        chunks = pickle.load(f)
    print(f"✅ Loaded {len(chunks)} chunks")

    # ---- BM25 ----
    print("📚 Loading BM25 index...")
    with open(bm25_path, "rb") as f:
        bm25 = pickle.load(f)
    print("✅ BM25 loaded")

    # ---- Embedder ----
    embedder = load_embedder(meta, api_key=args.api_key)

    # ---- Embed query ----
    print("🧠 Embedding query...")
    qvec = np.array(embedder.encode([args.query]), dtype="float32")

    # ---- FAISS search ----
    print("📐 Running FAISS search...")
    D, I = index.search(qvec, args.top_k)

    faiss_scores = 1 / (1 + D[0])
    faiss_scores /= (faiss_scores.max() + 1e-9)

    # ---- BM25 search ----
    print("🔎 Running BM25 search...")
    tokens = args.query.lower().split()
    bm25_scores = np.array(bm25.get_scores(tokens))
    bm25_scores /= (bm25_scores.max() + 1e-9)

    top_bm25 = np.argsort(bm25_scores)[-args.top_k:][::-1]

    # ---- Merge ----
    print("🔗 Merging FAISS + BM25 results...")
    combined = {}

    for i, idx in enumerate(I[0]):
        combined[idx] = faiss_scores[i] * 0.7

    for idx in top_bm25:
        combined[idx] = combined.get(idx, 0) + bm25_scores[idx] * 0.3

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)

    # ---- Output ----
    print("\n🧾 Hybrid retrieval results:\n")
    context = []
    for rank, (idx, score) in enumerate(ranked[:args.top_k]):
        chunk = chunks[idx]
        context.append(chunk["text"])
        print(f"--- Rank {rank+1} | Chunk {idx} | Score {score:.4f} ---")
        print(chunk["text"][:500])
        print()

    final_context = "\n\n".join(context)

    print("=" * 80)
    print("📎 Final concatenated context (truncated):")
    print(final_context[:1000])
    print("=" * 80)


if __name__ == "__main__":
    main()
