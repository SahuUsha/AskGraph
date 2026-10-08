# 🏗️ QueryVista: System Architecture & Technical Design

**Version:** 1.0  
**Date:** May 2026  
**Audience:** Technical & Executive Stakeholders  
**Status:** Production-Ready MVP

---

## Table of Contents

1. [Executive Architecture Overview](#executive-architecture-overview)
2. [High-Level System Architecture](#high-level-system-architecture)
3. [Component Architecture](#component-architecture)
4. [Data Flow Architecture](#data-flow-architecture)
5. [Migration Pipeline Architecture](#migration-pipeline-architecture)
6. [Technology Stack](#technology-stack)
7. [Database Support Matrix](#database-support-matrix)
8. [API Architecture](#api-architecture)
9. [Security Architecture](#security-architecture)
10. [Scalability & Performance](#scalability--performance)
11. [Deployment Architecture](#deployment-architecture)

---

## Executive Architecture Overview

### The QueryVista Stack: Three Integrated Layers

```
┌──────────────────────────────────────────────────────────────────┐
│           🎨 PRESENTATION LAYER                                  │
│  (Web UI - React/HTML5 SPA)                                      │
│  • Migration Wizard                                              │
│  • Schema Visualizer Dashboard                                  │
│  • Dual-Database Query Interface                                │
└──────────────────────────────────────────────────────────────────┘
                                ↕
┌──────────────────────────────────────────────────────────────────┐
│           🧠 APPLICATION LAYER (FastAPI Backend)                 │
│  Core Business Logic & Orchestration                            │
│  ┌───────────────┬──────────────────┬─────────────────┐         │
│  │   ETL Engine  │  AI Integration  │  Query Compiler │         │
│  │   (Pipelines) │   (Azure OpenAI) │  (SQL/NoSQL)    │         │
│  └───────────────┴──────────────────┴─────────────────┘         │
│  • Session Management                                           │
│  • Migration Orchestration                                      │
│  • Plan Generation & Execution                                 │
│  • Dual-Database Query Processing                              │
└──────────────────────────────────────────────────────────────────┘
                                ↕
┌──────────────────────────────────────────────────────────────────┐
│           💾 DATA LAYER                                           │
│  Database Abstraction & Storage                                 │
│  ┌──────────────┬─────────────┬──────────────┬──────────────┐   │
│  │ PostgreSQL   │   MySQL     │   MongoDB    │   CouchDB    │   │
│  │ (SQL)        │   (SQL)     │   (NoSQL)    │   (NoSQL)    │   │
│  └──────────────┴─────────────┴──────────────┴──────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## High-Level System Architecture

### Complete System Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                              │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  HTML5 SPA (app.js, index.html, style.css)                │   │
│  │  • Responsive Web Interface                               │   │
│  │  • Real-time Progress Monitoring                          │   │
│  │  • Interactive Schema Visualizer                          │   │
│  │  • Natural Language Query Builder                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                              ↕ (HTTPS/WebSocket)
┌─────────────────────────────────────────────────────────────────────┐
│                    BACKEND API LAYER (FastAPI)                      │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Route Layer: /api/pipelines, /api/extract-schema, etc.    │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Service Layer                                              │  │
│  │  ┌─────────────────┬──────────────┬──────────────────┐      │  │
│  │  │ Migration Mgr   │ AI Service   │  Query Compiler  │      │  │
│  │  │ (Orchestration) │ (OpenAI)     │  (Dual-DB)       │      │  │
│  │  └─────────────────┴──────────────┴──────────────────┘      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Pipeline Layer                                             │  │
│  │  ┌─────────────────────────────────────────────────────┐   │  │
│  │  │  Base Pipeline (Abstraction Layer)                 │   │  │
│  │  │  • Schema Extraction                               │   │  │
│  │  │  • Data Transformation                             │   │  │
│  │  │  • Validation & Error Handling                     │   │  │
│  │  └─────────────────────────────────────────────────────┘   │  │
│  │                       ↕                                     │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  Specialized Pipelines (9 Implementations)         │  │  │
│  │  │  • MySQL↔Mongo, PostgreSQL↔Mongo                 │  │  │
│  │  │  • MySQL↔CouchDB, PostgreSQL↔CouchDB            │  │  │
│  │  │  • Mongo↔CouchDB, Mongo↔MySQL, Mongo↔PostgreSQL│  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Database Drivers & Utilities                               │  │
│  │  • MySQL Connector (SQLAlchemy)                             │  │
│  │  • PostgreSQL Driver (psycopg2)                             │  │
│  │  • MongoDB PyMongo Client                                   │  │
│  │  • CouchDB HTTP Client                                      │  │
│  │  • Connection Pooling & Caching                             │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              ↕ (TCP/HTTP)
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                                    │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐     │
│  │  PostgreSQL  │    MySQL     │   MongoDB    │   CouchDB    │     │
│  │  (Neon/On-   │  (Docker/On- │  (Atlas/On- │  (Docker/On-│     │
│  │   Premise)   │   Premise)   │  Premise)   │  Premise)   │     │
│  └──────────────┴──────────────┴──────────────┴──────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### Component Interaction Diagram

```
┌─────────────────────────┐
│   Frontend Layer        │
│  (app.js, HTML5 UI)     │
└────────────┬────────────┘
             │
      ┌──────▼──────┐
      │ HTTP/REST   │
      │ Requests    │
      └──────┬──────┘
             │
┌────────────▼─────────────────────────────────┐
│     FastAPI Application (main.py)            │
│                                              │
│  Route Handlers (Request → Response)         │
│  ├─ GET /api/pipelines                       │
│  ├─ POST /api/test-connection                │
│  ├─ POST /api/extract-schema                 │
│  ├─ POST /api/generate-plan                  │
│  ├─ POST /api/update-plan                    │
│  ├─ POST /api/execute-migration              │
│  ├─ GET /api/migration-status/{id}           │
│  ├─ POST /generate-dual                      │
│  └─ [9+ more endpoints]                      │
│                                              │
└────────────┬─────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌────────────┐   ┌──────────────────┐
│  Pipeline  │   │  AI Service      │
│  Registry  │   │  (Azure OpenAI)  │
│            │   │                  │
│ • mysql_   │   │ • Schema Mapping │
│  to_mongo  │   │ • Plan Generation│
│ • postgres │   │ • Query Compilation
│ • etc (9)  │   │                  │
└────────────┘   └──────────────────┘
    │
    │ execute()
    │
    ▼
┌──────────────────────────────────────┐
│   Base Pipeline (base.py)            │
│                                      │
│   Abstract Methods:                  │
│   • source_to_source_connection()    │
│   • extract_source_schema()          │
│   • transform_schema()               │
│   • execute_migration()              │
│   • validate_data()                  │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│   Database Drivers & Connectors      │
│                                      │
│   • SQLAlchemy (SQL Databases)       │
│   • PyMongo (MongoDB)                │
│   • CouchDB HTTP Client              │
│   • Connection Pooling               │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│   Source & Target Databases          │
│                                      │
│   PostgreSQL │ MySQL │ Mongo │ Couch│
└──────────────────────────────────────┘
```

### Key Components Breakdown

| Component | Purpose | Technology | Files |
|-----------|---------|-----------|-------|
| **Frontend Layer** | User Interface & Interaction | HTML5, CSS3, JavaScript | `app.js`, `index.html`, `style.css` |
| **FastAPI Application** | REST API & Route Handling | FastAPI, Pydantic | `main.py`, `app2.py` |
| **AI Service** | Schema mapping & Plan generation | Azure OpenAI GPT-4o | `ai_service.py` |
| **Pipeline Base** | Abstract ETL operations | Python OOP | `pipelines/base.py` |
| **Specialized Pipelines** | Database pair implementations | SQL/NoSQL drivers | `pipelines/*_to_*.py` (9 files) |
| **Database Managers** | Connection & Query abstraction | SQLAlchemy, PyMongo, HTTP | `database_manager.py` |
| **Query Compiler** | Dual-database query translation | LLM + dynamic SQL/aggregation | `viz_service.py` |
| **Utilities** | Logging, config, helpers | Python standard lib | `utils.py`, `config.py` |

---

## Data Flow Architecture

### Migration Workflow Data Flow

```
Step 1: Connection & Validation
┌──────────────────────────────┐
│ User Input (DB Credentials)  │
└──────────────┬───────────────┘
               │
               ▼
      ┌─────────────────────┐
      │ Test Connection API │
      └──────────┬──────────┘
               │ (Validated)
               ▼
    ┌──────────────────────────┐
    │ Connection Stored in     │
    │ Session State            │
    └──────────────────────────┘

Step 2: Schema Extraction
┌──────────────────────────┐
│ extract_schema API Call  │
└──────────────┬───────────┘
               │
        ┌──────▼──────┐
        │ SQL DB?     │ NoSQL DB?
        └──┬──────┬───┘
        │  │
        │  └─────────────────┐
        │                    │
        ▼                    ▼
   ┌────────────┐      ┌──────────────────┐
   │  Query DB  │      │ Sample Collections
   │  Metadata  │      │ (Infer Schema)
   │ (DESCRIBE, │      │
   │ SHOW INDEX)│      └─────────┬────────┘
   └─────┬──────┘                │
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │ Unified Schema Object   │
        │ (Tables/Collections)    │
        │ (Columns/Fields)        │
        │ (Keys, Indexes)         │
        └────────────┬────────────┘
                     │
                     ▼
        ┌─────────────────────────┐
        │ Stored in Session       │
        │ for Human Review        │
        └─────────────────────────┘

Step 3: AI Plan Generation
┌──────────────────────────────────────┐
│ Schema + Target DB Type → Azure GPT  │
└──────────────┬───────────────────────┘
               │
               ▼
    ┌──────────────────────────────────┐
    │ AI Generates Migration Plan       │
    │ - Table/Collection Mappings      │
    │ - Field Type Conversions         │
    │ - Denormalization Suggestions    │
    │ - Index Preservation             │
    └──────────────┬───────────────────┘
                   │
                   ▼
        ┌──────────────────────────┐
        │ Plan JSON Stored in      │
        │ Session for Review       │
        └──────────────────────────┘

Step 4: Human Review & Approval
┌────────────────────────────┐
│ Human Reviews Plan in UI   │
└────────────┬───────────────┘
             │
        ┌────▼─────┐
        │ Feedback? │ No feedback
        └────┬─────┘    │
             │          ▼
             │      Plan Approved
             │
        (Yes - Provide Feedback)
             │
             ▼
    ┌──────────────────────────┐
    │ update_plan API Call     │
    │ (Submit Feedback)        │
    └──────────────┬───────────┘
                   │
                   ▼
        ┌──────────────────────────┐
        │ Re-generate Plan with    │
        │ User Feedback            │
        └──────────────┬───────────┘
                       │
                       ▼
            ┌──────────────────┐
            │ Human Approves   │
            └─────────┬────────┘
                      │
                      ▼
        ┌───────────────────────────┐
        │ Final Plan Ready for Exec │
        └───────────┬───────────────┘
                    │
Step 5: Data Hydration & Execution
                    │
                    ▼
        ┌──────────────────────────┐
        │ execute_migration API    │
        │ (Trigger ETL Pipeline)   │
        └──────────────┬───────────┘
                       │
                       ▼
    ┌──────────────────────────────────┐
    │ Load Source Database Schema      │
    │ (Extract)                        │
    └──────────────┬───────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────┐
    │ Batch Query Source Data          │
    │ (Chunk into 1000-10000 rows)     │
    └──────────────┬───────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────┐
    │ Transform Using Plan Mappings    │
    │ - Type Conversions               │
    │ - Denormalization Logic          │
    │ - Derived Field Computation      │
    └──────────────┬───────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────┐
    │ Batch Load to Target Database    │
    │ (Load)                           │
    └──────────────┬───────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────┐
    │ Validation Check                 │
    │ - Row Count Match                │
    │ - Null Counts                    │
    │ - Sample Data Spot Check         │
    └──────────────┬───────────────────┘
                   │
                   ▼
    ┌──────────────────────────────────┐
    │ Update Migration Status          │
    │ (Frontend polls /status endpoint)│
    └──────────────────────────────────┘
```

### Dual-Database Query Data Flow

```
┌──────────────────────────────┐
│ User Natural Language Query  │ 
│ "Total revenue by month"     │
└──────────────┬───────────────┘
               │
               ▼
    ┌──────────────────────────────┐
    │ /generate-dual Endpoint      │
    └──────────────┬───────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │ Query Compiler Service       │
    │ (LLM + Template Engine)      │
    └──────────────┬───────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
   ┌─────────────────┐   ┌──────────────────┐
   │ SQL Compilation │   │ NoSQL Compilation│
   │                 │   │                  │
   │ SELECT          │   │ db.orders.       │
   │ DATE_TRUNC(...) │   │ aggregate([{...}])
   │ FROM orders     │   │                  │
   └────────┬────────┘   └────────┬─────────┘
            │                     │
            ▼                     ▼
    ┌──────────────────┐  ┌──────────────────┐
    │ Execute SQL      │  │ Execute NoSQL    │
    │ Query on Source  │  │ Query on Target  │
    │ Database         │  │ Database         │
    └────────┬─────────┘  └────────┬─────────┘
             │                     │
             ▼                     ▼
    ┌──────────────────┐  ┌──────────────────┐
    │ Result Set 1     │  │ Result Set 2     │
    │ (DataFrame)      │  │ (DataFrame)      │
    └────────┬─────────┘  └────────┬─────────┘
             │                     │
             └──────────┬──────────┘
                        │
                        ▼
        ┌─────────────────────────────┐
        │ Comparison & Alignment      │
        │ - Normalize Field Names     │
        │ - Match Data Types          │
        │ - Diff Detection            │
        └────────────┬────────────────┘
                     │
                     ▼
        ┌─────────────────────────────┐
        │ Response to Frontend        │
        │ {                           │
        │   source_result: { },       │
        │   target_result: { },       │
        │   diff_analysis: { }        │
        │ }                           │
        └─────────────────────────────┘
```

---

## Migration Pipeline Architecture

### Pipeline Inheritance Hierarchy

```
┌────────────────────────────────────────┐
│   BasePipeline (Abstract Base)         │
│   ─────────────────────────────────    │
│   Abstract Methods:                    │
│   • get_source_connection()            │
│   • get_target_connection()            │
│   • extract_schema()                   │
│   • transform_data(row) → dict/doc     │
│   • execute_migration()                │
│   • validate()                         │
│                                        │
│   Common Methods:                      │
│   • test_connections()                 │
│   • batch_extract(size=1000)           │
│   • batch_load(docs/rows)              │
│   • get_migration_status()             │
│   • error_handling()                   │
└────┬───────────────────────────────────┘
     │
     ├─────────────────────────┬──────────────────────┬──────────────────┐
     │                         │                      │                  │
     ▼                         ▼                      ▼                  ▼
┌─────────────────┐  ┌──────────────────┐  ┌────────────────┐  ┌─────────────────┐
│ MySQL→MongoDB   │  │ PostgreSQL→Mongo │  │ MySQL→CouchDB  │  │ PostgreSQL→Couch│
│ Pipeline        │  │ Pipeline         │  │ Pipeline       │  │ Pipeline        │
│                 │  │                  │  │                │  │                 │
│ Specific Logic: │  │ Specific Logic:  │  │ Specific Logic:│  │ Specific Logic: │
│ • Connection    │  │ • Connection     │  │ • Denormalize  │  │ • Denormalize   │
│ • Type Mapping  │  │ • Type Mapping   │  │ • JSON format  │  │ • JSON format   │
│ • Batch Size    │  │ • Batch Size     │  │ • Indexing     │  │ • Indexing      │
│ • Error Retry   │  │ • Error Retry    │  │ • Validation   │  │ • Validation    │
└─────────────────┘  └──────────────────┘  └────────────────┘  └─────────────────┘

     (5 More Pipelines for Reverse Directions)
```

### Pipeline Execution State Machine

```
┌─────────────────┐
│   INITIALIZED   │ (Pipeline object created, configs loaded)
└────────┬────────┘
         │ test_connections()
         ▼
┌─────────────────┐
│   VALIDATED     │ (Source & target DBs confirmed reachable)
└────────┬────────┘
         │ extract_schema()
         ▼
┌─────────────────┐
│   SCHEMA_READY  │ (Metadata extracted, ready for AI plan)
└────────┬────────┘
         │ execute_migration() [approved plan received]
         ▼
┌─────────────────┐
│   EXTRACTING    │ (Reading source DB in batches)
└────────┬────────┘
         │ [all source data extracted]
         ▼
┌─────────────────┐
│   TRANSFORMING  │ (Applying mappings, type conversions)
└────────┬────────┘
         │ [all data transformed]
         ▼
┌─────────────────┐
│   LOADING       │ (Writing to target DB in batches)
└────────┬────────┘
         │ [all data loaded]
         ▼
┌─────────────────┐
│   VALIDATING    │ (Row counts, null checks, spot validation)
└────────┬────────┘
         │ [validation passed]
         ▼
┌─────────────────┐
│   COMPLETED     │ (Migration successful, ready for QA)
└─────────────────┘

    (Error Path)
         │ [any error encountered]
         ▼
┌─────────────────┐
│   FAILED        │ (Error logged, migration halted, can retry)
└─────────────────┘
```

---

## Technology Stack

### Core Technologies

| Layer | Technology | Purpose | Version |
|-------|-----------|---------|---------|
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) | Web UI | ES6+ |
| **Backend** | Python 3.9+ | Core logic | 3.9-3.11 |
| **Framework** | FastAPI | REST API | 0.95+ |
| **Web Server** | Uvicorn | ASGI server | 0.20+ |
| **AI/LLM** | Azure OpenAI (GPT-4o) | Schema mapping & plan generation | Latest |
| **SQL ORM** | SQLAlchemy | SQL database abstraction | 1.4+ |
| **MySQL Driver** | PyMySQL / mysql-connector | MySQL connectivity | 1.0+ |
| **PostgreSQL Driver** | psycopg2 | PostgreSQL connectivity | 2.9+ |
| **MongoDB Driver** | PyMongo | MongoDB connectivity | 4.3+ |
| **CouchDB Client** | requests library | HTTP API calls to CouchDB | Custom |
| **Task Scheduler** | APScheduler / Celery (optional) | Background jobs | 3.10+ |
| **Logging** | Python logging | Event logging | Built-in |
| **Config Mgmt** | python-dotenv | Environment variables | 0.19+ |
| **Containerization** | Docker | Service containerization | 20.10+ |
| **Orchestration** | Docker Compose | Multi-container orchestration | 1.29+ |

### Database Support

| Database | Version | Deployment | Purpose |
|----------|---------|-----------|---------|
| PostgreSQL | 12+ | Neon Cloud, Self-hosted | SQL Source/Target |
| MySQL | 5.7+ | Docker, Self-hosted | SQL Source/Target |
| MongoDB | 5.0+ | Atlas Cloud, Self-hosted | NoSQL Source/Target |
| CouchDB | 3.0+ | Docker, Self-hosted | NoSQL Source/Target |

---

## Database Support Matrix

### Supported Migration Paths (9 Pipelines)

```
                    TO
FROM      ┌─────────┬─────────┬─────────┬──────────┐
          │PostgreSQL│ MySQL   │ MongoDB │ CouchDB  │
┌─────────┼─────────┼─────────┼─────────┼──────────┤
│PostgreSQL│    —    │   ❌    │   ✅    │    ✅    │
├─────────┼─────────┼─────────┼─────────┼──────────┤
│ MySQL   │   ❌    │    —    │   ✅    │    ✅    │
├─────────┼─────────┼─────────┼─────────┼──────────┤
│ MongoDB │   ✅    │   ✅    │    —    │    ✅    │
├─────────┼─────────┼─────────┼─────────┼──────────┤
│ CouchDB │   ✅    │   ✅    │   ✅    │    —     │
└─────────┴─────────┴─────────┴─────────┴──────────┘

✅ = Implemented  |  ❌ = Planned  |  — = N/A
```

### Pipeline Implementation Matrix

| Pipeline ID | Source | Target | File Name | Status | Features |
|------------|--------|--------|-----------|--------|----------|
| 1 | MySQL | MongoDB | `mysql_to_mongo.py` | ✅ Prod | Batch load, validation |
| 2 | MySQL | CouchDB | `mysql_to_couchdb.py` | ✅ Prod | JSON conversion, indexing |
| 3 | PostgreSQL | MongoDB | `postgres_to_mongo.py` | ✅ Prod | Neon support, bulk insert |
| 4 | PostgreSQL | CouchDB | `postgres_to_couchdb.py` | ✅ Prod | JSONB support, mapping |
| 5 | MongoDB | MySQL | `mongo_to_mysql.py` | ✅ Prod | Denorm handling, schema gen |
| 6 | MongoDB | PostgreSQL | `mongo_to_postgres.py` | ✅ Prod | Array flattening, normalization |
| 7 | MongoDB | CouchDB | `mongo_to_couchdb.py` | ✅ Prod | Direct JSON transfer |
| 8 | CouchDB | MySQL | `couchdb_to_mysql.py` | ✅ Prod | Schema inference, indexing |
| 9 | CouchDB | PostgreSQL | `couchdb_to_postgres.py` | ✅ Prod | Normalization, relations |

---

## API Architecture

### REST API Structure

```
/api/
├── /pipelines
│   └── GET: List all supported pipeline configurations
│
├── /test-connection
│   └── POST: Verify database connectivity & credentials
│
├── /extract-schema
│   └── POST: Analyze source DB structure & metadata
│
├── /generate-plan
│   └── POST: Create AI-assisted migration blueprint
│
├── /update-plan
│   └── POST: Apply human feedback to migration plan
│
├── /execute-migration
│   └── POST: Trigger ETL execution with validated plan
│
├── /migration-status/{session_id}
│   └── GET: Poll migration progress & metrics
│
├── /connect-dual
│   └── POST: Initialize dual-database comparison environment
│
├── /generate-dual
│   └── POST: Execute NLP query against both databases
│
└── /health
    └── GET: Service health & version info
```

### Request/Response Patterns

**Authentication & Security:**
- CORS enabled for frontend communication
- Optional API key validation (configurable)
- Session-based state management for long-running migrations

**Response Format:**
```json
{
  "status": "success|error",
  "data": { /* Response payload */ },
  "session_id": "uuid",
  "timestamp": "ISO-8601",
  "error": null | { "code": "...", "message": "..." }
}
```

---

## Security Architecture

### Security Layers

```
┌──────────────────────────────────────────────────────────┐
│  1. Network Security                                     │
│  • HTTPS/TLS for all communications                      │
│  • CORS configuration for domain whitelisting            │
│  • Firewall rules for database access                    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  2. Authentication & Authorization                       │
│  • API key validation (if enabled)                       │
│  • Session token management                              │
│  • Role-based access control (future)                    │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  3. Credential Management                                │
│  • Environment variables for sensitive data              │
│  • No hardcoded passwords in code                        │
│  • Connection string masking in logs                     │
│  • Encrypted session storage (planned)                   │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  4. Data Protection                                      │
│  • Input validation & sanitization                       │
│  • SQL injection prevention (SQLAlchemy parameterization)│
│  • NoSQL injection prevention (PyMongo)                  │
│  • Batch encryption for data in transit (planned)        │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│  5. Audit & Logging                                      │
│  • All API calls logged with timestamp                   │
│  • Migration history maintained                          │
│  • Error tracking & alerting                             │
│  • Redaction of sensitive data in logs                   │
└──────────────────────────────────────────────────────────┘
```

---

## Scalability & Performance

### Performance Characteristics

| Metric | Current | Target | Strategy |
|--------|---------|--------|----------|
| **Batch Size** | 1,000-10,000 rows | 50,000+ | Configurable batching |
| **Migration Speed** | ~100K rows/min | 1M+ rows/min | Async workers, parallelization |
| **Concurrent Migrations** | 1-3 | 10+ | Celery task queue |
| **API Response Time** | <500ms | <200ms | Caching, async I/O |
| **Schema Extraction** | 30-60sec | <10sec | Intelligent sampling |

### Scalability Strategies

```
Current Architecture (Single-Instance)
    ┌──────────────────┐
    │  Single FastAPI  │
    │  Instance        │
    │  • 1 Python proc │
    │  • In-memory     │
    │    sessions      │
    └─────────┬────────┘

Future Architecture (Distributed)
    ┌──────────────────┐
    │  Load Balancer   │
    │  (Nginx/HAProxy) │
    └────────┬─────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌────────────────┐ ┌────────────────┐
│ FastAPI API #1 │ │ FastAPI API #2 │ (Horizontal scaling)
└────┬───────────┘ └────┬───────────┘
     │                  │
     └────────┬─────────┘
              │
         ┌────▼────────────┐
         │ Redis Cache &   │
         │ Session Store   │
         └────────────────┘
              │
         ┌────▼───────────┐
         │ Task Queue     │
         │ (Celery)       │
         └────┬───────────┘
              │
         ┌────▼────────────────────────┐
         │ Worker Pool (Background     │
         │ Migration Tasks)            │
         └─────────────────────────────┘
```

---

## Deployment Architecture

### Docker Compose Stack

```yaml
Services:
├── backend
│   └── FastAPI application (port 8000)
├── mysql
│   └── MySQL database container (port 3310)
├── postgres
│   └── PostgreSQL container (port 5432) [optional]
├── mongodb
│   └── MongoDB container (port 27017) [optional]
├── couchdb
│   └── CouchDB container (port 5984)
├── redis
│   └── Redis cache (port 6379) [optional]
└── phpmyadmin
    └── MySQL UI (port 8081) [optional]
```

### Deployment Targets

```
Development
├── Docker Compose (local)
├── Self-managed containers
└── Direct Python execution

Staging
├── Cloud container platform (Azure Container Instances)
├── Managed Kubernetes (AKS)
└── Platform-as-a-Service (Heroku, Render)

Production
├── Kubernetes cluster (AKS, EKS, GKE)
├── Container orchestration with auto-scaling
├── Load balancing & SSL termination
├── Database high availability
└── Monitoring & alerting infrastructure
```

---

## Architecture Decision Records (ADRs)

### ADR-1: Why FastAPI?
- **Decision:** Use FastAPI for backend REST API
- **Rationale:** 
  - High performance (built on Starlette & Pydantic)
  - Async/await support for non-blocking I/O
  - Automatic API documentation (Swagger UI)
  - Type safety with Python type hints
  - Growing ecosystem & community support

### ADR-2: Why Azure OpenAI?
- **Decision:** Use Azure OpenAI GPT-4o for schema mapping
- **Rationale:**
  - Superior schema understanding vs base LLMs
  - Enterprise-grade security & compliance
  - Fine-tuning capabilities for domain-specific models
  - Reliable API with SLA guarantees

### ADR-3: Why Plugin Architecture?
- **Decision:** Implement pipeline registry with plugin-style inheritance
- **Rationale:**
  - Easy to add new database pairs (9 pipelines currently)
  - Code reuse through base pipeline abstraction
  - Minimal coupling between pipeline implementations
  - Extensible without modifying core framework

### ADR-4: Why Session-Based Orchestration?
- **Decision:** Track migrations using session IDs & in-memory state
- **Rationale:**
  - Lightweight for MVP
  - Sufficient for current concurrency requirements
  - Easily migrate to distributed queue (Celery) in future
  - Human-in-the-loop approval requires session persistence

---

## Conclusion

QueryVista's architecture is designed to be:
- **Modular:** Plugin-based pipelines enable easy database pair additions
- **Transparent:** Human-in-the-loop ensures no hidden failures
- **Scalable:** From MVP to enterprise with Kubernetes support
- **Secure:** Multiple layers of data protection and access control
- **Maintainable:** Clear separation of concerns and extensive documentation

The architecture balances current MVP simplicity with future enterprise-grade scaling requirements.
