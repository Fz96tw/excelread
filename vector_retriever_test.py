from vector_retriever import VectorRetriever, search_user_documents

# Quick search across all documents
results = search_user_documents("NadeemH", "what are the important parts of epic from Product Manager", top_k=5)

for result in results:
    print(f"From: {result.url}")
    print(f"Score: {result.score}")
    print(f"Text: {result.chunk_text}")
    print()

# Or use the class for more control
retriever = VectorRetriever("NadeemH")

# Search all documents
results = retriever.search("citrix access issues", top_k=10)

# Search specific document only
results = retriever.search_specific_document(
    url="https://ithelpcentre.atlassian.net/wiki/...",
    query="troubleshoot",
    top_k=3
)

# Get list of all indexed documents
docs = retriever.get_document_list()
for doc in docs:
    print(f"{doc['url']} - {doc['num_chunks']} chunks")