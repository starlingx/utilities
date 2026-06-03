# conftool — Architecture

## Overview

conftool is a pluggable, domain-driven tool that transforms raw StarlingX
collect bundle data into structured summaries. It follows a three-stage
pipeline: **Load → Summarize → Output**.

```
┌─────────────────────────────────────────────────────────────────┐
│                         conftool (CLI)                          │
│  argparse → host discovery → domain dispatch → output writing   │
└────────────────────────────┬────────────────────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Domain 1 │  │ Domain 2 │  │ Domain N │
        │  network │  │ container│  │   ...    │
        └──────────┘  └──────────┘  └──────────┘
              │              │              │
              ▼              ▼              ▼
        load_config    load_config    load_config
              │              │              │
              ▼              ▼              ▼
        build_summary  build_summary  build_summary
              │              │              │
              ▼              ▼              ▼
        write_json     write_json     write_json
        write_text     write_text     write_text
```

## Directory Structure

```
conftool/
├── conftool              # CLI entry point (executable Python script)
├── host_utils.py         # Shared utilities (section parser, formatting, host discovery)
├── domains/
│   ├── __init__.py       # Domain registry and plugin loader
│   ├── network/
│   │   ├── __init__.py   # Domain metadata (NAME, FILE_PREFIX, INPUT_FILES)
│   │   ├── config.py     # load_config() + build_summary()
│   │   └── output.py     # write_json() + write_text()
│   ├── container/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── output.py
│   ├── software/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── output.py
│   ├── platform/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── output.py
│   └── storage/
│       ├── __init__.py
│       ├── config.py
│       └── output.py
├── test/
│   ├── mock_factory.py   # Real bundle data (anonymized) + bundle scaffolding
│   ├── test_host_utils.py
│   ├── test_network.py
│   ├── test_container.py
│   ├── test_software.py
│   ├── test_platform.py
│   ├── test_storage.py
│   └── test_e2e.py       # Integration test (subprocess CLI execution)
└── docs/
    ├── README.md
    └── ARCHITECTURE.md
```

## Core Components

### conftool (CLI Entry Point)

The main script handles:
1. Argument parsing
2. Host directory discovery (via `host_utils.find_host_dir`)
3. Domain resolution (all or user-selected subset)
4. Orchestrating the load → summarize → output pipeline
5. Exit code based on cross-check results

### host_utils.py (Shared Utilities)

Provides functionality shared across all domains:

| Function | Purpose |
|----------|---------|
| `parse_info_sections(text)` | Splits `----`-delimited `.info` files into `{command: output}` dicts |
| `find_host_dir(bundle, hostname)` | Locates the host directory within flat or nested bundle layouts |
| `extract_host_identity(host_dir)` | Extracts hostname and timestamp from directory name |
| `human_bytes(n)` | Formats byte counts into compact strings (e.g. `1.5G`) |
| `set_verbose_level(level)` / `get_verbose_level()` | Global verbosity control |

### domains/__init__.py (Plugin Registry)

Manages domain registration and lazy loading:
- `DOMAIN_NAMES` — ordered list of available domain names
- `get_domain(name)` — imports and wraps a domain module
- `get_all_domains()` — returns all registered domains

Each domain is wrapped into a `Domain` object exposing a uniform interface.

## Domain Plugin Contract

Every domain sub-package must export:

| Export | Type | Description |
|--------|------|-------------|
| `NAME` | `str` | Human-readable domain name |
| `FILE_PREFIX` | `str` | Filename prefix for output files |
| `INPUT_FILES` | `list[(str, str)]` | List of `(label, relative_path)` tuples |
| `load_config(host_dir, config)` | function | Parses raw files into the shared `config` dict |
| `build_summary(config)` | function | Distills raw config into a concise summary dict |
| `write_json(summary, output_path)` | function | Writes JSON output |
| `write_text(summary, lines)` | function | Appends human-readable text to a lines list |

## Data Flow

### Stage 1: Load (`load_config`)

Each domain reads its input files from the host directory and populates
the shared `config` dict with raw parsed data under domain-specific keys.

```python
config = {'hostname': 'controller-0', 'collected': '20251216.115202', 'warnings': []}

# Network domain adds:
#   config['interfaces'], config['routing'], config['services'], ...
# Container domain adds:
#   config['kube_nodes'], config['kube_pods'], config['helm_releases'], ...
# Software domain adds:
#   config['software_releases'], config['build_info'], ...
# Platform domain adds:
#   config['lscpu'], config['meminfo'], config['pci_devices'], ...
# Storage domain adds:
#   config['ceph'], config['drbd'], config['filesystems'], config['smart_disks'], ...
```

The shared config dict allows cross-domain data access (e.g. network domain
reads `platform.conf` which software domain also uses).

### Stage 2: Summarize (`build_summary`)

Each domain distills its raw data into a concise summary dict optimized for:
- LLM consumption (structured, self-describing keys)
- Human readability (pre-formatted values like `"1.5G"`)
- Anomaly highlighting (cross-checks, warnings, problem items)

Every summary includes:
- `cross_check` — list of `{check, status, detail}` validation results
- `warnings` — list of anomaly strings
- `source_files` — list of files that contributed data

### Stage 3: Output (`write_json` / `write_text`)

