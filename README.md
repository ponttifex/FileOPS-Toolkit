>🔧 *FileOps Toolkit* — Unified, parallel, and intelligent file deduplication &amp; transfer system.

# 🧩 FileOps Toolkit
**Advanced Deduplication & File Transfer Framework**

> A modular, parallel, and robust system for discovering, deduplicating, transferring, and verifying files across multiple disks or servers — with interactive configuration, rsync integration, and real-time logging.

---

## 🚀 Overview

**FileOps Toolkit** is an all-in-one solution for managing large-scale file operations such as:

- 🔍 File discovery across multiple sources
- 🧠 Intelligent deduplication (size / date / hash based)
- ⚙️ Parallel high-performance transfers (rsync, SCP, or rclone)
- 🧾 Real-time colored output and detailed CSV/JSON logs
- 🧰 Interactive menu for configuration and monitoring
- 🔁 Resume, retry, and verify mechanisms for reliability

Whether you’re merging ISO archives, syncing multiple disks, or cleaning redundant backups —
FileOps Toolkit gives you **complete control and transparency** over your data operations.

---

## ✨ Features

- 🌐 **Multi-source discovery** (`find`, `fdfind`, or recursive scan)
- 💾 **Deduplication logic** based on size → mtime → hash
- 🧮 **Checksum algorithms**: `xxh128`, `blake3`, `md5`, `sha1`
- ⚡ **Parallel processing** via `xargs`, `GNU parallel`, or Python `ThreadPool`
- 🔒 **Reliable transfers** using `rsync` or SSH
- 📊 **Comprehensive logging**: CSV, JSON, and human-readable formats
- 🧱 **Interactive config menu (TUI)** for full control
- 🧯 **Pre-checks** for disk space, permissions, and required tools
- 🧠 **Retry & recovery** for failed operations
- 💬 **Rich colored console output** (progress bars, ETA, stats)

---

## 🧰 Example Use Cases

| Scenario | Description |
|-----------|--------------|
| 🖥️ **ISO Collector** | Automatically gather and deduplicate `.iso` images from multiple drives |
| 🎥 **Media Sync** | Consolidate large video libraries with duplication protection |
| 🗄️ **Archive Merge** | Compare and unify backup archives across servers |
| 🌐 **Remote Sync** | Rsync-based file mirroring over SSH |
| 📁 **Data Cleaning** | Detect and remove redundant files by hash |

---

## ⚙️ Configuration Example (`config.yml`)

```yaml
sources:
  - /mnt/f
  - /mnt/d
destination: /mnt/e/Collected
parallel_workers: 12
checksum_algo: xxh128
deduplication_policy: prefer_newer
transfer_tool: rsync
rsync_args:
  - "-aHAX"
  - "--sparse"
  - "--preallocate"
  - "--info=progress2,stats4"
logging:
  dir: /var/log/fileops
  csv_file: operations.csv
dry_run: false
```
---
@pierringshot
@Azerbaijan-Cybersecurity-Center
@PierringShot-Electronics