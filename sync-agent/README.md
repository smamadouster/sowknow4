# SOWKNOW Sync Agent

A lightweight Python agent for syncing files from local directories, iCloud Drive, and Dropbox folders to SOWKNOW.

## Features

- **Watch folders** for new/modified files
- **Hash-based deduplication** to avoid re-uploading
- **Selective folder sync** with visibility control
- **Automatic retry** on network failure
- **Progress reporting** via logs
- **Secure token storage** using system keyring

## Installation

```bash
cd sync-agent
pip install -r requirements.txt
```

## Setup

Run the interactive setup:

```bash
python sowknow_sync.py --setup
```

You'll need:
1. SOWKNOW API URL (default: http://localhost:8000)
2. API Token (from SOWKNOW user settings)
3. Folder paths to sync

## Usage

### One-time sync
```bash
python sowknow_sync.py --sync
```

### Watch mode (continuous)
```bash
python sowknow_sync.py --watch
```

### Typical macOS paths

**iCloud Drive:**
```
~/Library/Mobile Documents/com~apple~CloudDocs/Documents/
```

**Downloads:**
```
~/Downloads/
```

**Desktop:**
```
~/Desktop/
```

**Dropbox:**
```
~/Dropbox/
```

## Configuration

Configuration is stored in:
- `~/.sowknow/sync_config.json` - Folders and settings
- `~/.sownow/sync_state.json` - Upload tracking (deduplication)
- `~/.sownow/sync_agent.log` - Activity logs

## Supported File Types

- Documents: `.pdf`, `.docx`, `.doc`, `.txt`, `.md`, `.json`
- Images: `.jpg`, `.jpeg`, `.png`, `.gif`
- Spreadsheets: `.xlsx`, `.xls`
- Presentations: `.pptx`

## Troubleshooting

**Permission denied:**
- Ensure folder paths are accessible
- Check API token has upload permissions

**Files not uploading:**
- Check `~/.sownow/sync_agent.log` for errors
- Verify API connection: `curl http://localhost:8000/health`

**Keyring errors:**
- Some systems may not support keyring
- Token will be stored in config file as fallback
