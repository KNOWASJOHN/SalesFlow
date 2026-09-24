# Sales Interaction Tracking and Analytics System - Backend (Module 1)

This is Module 1 (Foundation & Health) of the Sales Interaction Tracking and Analytics System. It contains the fundamental project setup, database connectivity configuration using SQLAlchemy and psycopg, and a health check endpoint.

## Setup Instructions

1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate a virtual environment** (optional but recommended):
   ```bash
   python -m venv venv
   # On Windows (PowerShell):
   .\venv\Scripts\Activate.ps1
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Verify `.env` configuration**:
   Ensure the `.env` file exists with your correct `DATABASE_URL`. It should point to the `sales_postgres` container running locally.

5. **Run the server**:
   ```bash
   uvicorn app.main:app --reload
   ```

## Acceptance Checks

To verify the setup is working correctly:

1. Ensure the server starts without errors by running `uvicorn app.main:app --reload`.
2. With the PostgreSQL Docker container (`sales_postgres`) running, send a GET request to `/health` (e.g., by visiting `http://localhost:8000/health` in your browser). It should return `{"status": "ok", "database": "connected"}`.
3. Stop the Postgres container (e.g., run `docker stop sales_postgres` in a new terminal) and send another GET request to `/health`. It should return a 503 Service Unavailable error with a JSON payload indicating the database is disconnected, without crashing the server.
