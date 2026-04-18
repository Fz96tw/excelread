# Scope File Tag Reference

Tags are special markers you place inside cells of an Excel sheet or Google Sheet. When the sheet is processed by `scope.py`, each tag controls what data gets pulled from Jira and how it is displayed or summarised.

Tags are **not case-sensitive**. The text you place **before** a tag on the same cell becomes the table name that labels the output.

---

## Table Tags

These tags define a data table. Each one starts a new block and must appear in its own cell. A blank row below the tag row signals the end of the table.

---

### `<jira>`

Pulls data from Jira. Rows below the tag row define column headers; subsequent rows supply the Jira issue keys to fetch.

**Cell format:**
```
My Table Name <jira>
```

**Required structure:**

| Row | What to put in it |
|---|---|
| Tag row | `Table Name <jira>` |
| Header row | One or more `<fieldname>` tags per column (see [Field Tags](#field-tags)) |
| Data rows | One Jira issue key per row in the `<key>` column (e.g. `PROJ-123`) |

**Example layout (each cell shown as a column):**

```
| My Issues <jira> |                  |             |
| <key>            | <summary>         | <status>    |
| PROJ-101         |                  |             |
| PROJ-102         |                  |             |
```

**Multiple field tags in one cell:**

A single header cell can contain multiple `<fieldname>` tags. The results for all tags in that cell are combined (separated by `; `) and written back to that one cell in the spreadsheet. `<key>` must always be alone in its cell.

```
| <key> | <summary> <status> <assignee> | <comments> Summarise blockers only |
```

When combining tags, any text that follows the last tag in the cell is used as the LLM prompt for that last tag only. To give each tag its own prompt, place the prompt text immediately after each respective tag:

```
| <summary> one-line title <description> full technical detail |
```

---

### `<jira>` with JQL import

Appending `jql` and a JQL expression to the tag cell fetches all matching issues automatically — no need to list individual keys.

**Cell format:**
```
My Table Name <jira> jql project = MYPROJ AND status != Done
```

The entire JQL expression follows the word `jql` in the same cell. The header row and column structure are still required.

---

### `<jira>` with create mode

Adding the word `create` after the tag switches to create mode: each data row below the headers defines a **new Jira issue** to be created rather than fetched.

**Cell format:**
```
New Issues <jira> create
```

In create mode, any text placed after a field tag in the header row becomes the **default value** for that field when a data cell is blank.

**Example:**
```
| New Bugs <jira> create |                         |              |
| <summary>              | <issuetype> Bug          | <priority>   |
| Login page crashes     |                         | High         |
| Export fails silently  |                         |              |
```
Here `<issuetype>` defaults to `Bug` for any row that leaves that cell empty.

---

### `<ai brief>`

Generates an AI-written summary briefing that draws from one or more other named tables. The table names listed after the tag are the source tables whose data feeds the briefing.

**Cell format:**
```
Q1 Summary <ai brief> My Issues, New Bugs
```

The comma-separated names after `<ai brief>` must match the table names defined elsewhere in the sheet.

**Optional companion tags** (place in the same row or the row immediately below):

| Tag | Purpose |
|---|---|
| `<email>` | Send the briefing to these addresses when complete |
| `<wiki>` | Publish the briefing to this Confluence page URL |
| `<llm>` | Custom prompt passed to the LLM when generating this briefing |

**Example:**
```
| Q1 Summary <ai brief> My Issues, New Bugs | <email> alice@example.com, bob@example.com | <wiki> https://wiki.example.com/Q1 |
```

---

### `<rate resolved>`

Generates a run-rate chart showing how many Jira issues were **resolved** per time period, grouped by the period defined in the second `< >` block.

**Cell format:**
```
Resolved Rate <rate resolved> <weekly 4> jql project = MYPROJ AND status = Done
```

- The second `< >` block sets the **period type and count** — e.g. `<weekly 4>` means 4 weeks.
- Everything after `jql` is the JQL query.

---

### `<rate assignee>`

Same structure as `<rate resolved>` but groups resolved issues **by assignee**.

**Cell format:**
```
Assignee Rate <rate assignee> <weekly 4> jql project = MYPROJ
```

---

### `<rate created>`

Same structure but counts issues **created** (not resolved) per period.

**Cell format:**
```
Created Rate <rate created> <weekly 4> jql project = MYPROJ
```

---

### `<cycletime>`

Calculates the **cycle time** (time from creation to resolution) for issues matching a JQL query. Results are written into the table starting at the row and column where the tag was found.

**Cell format:**
```
Dev Cycle Time <cycletime> jql project = MYPROJ AND issuetype = Story
```

The JQL expression is required and must follow the word `jql` in the same cell.

---

### `<statustime>`

Identical behaviour to `<cycletime>` but measures **time spent in each status** rather than overall cycle time.

**Cell format:**
```
Status Breakdown <statustime> jql project = MYPROJ
```

---

### `<quickstart>`

Produces a high-level summary snapshot for one or more Jira projects. Comma-separate multiple project keys.

**Cell format:**
```
Project Overview <quickstart> PROJ1, PROJ2, PROJ3
```

---

### `<docs>`

Registers URLs with the RAG document store so they become available for AI queries. Place the tag in one cell, then list one URL per row in subsequent cells below it. Only `http`/`https` URLs are captured.

**Layout:**
```
| <docs>                          |
| https://example.com/spec.xlsx   |
| https://wiki.example.com/design |
```

Any URL added here is automatically registered in `docs.json` and queued for vectorisation.

---

## Field Tags

Field tags define the **columns** of a `<jira>` table. They go in the header row immediately below the table tag row. A cell can contain one or more field tags (except `<key>`, which must be alone).

### Standard Jira API fields

These map directly to Jira REST API field names.

| Tag | Jira field pulled |
|---|---|
| `<key>` | Issue key (e.g. `PROJ-123`) — **required**, must be alone in its cell |
| `<summary>` | Issue title / summary |
| `<description>` | Full issue description |
| `<status>` | Current workflow status |
| `<issuetype>` | Issue type (Bug, Story, Task, …) |
| `<priority>` | Priority level |
| `<assignee>` | Assigned user's display name |
| `<created>` | Creation date |
| `<comments>` | All comments, newest first, formatted as `date - author: text` entries separated by `;` |

Any other valid Jira field name can also be used as a tag — it is passed directly to the Jira API (e.g. `<customfield_10014>`).

### Computed / virtual fields

These are not native Jira API fields — they are assembled by the pipeline.

| Tag | What is produced |
|---|---|
| `<url>` | A hyperlink to the issue in your Jira instance (prefixed `URL` for downstream hyperlink conversion) |
| `<id>` | Internal Jira numeric ID |
| `<timestamp>` | Date and time the data was fetched (`YYYY-MM-DD HH:MM:SS`) |
| `<headline>` | One-line digest: key, truncated summary, status, assignee, type, and created date — useful for a compact overview column |
| `<children>` | For Epic issues: a `;`-separated list of child issue keys and their summaries, statuses, and assignees. Empty for non-Epics. |
| `<links>` | All outward and inward issue links, each formatted as `▫️ KEY summary [link type]`, separated by `;` |
| `<synopsis>` | Brief structural summary: issue type (e.g. `Epic`) and sub-task count |

### Adding a prompt or default value

Any text placed **after** the closing `>` of a tag in the header cell has dual meaning depending on mode:

- **In regular / import mode** — treated as an **LLM prompt** applied to that field's value when generating summaries. The field value and any RAG context are passed to the LLM along with the prompt.
- **In create mode** — treated as the **default value** for that field when the data cell is blank.

**Example (regular mode — LLM prompt):**
```
| <summary> Rewrite as a one-line executive summary |
```

**Example (create mode — default value):**
```
| <issuetype> Bug |
```

**Example (multi-tag cell with per-tag prompts):**
```
| <summary> one-line title <description> extract acceptance criteria only |
```

---

## Companion Tags

These tags modify the behaviour of the enclosing table. They can appear in the same row as the table tag or on an immediately following row.

### `<email>`

Sends the output of an `<ai brief>` to the listed addresses. Comma-separate multiple addresses.

```
<email> alice@example.com, bob@example.com
```

Only active when paired with `<ai brief>`.

---

### `<wiki>`

Publishes the output of an `<ai brief>` to the specified Confluence page URL.

```
<wiki> https://confluence.example.com/display/TEAM/Q1+Summary
```

Only active when paired with `<ai brief>`.

---

### `<llm>`

Supplies a custom prompt to the LLM when it processes the accompanying table or briefing. The full text after the tag is passed as the instruction.

```
<llm> Focus on risks and blockers only. Keep the summary under 3 bullet points.
```

Can be placed anywhere in the sheet; applies to the table it accompanies.

---

## Rules and Behaviour Notes

- **Table name** is the text in the same cell, placed **before** the tag. Spaces are preserved in display but converted to underscores in output filenames.
- **One table tag per cell.** Do not place two table-level tags (e.g. `<jira>`, `<rate resolved>`) in the same cell.
- **Field header cells may contain multiple tags.** Any column in a `<jira>` header row may combine several field tags (e.g. `<summary> <status>`). Their results are concatenated with `; ` in the output cell. `<key>` must always be alone in its cell.
- **`<jira>` breaks out of its row** — the parser stops reading further cells on the same row after finding `<jira>`. Put companion tags (`<email>`, `<llm>`, etc.) in their own rows.
- **`<ai brief>` continues reading** the same row — `<email>`, `<wiki>`, and `<llm>` can appear in adjacent cells on the same row.
- **Blank rows end a table** — a fully blank row signals the end of the current data block.
- **Multiple tables per sheet** — you can place as many table tags as you like in a single sheet. Each one produces its own output file.
- **Tag detection is line-position agnostic** — tags can appear in any column. The parser scans every cell in every row.
