"""
Retrieval module for searching vector stores.
"""
import os
import json
import faiss
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass
from vector_embedder import get_embedder


@dataclass
class SearchResult:
    """A single search result from the vector store."""
    chunk_text: str
    score: float  # Lower is better for L2 distance
    chunk_index: int
    url: str
    metadata: Dict


class VectorRetriever:
    """Retrieve relevant chunks from user's vector stores."""
    
    def __init__(self, user_id: str, config_dir: str = "./config"):
        self.user_id = user_id
        self.config_dir = config_dir
        self.embedder = get_embedder()
        self.user_dir = os.path.join(config_dir, user_id)
        self.vectors_dir = os.path.join(self.user_dir, "vectors")
        
    def _load_vector_store(self, url_dir: str) -> Tuple[faiss.Index, List[str], Dict]:
        """Load FAISS index, chunks, and metadata for a single URL."""
        index_path = os.path.join(url_dir, "index.faiss")
        chunks_path = os.path.join(url_dir, "chunks.json")
        metadata_path = os.path.join(url_dir, "metadata.json")
        
        # Load FAISS index
        if not os.path.exists(index_path):
            raise FileNotFoundError(f"Index not found: {index_path}")
        index = faiss.read_index(index_path)
        
        # Load chunks
        with open(chunks_path, "r") as f:
            chunks = json.load(f)
        
        # Load metadata
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
            
        return index, chunks, metadata
    
    def _get_all_url_dirs(self) -> List[Tuple[str, str]]:
        """Get all URL directories for this user."""
        if not os.path.exists(self.vectors_dir):
            return []
        
        url_dirs = []
        for url_folder in os.listdir(self.vectors_dir):
            full_path = os.path.join(self.vectors_dir, url_folder)
            if os.path.isdir(full_path):
                url_dirs.append((url_folder, full_path))
        
        return url_dirs
    
    def search(self, query: str, top_k: int = 5, filter_url: str = None) -> List[SearchResult]:
        """
        Search across all vector stores for relevant chunks.
        
        Args:
            query: Search query text
            top_k: Number of results to return per document
            filter_url: Optional URL to search only in specific document
            
        Returns:
            List of SearchResult objects, sorted by relevance (lowest score first)
        """
        # Encode query
        query_embedding = self.embedder.encode([query])[0]
        query_embedding = np.array([query_embedding], dtype=np.float32)
        
        all_results = []
        
        # Search each vector store
        for url_folder, url_dir in self._get_all_url_dirs():
            try:
                # Load vector store
                index, chunks, metadata = self._load_vector_store(url_dir)
                
                # Check if we should filter by URL
                if filter_url:
                    # Convert both to comparable format (strip trailing slash, etc.)
                    doc_url = metadata.get("url", "").rstrip("/")
                    search_url = filter_url.rstrip("/")
                    if doc_url != search_url:
                        continue
                
                # Verify embedder compatibility
                stored_embedder = metadata.get("embedder")
                current_embedder = self.embedder.get_name()
                if stored_embedder and stored_embedder != current_embedder:
                    print(f"Warning: Embedder mismatch for {metadata.get('url')}")
                    print(f"  Stored: {stored_embedder}, Current: {current_embedder}")
                    print(f"  Skipping this document. Re-vectorize to use it.")
                    continue
                
                # Search FAISS index
                distances, indices = index.search(query_embedding, min(top_k, len(chunks)))
                
                # Create results
                for i, (distance, chunk_idx) in enumerate(zip(distances[0], indices[0])):
                    if chunk_idx < len(chunks):  # Valid index
                        result = SearchResult(
                            chunk_text=chunks[chunk_idx],
                            score=float(distance),
                            chunk_index=int(chunk_idx),
                            url=metadata.get("url", "unknown"),
                            metadata=metadata
                        )
                        all_results.append(result)
                        
            except Exception as e:
                print(f"Error searching {url_folder}: {e}")
                continue
        
        # Sort by score (lower is better for L2 distance)
        all_results.sort(key=lambda x: x.score)
        
        return all_results[:top_k] if filter_url else all_results
    
    def search_specific_document(self, url: str, query: str, top_k: int = 5) -> List[SearchResult]:
        """
        Search within a specific document only.
        
        Args:
            url: The exact URL of the document to search
            query: Search query text
            top_k: Number of results to return
            
        Returns:
            List of SearchResult objects from that document only
        """
        return self.search(query, top_k=top_k, filter_url=url)
    
    def get_document_list(self) -> List[Dict]:
        """
        Get list of all indexed documents for this user.
        
        Returns:
            List of metadata dicts for each document
        """
        documents = []
        
        for url_folder, url_dir in self._get_all_url_dirs():
            try:
                metadata_path = os.path.join(url_dir, "metadata.json")
                if os.path.exists(metadata_path):
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        documents.append(metadata)
            except Exception as e:
                print(f"Error reading metadata for {url_folder}: {e}")
                
        return documents


# Convenience function for quick searches
def search_user_documents(user_id: str, query: str, top_k: int = 5) -> List[SearchResult]:
    """
    Quick search function for user's documents.
    
    Args:
        user_id: The user ID
        query: Search query
        top_k: Number of results
        
    Returns:
        List of SearchResult objects
    """
    retriever = VectorRetriever(user_id)
    return retriever.search(query, top_k)


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python retriever.py <user_id> <query>")
        print("Example: python retriever.py NadeemH 'how to troubleshoot citrix'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    query = " ".join(sys.argv[2:])
    
    print(f"Searching documents for user: {user_id}")
    print(f"Query: {query}\n")
    
    results = search_user_documents(user_id, query, top_k=5)
    
    if not results:
        print("No results found.")
    else:
        print(f"Found {len(results)} results:\n")
        for i, result in enumerate(results, 1):
            print(f"--- Result {i} (Score: {result.score:.4f}) ---")
            print(f"URL: {result.url}")
            print(f"Chunk {result.chunk_index}:")
            print(result.chunk_text[:200] + "..." if len(result.chunk_text) > 200 else result.chunk_text)
            print()