"""
Archival API Service
Provides REST API for file upload, cataloging, and archival workflow
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydantic_settings import BaseSettings
import psycopg
from psycopg.rows import dict_row


class Settings(BaseSettings):
    database_url: str = "postgresql://archival:dev-password-change-in-production@postgres:5432/scottfiles"
    upload_dir: str = "/uploads"
    staging_dir: str = "/staging"
    ipfs_api_addr: str = "/ip4/172.30.0.21/tcp/5001"
    ccs_profile: str = "test-org1"


settings = Settings()
app = FastAPI(title="Archival API", version="0.1.0")

# Enable CORS for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure directories exist
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.staging_dir).mkdir(parents=True, exist_ok=True)


def get_db_connection():
    """Get PostgreSQL database connection"""
    return psycopg.connect(settings.database_url)


# ============================================================================
# MODELS
# ============================================================================

class UploadResponse(BaseModel):
    success: bool
    filename: str
    path: str
    size: int
    message: str


class ArchivalStatus(BaseModel):
    pending_files: int
    pending_size: int
    total_commits: int
    latest_commit: Optional[dict] = None


class FileInfo(BaseModel):
    path: str
    size: int
    mtime: int
    commit_id: Optional[str] = None
    cid_enc: Optional[str] = None
    content_hash: Optional[str] = None


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.get("/api")
async def api_info():
    """API information endpoint"""
    return {
        "service": "Archival API",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "POST /upload": "Upload files for archival",
            "GET /status": "Get archival status",
            "GET /files": "List cataloged files",
            "POST /catalog": "Run filelister scan",
            "POST /archive": "Run ntx archival",
        }
    }


@app.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """
    Upload a file to the archival system

    Files are saved to the upload directory and will be cataloged
    by the next filelister scan.
    """
    try:
        # Create dated subdirectory
        date_dir = Path(settings.upload_dir) / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        # Save uploaded file
        file_path = date_dir / file.filename
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        file_size = len(content)

        return UploadResponse(
            success=True,
            filename=file.filename,
            path=str(file_path),
            size=file_size,
            message=f"File uploaded successfully. Run /catalog to add to database."
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.get("/status", response_model=ArchivalStatus)
async def get_status():
    """
    Get current archival system status

    Returns counts of pending files and completed commits.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Count pending files
                cur.execute("""
                    SELECT COUNT(*) as count, COALESCE(SUM(size), 0) as total_size
                    FROM paths
                    WHERE commit_id IS NULL
                      AND deleted_at_run IS NULL
                      AND filetype = 'f'
                """)
                pending = cur.fetchone()

                # Count total commits
                cur.execute("SELECT COUNT(*) as count FROM commits")
                commits = cur.fetchone()

                # Get latest commit
                cur.execute("""
                    SELECT id, merkle_root, leaf_count, created_at, completed_at
                    FROM commits
                    ORDER BY sequence DESC
                    LIMIT 1
                """)
                latest = cur.fetchone()

                return ArchivalStatus(
                    pending_files=pending['count'],
                    pending_size=pending['total_size'],
                    total_commits=commits['count'],
                    latest_commit=dict(latest) if latest else None
                )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


