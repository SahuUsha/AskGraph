# cURL Tests for Multi-DB SQL Agent

This document contains a series of cURL commands you can run to test the endpoints of the FastAPI application.
Run the application locally (`uvicorn app.main:app --reload`) or via Docker before running these tests.

## 1. Test Root Endpoint (Frontend HTML)
```bash
curl -X GET "http://localhost:8000/"
```

## 2. Get All Schemas
Fetches all tables from the connected database. Replace the `db_url` with your actual database URL if different.
```bash
curl -X POST "http://localhost:8000/schemas" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
         }'
```

## 3. Get Table Details
Replace `YOUR_TABLE_NAME` with an actual table name from your schema.
```bash
curl -X POST "http://localhost:8000/schemas/YOUR_TABLE_NAME" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
         }'
```

## 4. Get Table Data with Pagination
```bash
curl -X POST "http://localhost:8000/schemas/YOUR_TABLE_NAME/data" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require",
           "page": 1,
           "limit": 50
         }'
```

## 5. Generate SQL Insight / Analysis
Asks the AI to generate a SQL query based on the database schema to answer your natural language query.
```bash
curl -X POST "http://localhost:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require",
           "query": "Show me the top 5 records from the database",
           "safe_mode": true
         }'
```

## 6. Generate Insights Dashboard
Generates a full dashboard plan with multiple charts powered by AI.
```bash
curl -X POST "http://localhost:8000/gen-dashboard" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
         }'
```

## 6b. Stream the Dashboard
Same dashboard, one NDJSON line per panel as each finishes. `curl -N` disables
curl's own buffering so the frames print as they land.
```bash
curl -N -X POST "http://localhost:8000/gen-dashboard/stream" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
         }'
```

## 6c. Export Dashboard Charts as a Zip
Takes the charts the browser already rendered and returns a zip holding one
`.png` and one `.txt` (title + description) per chart.
```bash
curl -X POST "http://localhost:8000/dashboard/export" \
     -o askgraph-dashboard.zip \
     -H "Content-Type: application/json" \
     -d '{
           "charts": [
             {"title": "Revenue by month", "description": "...", "graph_base64": "iVBORw0KGgo..."}
           ]
         }'
```

## 7. Data Health Check
Probes every table for nulls, orphaned foreign keys, duplicate keys and
implausible values. No question and no AI call — just SQL.
```bash
curl -X POST "http://localhost:8000/data-health" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
         }'
```

## 8. Optimize SQL
Explains and optimizes an existing SQL query.
```bash
curl -X POST "http://localhost:8000/optimize" \
     -H "Content-Type: application/json" \
     -d '{
           "db_url": "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require",
           "query": "SELECT * FROM my_table WHERE id > 0"
         }'
```
