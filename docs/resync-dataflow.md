# Resync Data Flow

## Overview

High-level pipeline: each numbered phase is detailed in its own diagram below.

```mermaid
flowchart LR
    A["① Download\ndownload.py"] --> B["② Scope Parse\nscope.py"]
    B --> C["③ Processors\nper table type"]
    C --> D["④ Write Back\nupdate_*.py"]
    D --> E["⑤ Vectorise\nrefresh.py"]

    HTTP["HTTP POST\nappnew.py"] --> Q["Celery\nvector_worker.py"]
    Q --> A

    D -->|ETag mismatch| A
```

---

## ① Trigger & Download

```mermaid
flowchart TD
    HTTP["HTTP POST · /resync_sharepoint\nappnew.py"]
    HTTP --> Task["resync_task_worker\nvector_worker.py · resync_queue · Redis DB0"]
    Task --> Refresh["refresh.py · resync()\ncreates work_dir: logs/userlogin/run_id/"]
    Refresh --> DL["download.py\nSharePoint Graph API or Google Sheets URL"]
    DL --> XLSX[("local .xlsx file\n+ ETag metadata")]
```

---

## ② Scope Parsing

```mermaid
flowchart TD
    XLSX[(".xlsx file or\nGoogle Sheet URL")] --> Scope["scope.py\nscans every cell for tags"]
    Scope --> DocsJSON[("config/userlogin/docs.json\nnew URLs registered for RAG")]

    Scope --> SY1[("*.scope.yaml\nstandard &lt;jira&gt; table")]
    Scope --> SY2[("*.import.scope.yaml\n&lt;jira&gt; jql … import")]
    Scope --> SY3[("*.create.scope.yaml\n&lt;jira&gt; create")]
    Scope --> SY4[("*.rate.scope.yaml\n&lt;rate resolved/created/assignee&gt;")]
    Scope --> SY5[("*.cycletime.scope.yaml")]
    Scope --> SY6[("*.statustime.scope.yaml")]
    Scope --> SY7[("*.quickstart.scope.yaml")]
    Scope --> SY8[("*.aibrief.scope.yaml")]
```

---

## ③a Standard Jira Tables

```mermaid
flowchart TD
    SY1[("*.scope.yaml\n*.import.scope.yaml")] --> RJ["read_jira.py\nJira REST API\noptional LLM summariser"]
    RJ --> JCSV[("*.jira.csv\n*.import.jira.csv")]
    JCSV --> UXL["update_excel.py\n(local .xlsx only)"]
    UXL --> CHG[("*.changes.txt")]
```

---

## ③b Create Jira Issues

```mermaid
flowchart TD
    SY3[("*.create.scope.yaml")] --> CJ["create_jira.py\nJira REST API"]
    CJ --> Done(["New issues created in Jira"])
```

---

## ③c Runrate Processors

```mermaid
flowchart TD
    SY4[("*.rate.scope.yaml")] --> RateType{"rate type?"}

    RateType -->|resolved| RRes["runrate_resolved.py"]
    RateType -->|created| RCre["runrate_created.py"]
    RateType -->|assignee| RAsn1["runrate_assignee.py · pass 1"]

    RRes --> RC1[("*.import.changes.txt")]
    RCre --> RC2[("*.import.changes.txt")]

    RAsn1 --> AsnSY[("*.assignee.scope.yaml")]
    AsnSY --> RJAsn["read_jira.py (chain)"]
    RJAsn --> AsnCSV[("*.assignee.jira.csv")]
    AsnCSV --> RAsn2["runrate_assignee.py · pass 2"]
    RAsn2 --> AsnChg[("*.import.changes.txt")]
```

---

## ③d Cycletime (two-pass)

```mermaid
flowchart TD
    SY5[("*.cycletime.scope.yaml")] --> CT1["cycletime.py · pass 1\nJira status history via API"]
    CT1 --> CTChainSY[("*.chain.scope.yaml")]
    CTChainSY --> RJCT["read_jira.py (chain)"]
    RJCT --> CTChainCSV[("*.chain.jira.csv")]
    CTChainCSV --> CT2["cycletime.py · pass 2\ncompute durations"]
    CT2 --> CTChg[("*.import.changes.txt")]
```

---

## ③e Statustime & Quickstart

```mermaid
flowchart TD
    SY6[("*.statustime.scope.yaml")] --> ST["statustime.py\nJira transition history"]
    ST --> STChg[("*.import.changes.txt")]

    SY7[("*.quickstart.scope.yaml")] --> QS["quickstart.py"]
    QS --> QSChg[("*.changes.txt")]
```

---

## ③f AI Briefing

```mermaid
flowchart TD
    SY8[("*.aibrief.scope.yaml")] --> AB["aibrief.py\nsummariser service\nOllama / Claude / OpenAI"]
    AB --> ABTxt[("*.aibrief.llm.txt")]
    AB --> ABChg[("*.aibrief.changes.txt")]
```

---

## ④ Write Back to Spreadsheet

```mermaid
flowchart TD
    CHG[("all *.changes.txt\nfrom processors")] --> USP{"destination?"}

    USP -->|SharePoint| SP["update_sharepoint.py\nGraph API PATCH"]
    USP -->|Google Sheet| GS["update_googlesheet.py\nSheets API"]
    USP -->|local Excel| XL["update_excel.py\nopenpyxl"]

    SP & GS & XL --> Sheet[("Spreadsheet updated")]

    SP & GS -->|ETag mismatch| Retry["wait 30 s\nre-download.py\nretry"]
    Retry --> USP
```

---

## ⑤ Vectorisation

```mermaid
flowchart TD
    JCSV[("*.jira.csv")] --> Copy["refresh.py\ncopy & strip timestamp"]
    ABTxt[("*.aibrief.llm.txt")] --> Copy
    Copy --> VS[("config/userlogin/vectorstore/\nindexed for RAG queries")]
```

---

## Phase Summary

| Phase | Script(s) | Input | Output |
|---|---|---|---|
| ① Download | `download.py` | SharePoint / Google Sheets URL | `.xlsx` + ETag |
| ② Scope | `scope.py` | `.xlsx` / Google Sheet | `*.scope.yaml` per table tag |
| ③a Jira fetch | `read_jira.py`, `update_excel.py` | `*.scope.yaml` | `*.jira.csv` → `*.changes.txt` |
| ③b Create | `create_jira.py` | `*.create.scope.yaml` | New Jira issues |
| ③c Runrate | `runrate_*.py` + `read_jira.py` | `*.rate.scope.yaml` | `*.changes.txt` (two-pass for assignee) |
| ③d Cycletime | `cycletime.py` ×2 + `read_jira.py` | `*.cycletime.scope.yaml` | `*.changes.txt` (two-pass via chain yaml) |
| ③e Statustime / Quickstart | `statustime.py`, `quickstart.py` | `*.statustime/quickstart.scope.yaml` | `*.changes.txt` |
| ③f AI Brief | `aibrief.py` + summariser | `*.aibrief.scope.yaml` | `*.aibrief.llm.txt` + `*.changes.txt` |
| ④ Write back | `update_sharepoint/googlesheet/excel.py` | `*.changes.txt` | Spreadsheet cells updated |
| ⑤ Vectorise | `refresh.py` (inline) | `*.jira.csv`, `*.aibrief.llm.txt` | `config/userlogin/vectorstore/` |
