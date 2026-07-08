# X (Twitter) Scraper — Architecture & System Diagrams

This document outlines the architecture, data flows, and system logic for the **X (Twitter) Scraper** application. It contains visual maps in Mermaid diagram syntax to illustrate how the application components interact.

---

## 1. High-Level System Architecture

This diagram illustrates the separation of concerns between the Client dashboard, the FastAPI web server routes, the underlying Singleton dependencies, storage mechanisms, and external services.

```mermaid
graph TD
    subgraph Client Layer
        A[Dashboard UI / HTML Client]
    end

    subgraph FastAPI Application [FastAPI Web Service]
        B[app.py]
        C[routes/scrape.py]
        D[routes/files.py]
        E[routes/ai.py]
        F[routes/status.py]
    end

    subgraph Service & Manager Layer [Singletons & Service Managers]
        G[dependencies.py]
        H[state_manager.py]
        I[file_manager.py]
    end

    subgraph Browser Automation Layer [Browser Automation]
        J[PlaywrightProvider]
        K[BrowserSession Manager]
        L[Playwright / Chromium Instance]
    end

    subgraph External Dependencies [External Services]
        M[x.com Profile Timeline]
        N[Groq API]
    end

    subgraph Storage [Local File Storage]
        O[(state/state.json)]
        P[(scraped_data/)]
        Q[(downloaded_json/)]
        R[(logs/)]
    end

    %% Routing
    A -- GET / --> B
    A -- POST /scrape/start --> C
    A -- POST /scrape/next --> C
    A -- GET /status --> F
    A -- GET /download/latest --> D
    A -- POST /ai/chat --> E

    %% App orchestration
    B --> C & D & E & F

    %% Routing logic
    C -->|Check Lock| G
    C -->|Load/Save State| H
    C -->|Save Batch JSON| I
    C -->|Fetch Posts| J

    D -->|Load State| H
    D -->|Get/Copy Batch JSON| I

    E -->|Read batch files| I
    E -->|Call LLM| N

    F -->|Load State| H
    F -->|Get Status| G

    %% Managers and Storage
    H <-->|Read/Write| O
    I -->|Write JSON| P
    I -->|Copy JSON| Q

    %% Browser interaction
    J -->|Lifecycle & Context| K
    K -->|Launch & Authenticate| L
    L <-->|Navigate & Parse DOM| M
```

### Components Summary
* **Entry Point ([app.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/app.py))**: Bootstraps the application, loads configuration, manages startup/shutdown lifecycles, and registers route modules.
* **Shared State & Singletons ([dependencies.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/dependencies.py))**: Holds the application singletons, including the execution concurrency lock (`scrape_lock`) and live progress status (`live_progress`).
* **Scraper API Router ([routes/scrape.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/scrape.py))**: Exposes endpoints to start sessions, request additional batches, and fetch the single latest post.
* **File & Reset Router ([routes/files.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/files.py))**: Handles browser-initiated state resets and downloads of scraped datasets.
* **AI Analysis Router ([routes/ai.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/ai.py))**: Reads JSON data files and interfaces with the Groq API for LLM-powered context analysis.
* **Playwright Provider ([provider/playwright_provider.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/provider/playwright_provider.py))**: Implements browser interaction, scrolling, DOM queries, tweet extraction, and authentication checking.

---

## 2. Scraping Logic Flowchart

This flowchart outlines the step-by-step logic executed during a scraping operation, showing how locks, authentication, browser navigation, scrolling boundary location, and state persistence are handled.

```mermaid
flowchart TD
    Start([Start Scrape Request]) --> Lock{Is scrape_lock active?}
    Lock -- Yes --> Err409[Return 409 Conflict]
    Lock -- No --> Acquire[Acquire scrape_lock]

    Acquire --> CheckType{Request Type?}
    CheckType -- /scrape/start --> ResetState[Reset state.json]
    ResetState --> FetchBatch1[Fetch Posts - Batch 1]
    
    CheckType -- /scrape/next --> LoadState[Load state.json]
    LoadState --> FetchBatchN[Fetch Posts - Batch N <br> using last_post_id cursor]

    FetchBatch1 & FetchBatchN --> CheckAuth{Is auth.json available?}
    CheckAuth -- No --> AuthErr[Raise AuthenticationError 401]
    CheckAuth -- Yes --> InitBrowser[Launch/Get Browser Context]

    InitBrowser --> GotoX[Navigate to x.com/username]
    GotoX --> CheckPage{Check Profile Status}
    CheckPage -- User Not Found / Suspended / Rate Limit --> PageErr[Raise appropriate ProviderError 400]
    CheckPage -- Success --> WaitTweets[Wait for Tweet Selectors]

    WaitTweets --> LocateBound{Is last_post_id cursor set?}
    LocateBound -- Yes --> ScrollBound[Scroll timeline down to locate last_post_id]
    LocateBound -- No --> ScrapingLoop[Scroll & Parse Tweets]
    ScrollBound --> ScrapingLoop

    ScrapingLoop --> CheckBatchSize{Collected config.BATCH_SIZE posts <br> or Timeline Exhausted?}
    CheckBatchSize -- No --> ScrapingLoop
    CheckBatchSize -- Yes --> SaveData[Save Posts to scraped_data/ JSON]

    SaveData --> UpdateState[Save new ScraperState in state.json]
    UpdateState --> LogMetrics[Write execution metrics to logs/scraper.log]
    LogMetrics --> ReleaseLock[Release scrape_lock]
    ReleaseLock --> End([Return ScrapeResponse 200 OK])
```

---

## 3. Interaction Sequence Diagrams

### Sequence A: Starting a Scraping Session (`/scrape/start`)

