# Resync Sequence Diagrams

Each diagram covers one phase of the resync pipeline. Start with the overview to orient yourself, then drill into whichever phase you need.

---

## Overview

```mermaid
sequenceDiagram
    actor User
    participant App as appnew.py
    participant R as refresh.py
    participant Ph1 as ① Trigger & Setup
    participant Ph2 as ② Jira Tables
    participant Ph3 as ③ Two-pass Processors
    participant Ph4 as ④ Simple Processors
    participant Ph5 as ⑤ AI Briefing
    participant Ph6 as ⑥ Vectorisation

    User->>App: POST /resync_sharepoint
    App->>R: Celery task dispatched
    R->>Ph1: download + scope parse
    Ph1->>Ph2: *.scope.yaml
    Ph1->>Ph3: *.scope.yaml
    Ph1->>Ph4: *.scope.yaml
    Ph2-->>R: changes written to sheet
    Ph3-->>R: changes written to sheet
    Ph4-->>R: changes written to sheet
    R->>Ph5: re-download + aibrief
    Ph5-->>R: briefing written to sheet
    R->>Ph6: copy to vectorstore
    Ph6-->>App: task complete
```

---

## ① Trigger & Setup

Entry point for every resync. Ends when `scope.py` has written all `*.scope.yaml` files — one per table tag found in the sheet.

```mermaid
sequenceDiagram
    actor User
    participant App as appnew.py
    participant Celery as vector_worker.py<br/>(Celery · Redis DB0)
    participant Refresh as refresh.py
    participant DL as download.py
    participant Scope as scope.py

    User->>App: POST /resync_sharepoint<br/>{ file_url }
    App->>Celery: resync_task_worker.delay(url, userlogin)
    App-->>User: { task_id }

    Celery->>Refresh: resync(url, userlogin)
    Note over Refresh: create work_dir<br/>logs/userlogin/run_id/

    Refresh->>DL: download.py url timestamp [user_auth userlogin]
    Note over DL: SharePoint Graph API<br/>or Google Sheets URL
    DL-->>Refresh: .xlsx file + ETag

    Refresh->>Scope: scope.py filename sheet timestamp userlogin
    Note over Scope: scans every cell for tags<br/>writes one *.scope.yaml per table found<br/>updates config/userlogin/docs.json with new URLs
    Scope-->>Refresh: *.scope.yaml files<br/>(one per table tag found in sheet)
```

---

## ② Standard Jira Tables

Runs once per `*.scope.yaml` or `*.import.scope.yaml`. The ETag retry loop handles the case where SharePoint rejects a write because the file was modified externally between download and update.

```mermaid
sequenceDiagram
    participant Refresh as refresh.py
    participant RJ as read_jira.py
    participant UXL as update_excel.py
    participant USP as update_sharepoint.py<br/>update_googlesheet.py
    participant DL as download.py

    Refresh->>RJ: read_jira.py scope.yaml timestamp userlogin
    Note over RJ: Jira REST API<br/>optional LLM summariser call
    RJ-->>Refresh: *.jira.csv

    Refresh->>UXL: update_excel.py jira.csv filename sheet userlogin
    Note over UXL: maps field indexes to columns<br/>combines multi-tag cell values
    UXL-->>Refresh: *.changes.txt

    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt timestamp userlogin sheet
    alt ETag mismatch
        USP-->>Refresh: Aborting update
        Note over Refresh: wait 30 s
        Refresh->>DL: download.py url timestamp (re-download)
        DL-->>Refresh: .xlsx + fresh ETag
        Refresh->>USP: retry with same changes.txt
    end
    USP-->>Refresh: done
```

---

## ③ Two-pass Processors

Both cycletime and runrate assignee follow the same chain pattern: pass 1 produces an intermediate scope YAML, `read_jira.py` fetches the data for it, then pass 2 builds the final output.

