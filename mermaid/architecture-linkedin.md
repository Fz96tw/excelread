# ExcelRead — Simplified Architecture (LinkedIn)

```mermaid
flowchart LR
    subgraph Sources["📂 Document Sources"]
        Jira["Jira"]
        Docs["SharePoint\nConfluence\nGoogle Sheets\nURLs"]
    end

    subgraph Platform["⚙️ ExcelRead Platform"]
        Ingest["Document\nIngestion"]
        Vector["Vector Store\n(FAISS)"]
        RAG["RAG\nRetriever"]
        LLM["LLM\n(Ollama / Claude\n/ OpenAI)"]
        Writer["Report\nWriter"]
    end

    subgraph Clients["🖥️ Clients"]
        Web["Web App"]
        MCP["Claude Desktop\n(MCP)"]
    end

    Docs -- "auto-sync\n& watch" --> Ingest
    Jira -- "auto-sync\n& watch" --> Ingest
    Ingest -- "chunk +\nembed" --> Vector
    Vector --> RAG
    RAG --> LLM
    LLM -- "AI briefings\n& answers" --> Web
    LLM -- "tool responses" --> MCP
    Web & MCP -- "natural language\nqueries" --> RAG
    Jira -- "issues &\nrun-rate data" --> LLM
    LLM -- "summarized\nbriefings" --> Writer
    Writer -- "populate\nshared docs" --> Docs
```

> Built a RAG platform that auto-syncs documents from SharePoint, Jira, Confluence & more — chunks, embeds, and indexes them into FAISS, then lets you query everything in natural language via a web app or directly from Claude Desktop via MCP.
