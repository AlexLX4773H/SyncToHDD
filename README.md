# SyncToHDD

A self-hosted file sync & backup tool with a web dashboard — designed to back up a Linux server to an external USB HDD.

![SyncToHDD Icon](assets/icon.png)

## Features

- **Multi-pair sync** — configure multiple source → destination directory pairs
- **Incremental** — only copies new or modified files (mtime + size, optional checksum)
- **Web UI** — monitor active syncs, browse run history, and inspect file-level changes
- **CasaOS & Docker Ready** — native `x-casaos` support for 1-click install from the CasaOS dashboard
- **Cross-platform** — uses `rsync` on Linux, pure-Python fallback on Windows
- **Run history** — every sync run is logged with full change details (added / modified / deleted)
- **Dry-run mode** — preview what would change before committing
- **Real-time progress** — live updates via Server-Sent Events (SSE)

---

## Running in CasaOS (Ubuntu Server)

SyncToHDD is designed to run directly on **Ubuntu Server with CasaOS** and opens seamlessly from your CasaOS dashboard.

### Method 1: Install from CasaOS Web UI (Recommended)

1. Open your **CasaOS Web UI** in a browser (`http://<server-ip>`).
2. Click the **`+`** icon in the top right of the CasaOS dashboard, then select **"Install a customized app"**.
3. In the top-right corner of the popup modal, click the **Import** button (the `</>` icon).
4. Copy and paste the contents of [`docker-compose.yml`](docker-compose.yml) into the text box and click **Submit**.
5. CasaOS will automatically populate:
   - **App Name**: `SyncToHDD`
   - **Icon & Web UI Link**: Port `6060`
   - **Volumes**:
     - Check that the destination volume matches your mounted USB3 HDD path (e.g. `/media/devmon/LX2T`).
     - Check that the source path matches your server data folder (e.g. `/sg2b`).
6. Click **Install**.
7. Once installed, click the **SyncToHDD** icon on your CasaOS dashboard to open the Web UI!

---

## Quick Start (Standard Local & Docker)

### Prerequisites

- Python 3.11+
- `rsync` (Linux — optional but recommended; the engine falls back to pure Python)

### Local

```bash
# Clone the repo
git clone https://github.com/AlexLX4773H/SyncToHDD.git
cd SyncToHDD

# Create a virtual environment
python -m venv venv
source venv/bin/activate   # Linux/macOS
venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt

# Run
python -m synctohdd.main server --port 6060
```

Open **http://localhost:6060** in your browser.

### Standard Docker / Docker Compose

```bash
# Clone and run
git clone https://github.com/AlexLX4773H/SyncToHDD.git
cd SyncToHDD
docker compose up -d

# View live logs
docker compose logs -f synctohdd
```

---

## Configuration

Edit `config.yaml` (or configure via the Web UI):

```yaml
sync_pairs:
  - id: "manga-cbz-backup"
    name: "Manga CBZ Backup"
    source: "/sg2b/Share2sgb/Manga/Manga_CBZ_1"
    destination: "/media/devmon/LX2T/BackupServer"
    mode: "mirror"          # mirror | additive
    exclude:
      - "*.tmp"
      - ".thumbs/"
      - ".DS_Store"
      - "Thumbs.db"
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

---

## CLI Usage

You can also run sync jobs or check status from the command line:

```bash
# List configured pairs
python -m synctohdd.main list

# Run a dry-run preview from terminal
python -m synctohdd.main sync manga-cbz-backup --dry-run

# Run actual sync from terminal
python -m synctohdd.main sync manga-cbz-backup

# Sync all configured pairs sequentially
python -m synctohdd.main sync all
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 |
| Frontend | Jinja2, HTMX, vanilla CSS/JS |
| Database | SQLite (WAL mode) |
| Sync Engine | rsync (Linux) / shutil (cross-platform fallback) |
| Deployment | Docker, CasaOS (`x-casaos`), docker-compose |

---

## License

MIT
