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
    
    def __init__(self, user_id: str, config_dir: str = "../../../config"):
        print(f"\n{'='*60}")
        print(f"INITIALIZING VECTOR RETRIEVER")
        print(f"{'='*60}")
        
        self.user_id = user_id
        self.config_dir = config_dir
        self.user_dir = os.path.join(config_dir, user_id)
        self.vectors_dir = os.path.join(self.user_dir, "vectors")
        
        print(f"User ID: {user_id}")
        print(f"Config directory: {config_dir}")
        print(f"User directory: {self.user_dir}")
        print(f"Vectors directory: {self.vectors_dir}")
        
        # Check if directories exist
        if not os.path.exists(self.config_dir):
            print(f"⚠ Warning: Config directory does not exist: {self.config_dir}")
        else:
            print(f"✓ Config directory exists")
            
        if not os.path.exists(self.user_dir):
            print(f"⚠ Warning: User directory does not exist: {self.user_dir}")
        else:
            print(f"✓ User directory exists")
            
        if not os.path.exists(self.vectors_dir):
            print(f"⚠ Warning: Vectors directory does not exist: {self.vectors_dir}")
        else:
            print(f"✓ Vectors directory exists")
        
        # Initialize embedder
        print(f"\nInitializing embedder...")
        try:
            self.embedder = get_embedder()
            print(f"✓ Embedder initialized: {self.embedder.get_name()}")
        except Exception as e:
            print(f"✗ Failed to initialize embedder: {e}")
            raise
        
        print(f"{'='*60}\n")
        
    def _load_vector_store(self, url_dir: str) -> Tuple[faiss.Index, List[str], Dict]:
        """Load FAISS index, chunks, and metadata for a single URL."""
        print(f"  Loading vector store from: {url_dir}")
        
        index_path = os.path.join(url_dir, "index.faiss")
        chunks_path = os.path.join(url_dir, "chunks.json")
        metadata_path = os.path.join(url_dir, "metadata.json")
        
        # Load FAISS index
        if not os.path.exists(index_path):
            print(f"    ✗ Index file not found: {index_path}")
            raise FileNotFoundError(f"Index not found: {index_path}")
        
        try:
            index = faiss.read_index(index_path)
            print(f"    ✓ FAISS index loaded: {index.ntotal} vectors")
        except Exception as e:
            print(f"    ✗ Failed to load FAISS index: {e}")
            raise
        
        # Load chunks
        if not os.path.exists(chunks_path):
            print(f"    ✗ Chunks file not found: {chunks_path}")
            raise FileNotFoundError(f"Chunks not found: {chunks_path}")
        
        try:
            with open(chunks_path, "r") as f:
                chunks = json.load(f)
            print(f"    ✓ Chunks loaded: {len(chunks)} chunks")
        except Exception as e:
            print(f"    ✗ Failed to load chunks: {e}")
            raise
        
        # Load metadata
        if not os.path.exists(metadata_path):
            print(f"    ✗ Metadata file not found: {metadata_path}")
            raise FileNotFoundError(f"Metadata not found: {metadata_path}")
        
        try:
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
            print(f"    ✓ Metadata loaded: {metadata.get('title', 'Unknown')}")
            print(f"      URL: {metadata.get('url', 'Unknown')}")
        except Exception as e:
            print(f"    ✗ Failed to load metadata: {e}")
            raise
            
        return index, chunks, metadata
    
    def _get_all_url_dirs(self) -> List[Tuple[str, str]]:
        """Get all URL directories for this user."""
        print(f"\n[DISCOVERING DOCUMENTS]")
        
        if not os.path.exists(self.vectors_dir):
            print(f"✗ Vectors directory does not exist: {self.vectors_dir}")
            return []
        
        print(f"Scanning directory: {self.vectors_dir}")
        
        url_dirs = []
        try:
            items = os.listdir(self.vectors_dir)
            print(f"Found {len(items)} items in vectors directory")
            
            for url_folder in items:
                full_path = os.path.join(self.vectors_dir, url_folder)
                if os.path.isdir(full_path):
                    url_dirs.append((url_folder, full_path))
                    print(f"  ✓ Document: {url_folder}")
                else:
                    print(f"  ⊗ Skipping (not a directory): {url_folder}")
            
            print(f"✓ Found {len(url_dirs)} document(s) to search")
        except Exception as e:
            print(f"✗ Error reading vectors directory: {e}")
            return []
        
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
        print(f"\n{'='*60}")
        print(f"SEARCHING VECTOR STORES")
        print(f"{'='*60}")
        print(f"Query: {query}")
        print(f"Top K: {top_k}")
        print(f"Filter URL: {filter_url if filter_url else 'None (search all)'}")
        
        # Encode query
        print(f"\n[STEP 1] Encoding query...")
        try:
            query_embedding = self.embedder.encode([query])[0]
            query_embedding = np.array([query_embedding], dtype=np.float32)
            embedding_dim = query_embedding.shape[1]
            print(f"✓ Query encoded: {embedding_dim} dimensions")
        except Exception as e:
            print(f"✗ Failed to encode query: {e}")
            raise
        
        all_results = []
        
        # Get all document directories
        url_dirs = self._get_all_url_dirs()
        
        if not url_dirs:
            print(f"\n✗ No documents found to search")
            print(f"{'='*60}\n")
            return []
        
        # Search each vector store
        print(f"\n[STEP 2] Searching {len(url_dirs)} document(s)...")
        docs_searched = 0
        docs_skipped = 0
        docs_errored = 0
        
        for idx, (url_folder, url_dir) in enumerate(url_dirs, 1):
            print(f"\n  [{idx}/{len(url_dirs)}] Processing: {url_folder}")
            
            try:
                # Load vector store
                index, chunks, metadata = self._load_vector_store(url_dir)
                
                # Check if we should filter by URL
                if filter_url:
                    doc_url = metadata.get("url", "").rstrip("/")
                    search_url = filter_url.rstrip("/")
                    if doc_url != search_url:
                        print(f"    ⊗ Skipping: URL doesn't match filter")
                        print(f"      Doc URL: {doc_url}")
                        print(f"      Filter:  {search_url}")
                        docs_skipped += 1
                        continue
                
                # Verify embedder compatibility
                stored_embedder = metadata.get("embedder")
                current_embedder = self.embedder.get_name()
                
                if stored_embedder and stored_embedder != current_embedder:
                    print(f"    ✗ Embedder mismatch!")
                    print(f"      Stored: {stored_embedder}")
                    print(f"      Current: {current_embedder}")
                    print(f"      Skipping this document (re-vectorize to use it)")
                    docs_skipped += 1
                    continue
                
                print(f"    Embedder: {current_embedder} ✓")
                
                # Search FAISS index
                k_to_search = min(top_k, len(chunks))
                print(f"    Searching for top {k_to_search} chunks...")
                
                try:
                    distances, indices = index.search(query_embedding, k_to_search)
                    print(f"    ✓ Search completed")
                except Exception as e:
                    print(f"    ✗ FAISS search failed: {e}")
                    docs_errored += 1
                    continue
                
                # Create results
                results_from_doc = 0
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
                        results_from_doc += 1
                        print(f"      Result {i+1}: chunk {chunk_idx}, score {distance:.4f}")
                    else:
                        print(f"      ⚠ Invalid chunk index {chunk_idx} (max: {len(chunks)-1})")
                
                print(f"    ✓ Added {results_from_doc} result(s) from this document")
                docs_searched += 1
                        
            except Exception as e:
                print(f"    ✗ Error searching {url_folder}: {e}")
                docs_errored += 1
                continue
        
        # Summary
        print(f"\n[SEARCH SUMMARY]")
        print(f"  Documents found: {len(url_dirs)}")
        print(f"  Successfully searched: {docs_searched}")
        print(f"  Skipped: {docs_skipped}")
        print(f"  Errors: {docs_errored}")
        print(f"  Total results before sorting: {len(all_results)}")
        
        # Sort by score (lower is better for L2 distance)
        if all_results:
            print(f"\n[STEP 3] Sorting results by relevance...")
            all_results.sort(key=lambda x: x.score)
            
            # Show score range
            best_score = all_results[0].score
            worst_score = all_results[-1].score
            print(f"  Score range: {best_score:.4f} (best) to {worst_score:.4f} (worst)")
            
            # Apply final limit
            if filter_url:
                final_results = all_results[:top_k]
            else:
                final_results = all_results
            
            if len(final_results) < len(all_results):
                print(f"  Limiting to top {len(final_results)} results")
            
            print(f"✓ Returning {len(final_results)} result(s)")
        else:
            print(f"\n✗ No results found")
            final_results = []
        
        print(f"{'='*60}\n")
        
        return final_results if not filter_url else all_results[:top_k]
    
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
        print(f"\n[SPECIFIC DOCUMENT SEARCH]")
        print(f"Target URL: {url}")
        
        return self.search(query, top_k=top_k, filter_url=url)
    
    def get_document_list(self) -> List[Dict]:
        """
        Get list of all indexed documents for this user.
        
        Returns:
            List of metadata dicts for each document
        """
        print(f"\n[LISTING DOCUMENTS]")
        
        documents = []
        
        for url_folder, url_dir in self._get_all_url_dirs():
            try:
                metadata_path = os.path.join(url_dir, "metadata.json")
                if os.path.exists(metadata_path):
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        documents.append(metadata)
                        print(f"  ✓ {metadata.get('title', url_folder)}")
                else:
                    print(f"  ⚠ No metadata found for {url_folder}")
            except Exception as e:
                print(f"  ✗ Error reading metadata for {url_folder}: {e}")
        
        print(f"\nFound {len(documents)} document(s)")
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
    print(f"\n{'*'*60}")
    print(f"* QUICK SEARCH")
    print(f"{'*'*60}")
    
    retriever = VectorRetriever(user_id)
    return retriever.search(query, top_k)


