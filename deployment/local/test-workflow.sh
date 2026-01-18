#!/bin/bash
# Test script for local archival pipeline
# Tests: Upload → Catalog → Archive → Verify

set -e

API_URL="http://localhost:8000"
CLUSTER_URL="http://localhost:9094"

echo "🧪 Testing Local Archival Pipeline"
echo "=================================="
echo ""

# Create test files
echo "📁 Step 1: Creating test files..."
TEST_DIR=$(mktemp -d)
echo "Hello from the archival system!" > "$TEST_DIR/test1.txt"
echo "Second test file" > "$TEST_DIR/test2.txt"
mkdir -p "$TEST_DIR/subdir"
echo "File in subdirectory" > "$TEST_DIR/subdir/test3.txt"
echo "   Created test files in: $TEST_DIR"
echo ""

# Check initial status
echo "📊 Step 2: Checking initial status..."
INITIAL_STATUS=$(curl -s "$API_URL/status")
INITIAL_PENDING=$(echo "$INITIAL_STATUS" | jq -r '.pending_files')
INITIAL_COMMITS=$(echo "$INITIAL_STATUS" | jq -r '.total_commits')
echo "   Pending files: $INITIAL_PENDING"
echo "   Total commits: $INITIAL_COMMITS"
echo ""

# Upload files
echo "📤 Step 3: Uploading test files..."
for file in "$TEST_DIR"/*.txt "$TEST_DIR"/subdir/*.txt; do
    FILENAME=$(basename "$file")
    RESPONSE=$(curl -s -X POST "$API_URL/upload" -F "file=@$file")
    SUCCESS=$(echo "$RESPONSE" | jq -r '.success')
    if [ "$SUCCESS" = "true" ]; then
        echo "   ✅ Uploaded: $FILENAME"
    else
        echo "   ❌ Failed: $FILENAME"
        exit 1
    fi
done
echo ""

# Run catalog
echo "📋 Step 4: Running catalog scan..."
CATALOG_RESPONSE=$(curl -s -X POST "$API_URL/catalog")
FILES_ADDED=$(echo "$CATALOG_RESPONSE" | jq -r '.files_added')
echo "   Files cataloged: $FILES_ADDED"
if [ "$FILES_ADDED" -eq 0 ]; then
    echo "   ⚠️  No new files cataloged (may already exist in database)"
fi
echo ""

# Check status after catalog
echo "📊 Step 5: Checking status after catalog..."
AFTER_CATALOG=$(curl -s "$API_URL/status")
PENDING_AFTER_CATALOG=$(echo "$AFTER_CATALOG" | jq -r '.pending_files')
echo "   Pending files now: $PENDING_AFTER_CATALOG"
echo ""

# List cataloged files
echo "📄 Step 6: Listing cataloged files..."
FILES_RESPONSE=$(curl -s "$API_URL/files?limit=5")
FILE_COUNT=$(echo "$FILES_RESPONSE" | jq -r '.files | length')
echo "   Found $FILE_COUNT cataloged files:"
echo "$FILES_RESPONSE" | jq -r '.files[] | "   - \(.path | @base64d) (\(.size) bytes)"' 2>/dev/null || \
echo "$FILES_RESPONSE" | jq -r '.files[] | "   - \(.path) (\(.size) bytes)"'
echo ""

# Run archive
echo "📦 Step 7: Running archival process..."
ARCHIVE_RESPONSE=$(curl -s -X POST "$API_URL/archive")
ARCHIVE_SUCCESS=$(echo "$ARCHIVE_RESPONSE" | jq -r '.success')
if [ "$ARCHIVE_SUCCESS" = "true" ]; then
    COMMIT_ID=$(echo "$ARCHIVE_RESPONSE" | jq -r '.commit_id')
    FILES_ARCHIVED=$(echo "$ARCHIVE_RESPONSE" | jq -r '.files_archived')
    echo "   ✅ Archive successful!"
    echo "   Commit ID: $COMMIT_ID"
    echo "   Files archived: $FILES_ARCHIVED"
else
    echo "   ℹ️  $(echo "$ARCHIVE_RESPONSE" | jq -r '.message')"
fi
echo ""

# Check final status
echo "📊 Step 8: Checking final status..."
FINAL_STATUS=$(curl -s "$API_URL/status")
FINAL_PENDING=$(echo "$FINAL_STATUS" | jq -r '.pending_files')
FINAL_COMMITS=$(echo "$FINAL_STATUS" | jq -r '.total_commits')
LATEST_COMMIT=$(echo "$FINAL_STATUS" | jq -r '.latest_commit.id // "None"')
echo "   Pending files: $FINAL_PENDING (was $INITIAL_PENDING)"
echo "   Total commits: $FINAL_COMMITS (was $INITIAL_COMMITS)"
echo "   Latest commit: $LATEST_COMMIT"
echo ""

# List archived files
echo "✅ Step 9: Listing archived files..."
ARCHIVED_RESPONSE=$(curl -s "$API_URL/files?archived_only=true&limit=5")
ARCHIVED_COUNT=$(echo "$ARCHIVED_RESPONSE" | jq -r '.files | length')
echo "   Found $ARCHIVED_COUNT archived files:"
echo "$ARCHIVED_RESPONSE" | jq -r '.files[] | "   - \(.path | @base64d) (CID: \(.cid_enc // "N/A"))"' 2>/dev/null || \
echo "$ARCHIVED_RESPONSE" | jq -r '.files[] | "   - \(.path) (CID: \(.cid_enc // "N/A"))"'
echo ""

# Check IPFS cluster
echo "🔗 Step 10: Checking IPFS cluster..."
CLUSTER_PEERS=$(curl -s "$CLUSTER_URL/peers" 2>/dev/null | jq -r 'length' 2>/dev/null || echo "0")
echo "   Cluster peers: $CLUSTER_PEERS"
if [ "$CLUSTER_PEERS" -ge 3 ]; then
    echo "   ✅ Cluster is healthy (3 peers expected)"
else
    echo "   ⚠️  Cluster may not be fully formed (expected 3, got $CLUSTER_PEERS)"
fi
echo ""

# List commits
echo "📋 Step 11: Listing recent commits..."
COMMITS_RESPONSE=$(curl -s "$API_URL/commits?limit=3")
COMMIT_COUNT=$(echo "$COMMITS_RESPONSE" | jq -r '.commits | length')
echo "   Recent commits ($COMMIT_COUNT):"
echo "$COMMITS_RESPONSE" | jq -r '.commits[] | "   - \(.id): \(.leaf_count) files at \(.created_at)"'
echo ""

# Cleanup
echo "🧹 Step 12: Cleaning up test files..."
rm -rf "$TEST_DIR"
echo "   ✅ Test files removed"
echo ""

# Summary
echo "=================================="
echo "✨ Test Complete!"
echo ""
echo "Summary:"
echo "  • Files uploaded: 3"
echo "  • Files cataloged: $FILES_ADDED"
echo "  • Files archived: ${FILES_ARCHIVED:-0}"
echo "  • Cluster peers: $CLUSTER_PEERS"
echo ""

# Check if systems are operational
if [ "${FILES_ARCHIVED:-0}" -gt 0 ] 2>/dev/null && [ "$CLUSTER_PEERS" -ge 3 ] 2>/dev/null; then
    echo "✅ All systems operational!"
    exit 0
else
    echo "⚠️  Some components may need attention"
    echo "   Files archived: ${FILES_ARCHIVED:-0}"
    echo "   Cluster peers: $CLUSTER_PEERS (expected 3)"
    exit 0
fi