- `write_json` serializes the summary dict to a formatted JSON file
- `write_text` builds a section-based human-readable report with:
  - Section headers (`====`)
  - Key-value pairs (aligned columns)
  - Status icons (✅ ⚠️ ❌)
  - Hierarchical grouping where appropriate

## .info File Format

StarlingX collect bundles store command outputs in `.info` files using a
section-delimited format:

```
------------------------------------------------------------
Tue 16 Dec 2025 11:58:55 AM KST :  : ip -s link
------------------------------------------------------------
<command output here>
------------------------------------------------------------
Tue 16 Dec 2025 11:58:55 AM KST :  : ip -4 route
------------------------------------------------------------
<command output here>
```

`parse_info_sections()` handles multiple header timestamp formats across
StarlingX releases and returns a `{command_string: output_text}` dict.

## Cross-Check Pattern

Each domain performs validation checks that produce structured results:

```python
{'check': 'management_interface (bond0)', 'status': 'OK', 'detail': 'UP, 2 IPv4 addrs'}
{'check': 'node controller-0',            'status': 'FAIL', 'detail': 'Status: NotReady'}
{'check': 'deploy status',                'status': 'WARN', 'detail': 'Deploy in progress'}
```

Status values: `OK`, `WARN`, `FAIL`, `INFO`

The CLI exits with code 1 if any cross-check returns `FAIL`.

## Adding a New Domain

1. Create `domains/<name>/` with `__init__.py`, `config.py`, `output.py`
2. In `__init__.py`, define `NAME`, `FILE_PREFIX`, `INPUT_FILES` and
   re-export `load_config`, `build_summary`, `write_json`, `write_text`
3. Add the domain name to `DOMAIN_NAMES` in `domains/__init__.py`
4. Add an import branch in `get_domain()` in `domains/__init__.py`

## Design Decisions

- **No external dependencies** — runs on any Python 3.6+ without pip install
- **No `__pycache__`** — `sys.dont_write_bytecode = True` everywhere to
  avoid polluting the source tree
- **Lazy imports** — domains are imported on demand to keep startup fast
- **Shared config dict** — allows domains to access data loaded by other
  domains (e.g. `platform.conf` is used by both network and software)
- **Fallback parsers** — older StarlingX releases store data in different
  files (`sm.info`); domains gracefully fall back when primary files are empty
- **Verbosity-aware output** — text and JSON writers respect the global
  verbose level to control detail (e.g. hiding DOWN interfaces with no role)


## Testing Architecture

### Invocation

Tests are invoked via the CLI entry point itself:

```bash
./conftool --test          # unittest discover, verbosity=2
./conftool --test --cov    # + coverage.py report with per-line miss info
```

The `--test` flag is intercepted before `argparse` runs (same pattern as
the parent report tool), so `--bundle` is not required.

### Test Layers

```
┌──────────────────────────────────────────────────────────────┐
│                    Integration (test_e2e.py)                  │
│  Runs ./conftool as subprocess against synthetic bundle       │
│  Validates: exit codes, file creation, JSON validity,         │
│             domain flags, error paths, nested bundles         │
└──────────────────────────────────────────┬───────────────────┘
                                           │
┌──────────────────────────────────────────┼───────────────────┐
│              Pipeline Tests (per domain)                      │
│  load_config(host_dir, config) → build_summary(config)       │
│  Validates: end-to-end data flow, cross-checks, summaries    │
└──────────────────────────────────────────┬───────────────────┘
                                           │
┌──────────────────────────────────────────┼───────────────────┐
│              Unit Tests (per parser function)                 │
│  parse_ip_link(), _parse_ceph_status(), etc.                 │
│  Validates: individual parsers against known input/output     │
└──────────────────────────────────────────────────────────────┘
```

### Mock Factory (`test/mock_factory.py`)

The mock factory provides test data derived from real production collect
bundles (anonymized). This ensures parsers are tested against actual
formatting — column alignment, tab separators, indentation, header rows —
rather than invented approximations.

Key components:

| Component | Purpose |
|-----------|---------|
| `make_section(cmd, output)` | Wraps output in `.info` section format (68-dash separators + timestamp header) |
| `make_info_file(*sections)` | Concatenates sections into a complete `.info` file |
| `create_bundle(base_dir)` | Builds a full bundle directory tree in a temp directory |
| `NETWORK_IP_LINK`, etc. | Constants with real parser input data |

### Design Principles

- **No external dependencies** — uses `unittest` from stdlib only
  (`coverage` optional for `--cov`)
- **No hardcoded paths** — all test bundles created in `tempfile.mkdtemp()`
- **Self-contained** — runs anywhere with Python 3.6+, no network, no
  real bundles required
- **Real data formats** — mock constants extracted from production bundles
  to catch format-related regressions
- **Cleanup** — `tearDown()` removes all temp directories

### Coverage

When invoked with `--cov`, coverage is reported for all production modules:
- `host_utils`
- `domains/__init__`
- `domains/{network,container,software,platform,storage}/{config,output}`

### Adding Tests for a New Domain

1. Add mock data constants to `mock_factory.py` (extract from a real bundle)
2. Add the mock data to `create_bundle()` file writes
3. Create `test/test_<domain>.py` with:
   - Parser-level unit tests (import individual `_parse_*` functions)
   - Pipeline test class using `create_bundle()` + `load_config` → `build_summary`
4. Run `./conftool --test` to verify