if __name__ == "__main__":
    # Example usage
    import sys
    
    print(f"\n{'#'*60}")
    print(f"# VECTOR RETRIEVER - COMMAND LINE MODE")
    print(f"{'#'*60}\n")
    
    if len(sys.argv) < 3:
        print("Usage: python retriever.py <user_id> <query>")
        print("Example: python retriever.py NadeemH 'how to troubleshoot citrix'")
        sys.exit(1)
    
    user_id = sys.argv[1]
    query = " ".join(sys.argv[2:])
    
    print(f"User ID: {user_id}")
    print(f"Query: {query}")
    
    try:
        results = search_user_documents(user_id, query, top_k=5)
        
        if not results:
            print("\n" + "="*60)
            print("NO RESULTS FOUND")
            print("="*60)
            print("\nPossible reasons:")
            print("  - No documents indexed for this user")
            print("  - Query doesn't match any document content")
            print("  - Embedder mismatch (documents need re-vectorization)")
        else:
            print("\n" + "="*60)
            print(f"FOUND {len(results)} RESULT(S)")
            print("="*60)
            
            for i, result in enumerate(results, 1):
                print(f"\n{'─'*60}")
                print(f"Result {i} - Score: {result.score:.4f}")
                print(f"{'─'*60}")
                print(f"URL: {result.url}")
                print(f"Chunk Index: {result.chunk_index}")
                print(f"Title: {result.metadata.get('title', 'Unknown')}")
                print(f"\nContent Preview:")
                content_preview = result.chunk_text[:300] + "..." if len(result.chunk_text) > 300 else result.chunk_text
                print(content_preview)
                print()
        
        print("\n" + "#"*60)
        print("# EXECUTION COMPLETED")
        print("#"*60 + "\n")
        
    except Exception as e:
        print("\n" + "!"*60)
        print("! EXECUTION FAILED")
        print("!"*60)
        print(f"\nError: {e}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        print("\n" + "!"*60 + "\n")
        sys.exit(1)