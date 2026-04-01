<pre> ```mermaid flowchart TD 

    A[Start Program] --> B[start_watcher()]
    B --> C[Create Observer]
    C --> D[Create DocsFileHandler]
    D --> E[Ensure ./config exists]
    E --> F[Watch config root for new folders]

    F --> G[Loop existing user folders]
    G --> H[Schedule watch per user folder]

    H --> I[Observer.start()]
    I --> J[Infinite loop]

    %% Event handling
    J --> K{File system event?}

    %% Created event
    K -->|on_created| L{Is directory?}
    L -->|Yes| M{Is under config root?}
    M -->|Yes| N[Extract username]
    N --> O[Add user folder to watcher]

    L -->|No| P{Is docs.json?}
    P -->|Yes| Q[Extract username]
    Q --> R[process_user_docs]

    %% Modified event
    K -->|on_modified| S{Is docs.json?}
    S -->|No| J
    S -->|Yes| T{Debounce check}
    T -->|Too soon| J
    T -->|OK| U[Extract username]
    U --> R

    %% Processing docs
    R --> V[Load JSON file]
    V -->|Error| J
    V --> W[Get docs list]
    W -->|Invalid| J

    W --> X[Iterate doc entries]

    X --> Y{Valid dict?}
    Y -->|No| X

    Y --> Z[Extract URL + metadata]

    Z --> AA{Already processed?}
    AA -->|Yes| X

    AA -->|No| AB{Valid URL?}
    AB -->|No| X

    AB -->|Yes| AC[Update Redis state = queued]
    AC --> AD[Dispatch Celery task process_url.delay]
    AD --> X

    %% Loop back
    X -->|Done| J

``` </pre>
