-- Initialize scottfiles database schema
-- Combines filelister and ntx schemas

-- ============================================================================
-- FILELISTER SCHEMA
-- ============================================================================

CREATE TABLE paths (
    path BYTEA NOT NULL,
    filetype CHAR(1),
    size BIGINT,
    mtime BIGINT,
    link_target BYTEA,
    run_end_time TIMESTAMPTZ,

    -- ntx additions
    content_hash TEXT,
    commit_id TEXT,
    cid_enc TEXT,
    cid_sidecar TEXT,
    encrypted_size BIGINT,
    s3_uploaded_at TIMESTAMPTZ,
    deleted_at_run TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_paths_unique ON paths (path, size, mtime);
CREATE INDEX IF NOT EXISTS idx_paths_commit_id ON paths(commit_id) WHERE commit_id IS NOT NULL;
CREATE INDEX idx_paths_cid_enc ON paths(cid_enc) WHERE cid_enc IS NOT NULL;

-- Staging table (unlogged for performance)
CREATE UNLOGGED TABLE paths_staging (LIKE paths INCLUDING ALL);

-- ============================================================================
-- NTX SCHEMA
-- ============================================================================

CREATE TABLE commits (
    id TEXT PRIMARY KEY,              -- ISO timestamp (commit_id)
    sequence BIGINT UNIQUE,           -- Sequential commit number
    merkle_root TEXT NOT NULL,        -- Root hash of Merkle tree
    leaf_count INTEGER NOT NULL,      -- Number of files in commit

    -- Lifecycle timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signed_at TIMESTAMPTZ,
    ots_submitted_at TIMESTAMPTZ,
    ots_confirmed_at TIMESTAMPTZ,
    uploaded_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- IPFS CIDs
    commit_cid TEXT,                  -- Root directory CID
    manifest_cid TEXT,                -- manifest.json CID
    manifest_ots_cid TEXT,            -- merkle_root.ots CID

    -- S3 backup
    s3_uploaded_at TIMESTAMPTZ,
    s3_completed_at TIMESTAMPTZ
);

CREATE INDEX idx_commits_sequence ON commits(sequence);
CREATE INDEX idx_commits_created_at ON commits(created_at);

-- Sequence for commit numbers
CREATE SEQUENCE commit_sequence START 1;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get next commit ID
CREATE OR REPLACE FUNCTION next_commit_id() RETURNS TEXT AS $$
BEGIN
    RETURN TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"');
END;
$$ LANGUAGE plpgsql;

-- Function to count pending files
CREATE OR REPLACE FUNCTION count_pending_files() RETURNS TABLE (
    count BIGINT,
    total_size BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*),
        COALESCE(SUM(size), 0)
    FROM paths
    WHERE cid_enc IS NULL
      AND commit_id IS NULL
      AND deleted_at_run IS NULL
      AND filetype = 'f'
      AND content_hash IS NULL;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions
GRANT ALL ON ALL TABLES IN SCHEMA public TO archival;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO archival;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO archival;
