# SyncToHDD

A self-hosted file sync & backup tool with a web dashboard — designed to back up a Linux server to an external USB HDD.

## Features

- **Multi-pair sync** — configure multiple source → destination directory pairs
- **Incremental** — only copies new or modified files (mtime + size, optional checksum)
- **Web UI** — monitor active syncs, browse run history, and inspect file-level changes
- **Cross-platform** — uses `rsync` on Linux, pure-Python fallback on Windows
- **Docker-ready** — single-container deployment with volume mounts
- **Run history** — every sync run is logged with full change details (added / modified / deleted)
- **Dry-run mode** — preview what would change before committing
- **Real-time progress** — live updates via Server-Sent Events (SSE)

## Quick Start

### Prerequisites

- Python 3.11+
- `rsync` (Linux — optional but recommended; the engine falls back to pure Python)

### Local

```bash
# Clone the repo
git clone https://github.com/<your-user>/SyncToHDD.git
cd SyncToHDD

# Create a virtual environment
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt

# Edit config
cp config.yaml.example config.yaml   # then edit your sync pairs

# Run
python -m synctohdd.main
```

Open **http://localhost:6060** in your browser.

### Docker

```bash
# Build and run
docker compose up -d

# View logs
docker compose logs -f synctohdd
```

Make sure to edit `docker-compose.yml` to mount your source and destination volumes.

## Configuration

Edit `config.yaml` to define your sync pairs:

```yaml
sync_pairs:
  - name: "Manga CBZ Backup"
    source: "/sg2b/Share2sgb/Manga/Manga_CBZ_1"
    destination: "/media/devmon/LX2T/BackupServer"
    mode: "mirror"          # mirror | additive
    exclude:
      - "*.tmp"
      - ".thumbs/"
    checksum: false
    bandwidth_limit: null

server:
  host: "0.0.0.0"
  port: 6060
  log_level: "info"

database:
  path: "./data/synctohdd.db"
```

| Option | Description |
|--------|-------------|
| `mode: mirror` | Deletes files at destination that no longer exist at source |
| `mode: additive` | Only adds/updates files, never deletes |
| `checksum: true` | Uses SHA-256 instead of mtime+size for comparison (slower) |
| `bandwidth_limit` | Rate limit, e.g. `"50M"` for 50 MB/s |
| `exclude` | Glob patterns for files/directories to skip |

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2.0 |
| Frontend | Jinja2, HTMX, vanilla CSS/JS |
| Database | SQLite (WAL mode) |
| Sync Engine | rsync (Linux) / shutil (cross-platform fallback) |
| Deployment | Docker, docker-compose |

## Project Structure

```
SyncToHDD/
├── synctohdd/           # Main Python package
│   ├── main.py          # Entry point
│   ├── config.py        # Config loader
│   ├── engine/          # Sync backends
│   ├── api/             # FastAPI routes
│   ├── db/              # SQLAlchemy models & CRUD
│   └── web/             # Templates & static assets
├── config.yaml          # Sync pair configuration
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── PLAN.md              # Detailed project plan
```

## License

MIT