@app.get("/files")
async def list_files(limit: int = 100, offset: int = 0, archived_only: bool = False):
    """
    List cataloged files

    Query parameters:
    - limit: Number of files to return (default 100)
    - offset: Pagination offset (default 0)
    - archived_only: Only show archived files with CIDs (default false)
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                where_clause = ""
                if archived_only:
                    where_clause = "WHERE commit_id IS NOT NULL"

                cur.execute(f"""
                    SELECT
                        encode(path, 'escape') as path,
                        size,
                        mtime,
                        commit_id,
                        cid_enc,
                        content_hash,
                        run_end_time
                    FROM paths
                    {where_clause}
                    ORDER BY run_end_time DESC NULLS LAST, mtime DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))

                files = cur.fetchall()

                # Count total
                cur.execute(f"SELECT COUNT(*) as count FROM paths {where_clause}")
                total = cur.fetchone()['count']

                return {
                    "files": [dict(f) for f in files],
                    "total": total,
                    "limit": limit,
                    "offset": offset
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@app.post("/catalog")
async def run_catalog(background_tasks: BackgroundTasks):
    """
    Run filelister scan to catalog uploaded files

    This runs a simplified version of filelister that scans the upload directory
    and adds file metadata to the database.

    Note: This is a simplified implementation for the prototype.
    Production uses the full filelister tool.
    """
    try:
        # Simple implementation: directly scan upload directory and insert
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                upload_path = Path(settings.upload_dir)
                run_end_time = datetime.now()

                files_added = 0
                for file_path in upload_path.rglob("*"):
                    if file_path.is_file():
                        stat = file_path.stat()

                        # Insert into database
                        cur.execute("""
                            INSERT INTO paths (path, filetype, size, mtime, run_end_time)
                            VALUES (%s, 'f', %s, %s, %s)
                            ON CONFLICT (path, size, mtime) DO NOTHING
                        """, (
                            str(file_path).encode('utf-8'),
                            stat.st_size,
                            int(stat.st_mtime),
                            run_end_time
                        ))

                        if cur.rowcount > 0:
                            files_added += 1

                conn.commit()

                return {
                    "success": True,
                    "files_added": files_added,
                    "message": f"Cataloged {files_added} new files"
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Catalog failed: {str(e)}")


@app.post("/archive")
async def run_archive(
    background_tasks: BackgroundTasks,
    size_limit_gb: float = 0.1,  # Small default for prototype
    dry_run: bool = False
):
    """
    Run archival process (simplified ntx workflow)

    This is a SIMPLIFIED prototype implementation that demonstrates the workflow:
    1. Claim files from database
    2. Hash files (BLAKE3)
    3. Create mock commit
    4. Update database with mock CIDs

    Query parameters:
    - size_limit_gb: Maximum batch size in GB (default 0.1 for prototype)
    - dry_run: Don't actually commit changes (default false)

    Note: This is simplified for the prototype. Production ntx includes:
    - Encryption (XChaCha20-Poly1305)
    - Merkle tree creation
    - Ed25519 signatures
    - OpenTimestamps (Bitcoin anchoring)
    - IPFS cluster upload
    - S3 backup
    """
    try:
        size_limit_bytes = int(size_limit_gb * 1024 * 1024 * 1024)

        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                # Get pending files up to size limit
                cur.execute("""
                    SELECT encode(path, 'escape') as path, size, mtime
                    FROM paths
                    WHERE commit_id IS NULL
                      AND deleted_at_run IS NULL
                      AND filetype = 'f'
                    ORDER BY size ASC
                """)

                files_to_archive = []
                total_size = 0
                for row in cur:
                    if total_size + row['size'] > size_limit_bytes:
                        break
                    files_to_archive.append(row)
                    total_size += row['size']

                if not files_to_archive:
                    return {
                        "success": True,
                        "files_archived": 0,
                        "message": "No pending files to archive"
                    }

                if dry_run:
                    return {
                        "success": True,
                        "dry_run": True,
                        "files_to_archive": len(files_to_archive),
                        "total_size": total_size,
                        "files": files_to_archive
                    }

                # Create commit
                commit_id = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
                cur.execute("""
                    INSERT INTO commits (id, merkle_root, leaf_count, sequence)
                    VALUES (%s, %s, %s, nextval('commit_sequence'))
                    RETURNING sequence
                """, (commit_id, "mock-merkle-root-" + commit_id, len(files_to_archive)))

                sequence = cur.fetchone()['sequence']

                # Claim files and add mock CIDs
                for file_info in files_to_archive:
                    mock_cid = f"mock-cid-{sequence}-{file_info['path'][:20]}"

                    cur.execute("""
                        UPDATE paths
                        SET commit_id = %s,
                            cid_enc = %s,
                            content_hash = %s
                        WHERE path = %s AND size = %s AND mtime = %s
                    """, (
                        commit_id,
                        mock_cid,
                        f"mock-hash-{file_info['path'][:20]}",
                        file_info['path'].encode('utf-8'),
                        file_info['size'],
                        file_info['mtime']
                    ))

                # Mark commit as completed
                cur.execute("""
                    UPDATE commits
                    SET completed_at = NOW()
                    WHERE id = %s
                """, (commit_id,))

                conn.commit()

                return {
                    "success": True,
                    "commit_id": commit_id,
                    "files_archived": len(files_to_archive),
                    "total_size": total_size,
                    "message": f"Archived {len(files_to_archive)} files in commit {commit_id}",
                    "note": "This is a simplified prototype. Production includes encryption, signatures, and IPFS upload."
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Archive failed: {str(e)}")


@app.get("/commits")
async def list_commits(limit: int = 50):
    """List recent commits"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT
                        id,
                        sequence,
                        merkle_root,
                        leaf_count,
                        created_at,
                        completed_at,
                        commit_cid
                    FROM commits
                    ORDER BY sequence DESC
                    LIMIT %s
                """, (limit,))

                commits = cur.fetchall()

                return {
                    "commits": [dict(c) for c in commits],
                    "total": len(commits)
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list commits: {str(e)}")


# ============================================================================
# SERVE STATIC FILES (Vue UI)
# ============================================================================

# Mount static files last so API routes take precedence
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
