# lazier — architecture diagram

```mermaid
flowchart TB
    subgraph UI["Frontend (NLE editor)"]
        CREATE["Create project<br/>(aspect, fps, audio, budget, sources)"]
        VIEW["Preview viewport"]
        TL["Multi-track timeline<br/>(waveform spine + sections)"]
        CARDS["Per-section suggestion cards<br/>(recommended + 2 alts, override)"]
        FEED["Quiet agent activity feed"]
    end

    subgraph PIPE["Backend pipeline (FastAPI, deterministic harness)"]
        ING["Audio ingest"]
        WHISP["Whisper service<br/>(faster-whisper large-v3 int8)"]
        P1["Pass 1: silence/gap split<br/>(deterministic)"]
        SEG["Segmenter agent<br/>Pass 2: merge -> sections + visual_brief"]
        SCHED["Fan-out scheduler<br/>+ budget accounting (deterministic)"]
        RES["Researcher agent<br/>brief -> entities + search terms"]
        SRC["Sourcer agents<br/>YouTube / Stock / Meme / Gen / Pool<br/>(rank + fetch)"]
        VER["Verifier agent (VLM)<br/>sample frames -> fit score"]
        ASM["Assembler agent<br/>place recommended + propose alts"]
        DIR["Director (thin LLM)<br/>pacing / variety / budget tradeoffs"]
    end

    subgraph MCP["MCP tool servers (fastmcp)"]
        T_TR["transcribe"]
        T_SG["segments"]
        T_SE["media-search<br/>(Serper, YT API, stock, gif, meme)"]
        T_FE["media-fetch<br/>(yt-dlp, downloader, pool)"]
        T_GE["media-gen<br/>(FAL, budget-guarded)"]
        T_VV["vision-verify<br/>(OpenRouter VLM)"]
        T_TL["timeline<br/>(project mutation)"]
    end

    subgraph STORE["workspace/{project_id}/"]
        PROJ["project.json (truth)"]
        SQL["SQLite asset index"]
        MEDIA["media / proxies / exports"]
        SRT["captions.srt (always)"]
    end

    subgraph RENDER["ffmpeg"]
        PROXY["Proxy chunks (480p, cached)"]
        EXPORT["Full export + audio ducking"]
    end

    CREATE --> ING --> WHISP --> P1 --> SEG --> SCHED
    SCHED --> RES --> SRC --> VER --> ASM --> DIR
    DIR -.global decisions.-> SCHED

    WHISP -. via .-> T_TR
    SEG -. via .-> T_SG
    RES -. via .-> T_SE
    SRC -. via .-> T_SE
    SRC -. via .-> T_FE
    SRC -. via .-> T_GE
    VER -. via .-> T_VV
    ASM -. via .-> T_TL
    DIR -. via .-> T_TL

    T_TL --> PROJ
    T_FE --> MEDIA
    T_GE --> MEDIA
    PROJ --> SQL

    PROJ --> PROXY --> VIEW
    PROJ --> EXPORT
    P1 --> SRT

    ASM --> CARDS
    SCHED --> FEED
    TL --> T_TL
    CARDS --> T_TL
```

Key reading: the **solid spine** is deterministic Python (audio -> whisper -> pass1 -> ... -> assembled timeline). The named "agent" boxes are the only LLM judgment steps, and each reaches the world **only through an MCP server** (dotted lines), never raw. Media files flow into `workspace/` and the agents see them as `asset_id` handles, never bytes. The timeline `project.json` is the single source of truth; both the proxy preview and the final export are derived from it by ffmpeg.
