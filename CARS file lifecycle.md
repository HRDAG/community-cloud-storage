CARS file lifecycle

1. New files retrieved by filelister (from 3rd party sources like dropbox, local filesystem). Saves db with raw metadata about files (path, timestamp, size)

2. NTXv3 polls the scottfiles db for the new files, bundles them into 1 or more 1gb commits. Handles all the OTSing, slicing, bundling, encrypting, signing, manfisting. One single NTX call does everything. Leaves a commit direectory in place with the slices and metadata files there, and the db records in pending state. At this point the commits are staging, and live only on local fs and referenced in db.

3. Pushing phase: NTXv3 polls scottfiles db and looks for commits that haven't been pushed to a backend (e.g., IPFS, S3, dropbox, other fs). Results stored in db table.

4. Auto-verification phase: NTXv3 polls db for unverified commits (currently just s3-verify). Once verified, update state in db (last check timestamp).

5. Manual restore: do a local restore and verificaiton of a commited file

CARS core requirements:

- Allow uploading folders or directories through the web UI (much like Box or Dropbox)
- Basic auth (via username/password for now). Default is "admin/admin".
- Once files are uploaded, the UI will display their archival process along the lifecycle states.
- File browsing view will show timestamp uploaded, and owner.
- Once archival is done, it will show a nice user-friendly array of checkboxes showing progress of upload -> OTS, slicing, bundling, encrypting, signing, manifesting, backing up to backends (just ipfs and s3 for now)
- Archival status by file (NTX doesnt support this yet but soon)
- Retrieve, download and verify files from different backends