```mermaid
sequenceDiagram
    participant Refresh as refresh.py
    participant CT as cycletime.py
    participant RAsn as runrate_assignee.py
    participant RJ as read_jira.py
    participant USP as update_sharepoint.py<br/>update_googlesheet.py

    Note over Refresh,CT: ── Cycletime ──────────────────────────────

    Refresh->>CT: cycletime.py cycletime.scope.yaml timestamp userlogin (pass 1)
    Note over CT: queries Jira status history API
    CT-->>Refresh: *.chain.scope.yaml

    Refresh->>RJ: read_jira.py chain.scope.yaml timestamp userlogin
    RJ-->>Refresh: *.chain.jira.csv

    Refresh->>CT: cycletime.py chain.jira.csv timestamp userlogin (pass 2)
    Note over CT: computes durations between statuses
    CT-->>Refresh: *.import.changes.txt

    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done

    Note over Refresh,RAsn: ── Runrate Assignee ────────────────────────

    Refresh->>RAsn: runrate_assignee.py rate.scope.yaml timestamp userlogin (pass 1)
    Note over RAsn: groups issues by assignee
    RAsn-->>Refresh: *.assignee.scope.yaml

    Refresh->>RJ: read_jira.py assignee.scope.yaml timestamp userlogin
    RJ-->>Refresh: *.assignee.jira.csv

    Refresh->>RAsn: runrate_assignee.py assignee.jira.csv timestamp userlogin (pass 2)
    Note over RAsn: builds rate table per assignee
    RAsn-->>Refresh: *.import.changes.txt

    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done
```

---

## ④ Simple Processors

Single-pass processors — no chaining. Each reads its scope YAML, calls the Jira API, and writes a changes file directly.

```mermaid
sequenceDiagram
    participant Refresh as refresh.py
    participant RRes as runrate_resolved.py
    participant RCre as runrate_created.py
    participant ST as statustime.py
    participant QS as quickstart.py
    participant USP as update_sharepoint.py<br/>update_googlesheet.py

    Note over Refresh,RRes: ── Runrate Resolved ────────────────────────
    Refresh->>RRes: runrate_resolved.py rate.scope.yaml timestamp userlogin
    RRes-->>Refresh: *.import.changes.txt
    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done

    Note over Refresh,RCre: ── Runrate Created ─────────────────────────
    Refresh->>RCre: runrate_created.py rate.scope.yaml timestamp userlogin
    RCre-->>Refresh: *.import.changes.txt
    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done

    Note over Refresh,ST: ── Statustime ──────────────────────────────
    Refresh->>ST: statustime.py statustime.scope.yaml timestamp userlogin
    Note over ST: queries Jira transition history API
    ST-->>Refresh: *.import.changes.txt
    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done

    Note over Refresh,QS: ── Quickstart ──────────────────────────────
    Refresh->>QS: quickstart.py quickstart.scope.yaml timestamp
    QS-->>Refresh: *.changes.txt
    Refresh->>USP: update_sharepoint/googlesheet.py url changes.txt
    USP-->>Refresh: done
```

---

## ⑤ AI Briefing

Runs **after** all other tables have been written back. A re-download is required first so `aibrief.py` reads a spreadsheet that already contains the freshly updated Jira data.

```mermaid
sequenceDiagram
    participant Refresh as refresh.py
    participant DL as download.py
    participant AB as aibrief.py
    participant LLM as summariser service<br/>(Ollama / Claude / OpenAI)
    participant USP as update_sharepoint.py<br/>update_googlesheet.py

    Note over Refresh,DL: all other tables are already written back at this point

    Refresh->>DL: download.py url timestamp (re-download with updated data)
    DL-->>Refresh: .xlsx + fresh ETag

    Refresh->>AB: aibrief.py url aibrief.scope.yaml timestamp userlogin [--user_auth]
    AB->>LLM: POST /summarize_*_ex  { comments, field_prompt }
    LLM-->>AB: generated summary text
    AB-->>Refresh: *.aibrief.llm.txt<br/>*.aibrief.changes.txt

    Refresh->>USP: update_sharepoint/googlesheet.py url aibrief.changes.txt
    USP-->>Refresh: done
```

---

## ⑥ Vectorisation

Final step. Copies output files into the per-user vectorstore for RAG queries, then purges work directories older than 24 hours.

```mermaid
sequenceDiagram
    participant Refresh as refresh.py
    participant VS as vectorstore<br/>config/userlogin/vectorstore/
    participant Celery as vector_worker.py

    Note over Refresh: all tables written, aibrief complete

    Refresh->>VS: copy *.jira.csv (timestamp stripped from filename)
    Refresh->>VS: copy *.aibrief.llm.txt (timestamp stripped)
    Note over VS: files available for RAG queries<br/>via vector_retriever.py

    Refresh->>Refresh: delete work_dirs older than 24 h<br/>under logs/userlogin/

    Refresh-->>Celery: return
    Note over Celery: task state → SUCCESS<br/>removed from Redis tracking set
```
