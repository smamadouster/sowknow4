# SOWKNOW Phase 2 - User Guide

**Last Updated:** February 10, 2026
**Version:** 2.0.0

---

## Table of Contents

1. [Smart Collections](#smart-collections)
2. [Smart Folders](#smart-folders)
3. [Reports](#reports)
4. [Auto-Tagging](#auto-tagging)
5. [Mac Sync Agent](#mac-sync-agent)

---

## Smart Collections

Smart Collections allow you to group documents using natural language queries. The AI analyzes your query and automatically gathers relevant documents.

### Creating a Collection

1. Navigate to **Collections** in the sidebar
2. Click **+ New Collection**
3. Describe what you want to find in natural language:
   - "Show me all financial documents from 2023"
   - "Photos from my vacation in France"
   - "All contracts with Company XYZ"
4. Click **Create Collection**

### Collection Features

- **AI Summary**: Automatically generated summary of the collection
- **Document Relevance**: Documents ranked by relevance score
- **Follow-up Q&A**: Chat with your collection using context-aware AI
- **Pin & Favorite**: Pin important collections to the top

### Collection Chat

Each collection has its own chat interface scoped to its documents:

1. Open a collection
2. Type your question in the chat sidebar
3. Get answers with source citations from collection documents

**Benefits:**
- Faster, more relevant answers
- Context caching reduces costs on repeated queries
- Sources are always from your collection

---

## Smart Folders

Smart Folders generate AI-written content from your documents. Perfect for creating summaries, reports, or articles.

### Creating a Smart Folder

1. Navigate to **Smart Folders** in the sidebar
2. Enter your topic (e.g., "Annual performance summary")
3. Choose writing style:
   - **Informative**: Educational and clear
   - **Professional**: Formal business tone
   - **Creative**: Engaging and vivid
   - **Casual**: Friendly and relaxed
4. Choose length: Short (~300 words), Medium (~800 words), Long (~2000 words)
5. Click **Generate Smart Folder**

### Use Cases

- **Executive Summaries**: Quick overviews of document sets
- **Knowledge Synthesis**: Combine insights from multiple sources
- **Report Drafting**: Generate first drafts for review
- **Topic Exploration**: Learn about a subject from your documents

---

## Reports

Generate professional PDF reports from your collections in three formats.

### Report Formats

| Format | Length | Best For |
|--------|--------|----------|
| **Short** | 1-2 pages | Quick summaries, executive overviews |
| **Standard** | 3-5 pages | Balanced reports with analysis |
| **Comprehensive** | 6-10 pages | In-depth analysis with appendices |

### Generating a Report

1. Open the collection you want to report on
2. Click **Generate Report**
3. Choose format and language
4. Toggle **Include Citations** for document references
5. Click **Generate**

### Report Sections

- Executive Summary
- Introduction
- Analysis/Findings
- Recommendations
- References (with citations)

---

## Auto-Tagging

Documents are automatically tagged when uploaded, making them easier to find.

### Auto-Generated Tags

- **Topics**: Main themes (e.g., "finance", "legal", "medical")
- **Entities**: Names, organizations, locations
- **Importance**: Critical, high, medium, low
- **Language**: English, French, multilingual

### Managing Tags

- View tags in the document details panel
- Add manual tags for custom organization
- Search by tag to find related documents

---

## Mac Sync Agent

The SOWKNOW Sync Agent keeps your documents synchronized from local folders to SOWKNOW.

### Installation

```bash
cd sync-agent
pip install -r requirements.txt
```

### Setup

1. Run the setup wizard:
   ```bash
   python sowknow_sync.py --setup
   ```

2. Enter your API URL and token (from SOWKNOW Settings)

3. Add folders to sync (Desktop, Downloads, iCloud Drive, etc.)

### Running the Agent

**Watch mode** (continuous syncing):
```bash
python sowknow_sync.py --watch
```

**One-time sync**:
```bash
python sowknow_sync.py --sync
```

### Features

- **Deduplication**: Skips files already uploaded
- **Selective Sync**: Choose specific folders
- **Auto-Tagging**: Tags files on upload
- **Visibility Control**: Set public/confidential per folder

### Typical Folder Paths

- iCloud Drive: `~/Library/Mobile Documents/com~apple~CloudDocs/Documents/`
- Downloads: `~/Downloads/`
- Dropbox: `~/Dropbox/`

---

## Tips & Best Practices

### Collections

- **Be Specific**: More specific queries yield better results
- **Use Dates**: Include time ranges like "from 2023" or "last 6 months"
- **Name Clearly**: Give your collections descriptive names

### Smart Folders

- **Start Broad**: Begin with general topics, then refine
- **Experiment with Styles**: Different styles for different purposes
- **Review Sources**: Always check which documents were used

### Reports

- **Short Format**: For quick updates and summaries
- **Standard Format**: For most business needs
- **Comprehensive**: For detailed analysis and documentation

### Sync Agent

- **Test First**: Run `--sync` once to verify setup
- **Check Logs**: View `~/.sowknow/sync_agent.log` for issues
- **Start Small**: Begin with one folder, add more gradually

---

## Troubleshooting

### Collection returns no documents

- Try rephrasing your query
- Check if documents exist (visit Documents page)
- Verify document visibility settings

### Smart Folder generation is slow

- Larger document sets take longer
- Consider using Medium length for faster generation
- Check system status page for API issues

### Sync Agent not uploading

- Verify API token is valid
- Check file permissions
- Review sync agent logs: `~/.sowknow/sync_agent.log`

---

## Privacy & Security

- **Confidential Routing**: Documents marked confidential only use local LLM (Ollama)
- **No PII to Cloud**: Private data never leaves your infrastructure
- **Audit Logging**: All confidential access is logged

---

## Support

For issues or questions:
1. Check the system status page
2. Review error logs
3. Contact your administrator

**Version:** 2.0.0 | **Phase:** 2 - Intelligence Layer