This diagram tracks the messages, database accesses, and browser actions when initiating a new session to collect the first batch of tweets.

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Dashboard
    participant API as routes/scrape.py
    participant Lock as dependencies.scrape_lock
    participant State as state_manager.py
    participant File as file_manager.py
    participant Provider as provider/playwright_provider.py
    participant Session as playwright_provider.py (_BrowserSession)
    participant Browser as Playwright Page
    participant X as x.com

    User->>API: POST /scrape/start {username}
    API->>Lock: check if locked
    alt lock is active
        Lock-->>API: Locked
        API-->>User: 409 Conflict
    else lock is free
        API->>Lock: acquire()
        API->>State: reset_state()
        State-->>API: state.json deleted
        
        API->>Provider: fetch_posts(username, batch=1, last_post_id=None)
        Provider->>Session: get_context()
        Session->>Session: verify auth.json exists
        Session->>Browser: Create page inside authenticated context
        Browser-->>Provider: page instance
        
        Provider->>Browser: goto("https://x.com/username")
        Browser->>X: Fetch profile page
        X-->>Browser: HTML content
        
        Provider->>Browser: wait_for_selector("article[data-testid='tweet']")
        Provider->>Browser: scroll & collect 10 posts
        Browser-->>Provider: parse & return Post objects
        Provider-->>API: List[Post]
        
        API->>File: save_batch(username, batch=1, posts)
        File->>Disk: write file to scraped_data/
        File-->>API: filename
        
        API->>State: save_state(username, batch=1, last_post_id, total, filename)
        State->>Disk: write state.json
        
        API->>Disk: write execution metrics to logs/scraper.log
        API->>Lock: release()
        API-->>User: 200 OK (ScrapeResponse)
    end
```

---

### Sequence B: Continuing a Scraping Session (`/scrape/next`)

This diagram traces how pagination is handled when fetching the next batch of tweets, using `last_post_id` to orient the scrolling mechanism.

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Dashboard
    participant API as routes/scrape.py
    participant Lock as dependencies.scrape_lock
    participant State as state_manager.py
    participant File as file_manager.py
    participant Provider as provider/playwright_provider.py
    participant Browser as Playwright Page
    participant X as x.com

    User->>API: POST /scrape/next
    API->>Lock: check if locked
    alt lock is active
        Lock-->>API: Locked
        API-->>User: 409 Conflict
    else lock is free
        API->>Lock: acquire()
        API->>State: load_state()
        State-->>API: Return ScraperState (username, batch, last_post_id)
        
        API->>Provider: fetch_posts(username, batch=N, last_post_id)
        Provider->>Browser: Navigate to "https://x.com/username" (if closed)
        Provider->>Browser: scroll down until last_post_id is found (locate boundary)
        Provider->>Browser: scroll further & collect next 10 unique posts
        Browser-->>Provider: return Post objects
        Provider-->>API: List[Post]
        
        API->>File: save_batch(username, batch=N, posts)
        File->>Disk: write file to scraped_data/
        File-->>API: filename
        
        API->>State: save_state(username, batch=N, new_last_post_id, total, filename)
        State->>Disk: write state.json
        
        API->>Disk: write execution metrics to logs/scraper.log
        API->>Lock: release()
        API-->>User: 200 OK (ScrapeResponse)
    end
```

---

### Sequence C: Downloading Datasets & AI Analysis (`/download/latest` & `/ai/chat`)

This sequence represents the flow of raw data files onto the disk, copying them for the analyst sandbox, and leveraging the Groq API to query context files.

```mermaid
sequenceDiagram
    autonumber
    actor User as Client / Dashboard
    participant FileAPI as routes/files.py
    participant AIAPI as routes/ai.py
    participant State as state_manager.py
    participant File as file_manager.py
    participant Groq as Groq API (llama-3.1-8b-instant)

    %% Flow: Download & Copy to Sandbox
    Note over User, Groq: Dataset Preparation and Downloading
    User->>FileAPI: GET /download/latest
    FileAPI->>State: load_state()
    State-->>FileAPI: active username
    FileAPI->>File: get_latest_batch_file(username)
    File-->>FileAPI: filepath (scraped_data/username_batch_xxx.json)
    
    FileAPI->>FileAPI: _copy_to_downloaded_json()
    Note over FileAPI: Copies file to downloaded_json/ folder for AI context
    FileAPI-->>User: Streams FileResponse (Download file attachment)
    
    %% Flow: AI Context Queries (Analyst Mode)
    Note over User, Groq: AI Context Queries (Analyst Mode)
    User->>AIAPI: POST /ai/chat {message}
    AIAPI->>AIAPI: _get_downloaded_posts()
    Note over AIAPI: Scans downloaded_json/ and compiles unique posts list
    
    AIAPI->>Groq: POST /chat/completions {model, messages + compiled posts context}
    Groq-->>AIAPI: Returns AI analysis response text
    AIAPI-->>User: Returns analysis response JSON
```

---

## 4. Referenced Components

Below are the key codebase files and components referenced in the diagrams:

* [app.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/app.py) — Application Entry & Lifespan
* [config.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/config.py) — Configuration Variables
* [dependencies.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/dependencies.py) — Singleton Registry & Locks
* [models.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/models.py) — Scraper Data Models
* [state_manager.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/state_manager.py) — Session Progress State Tracker
* [file_manager.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/file_manager.py) — File System IO Helper
* [provider/playwright_provider.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/provider/playwright_provider.py) — Browser Automation Engine
* [routes/scrape.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/scrape.py) — Scraper API Endpoints
* [routes/files.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/files.py) — File Download & State Reset Routes
* [routes/ai.py](file:///c:/Users/farze/Desktop/Typescript_practice/x-scrapper/twitter_scraper/routes/ai.py) — AI Analyst Interface
