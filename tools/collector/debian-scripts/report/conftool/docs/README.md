# conftool — Host Configuration Summary Tool

`conftool` extracts and summarizes host configuration from a StarlingX collect
bundle directory. It produces both JSON and human-readable text output designed
for both human and LLM-assisted root-cause analysis.

## Requirements

- Python 3.6+
- No external dependencies (stdlib only)

## Quick Start

```bash
# Summarize controller-0 across all domains
conftool -b /path/to/ALL_NODES_20251216.115202

# Summarize a specific host
conftool -b /path/to/bundle -H controller-1

# Run only the network domain
conftool -b /path/to/bundle --domain network
# Run only the storage domain

conftool -b /path/to/bundle --domain storage

# Run multiple domains
conftool -b /path/to/bundle -d network -d container

# Custom output directory
conftool -b /path/to/bundle -o /tmp/output

# Verbose output (print text summary to stdout)
conftool -b /path/to/bundle --domain network -v

# Extra verbose (show parsed input file details)
conftool -b /path/to/bundle -vv

# Maximum verbosity (debug-level tracing)
conftool -b /path/to/bundle -vvv
```

## Command-Line Options

| Option | Description |
|--------|-------------|
| `-b, --bundle PATH` | **(required)** Path to the collect bundle directory |
| `-H, --hostname NAME` | Hostname to load (default: `controller-0`) |
| `-d, --domain DOMAIN` | Domain(s) to process. May be repeated. Default: all |
| `-o, --output PATH` | Output base directory (default: `<bundle>/config`) |
| `-v, --verbose` | Increase verbosity (`-v`, `-vv`, `-vvv`) |

Available domains: `network`, `container`, `software`, `platform`, `storage`

## Output

For each domain, conftool writes two files into `<output>/<hostname>/`:

| File | Format | Purpose |
|------|--------|---------|
| `<domain>_config.json` | JSON | Machine-readable summary for LLM ingestion |
| `<domain>_config.txt` | Text | Human-readable summary for quick inspection |

Example output tree:
```
<bundle>/config/controller-0/
├── network_config.json
├── network_config.txt
├── container_config.json
├── container_config.txt
├── software_config.json
├── software_config.txt
├── platform_config.json
├── platform_config.txt
├── storage_config.json
└── storage_config.txt
```

## Domains

### Network

Extracts interfaces, bonds, VLANs, IP addresses, routing, listeners,
connection states, `/etc/hosts`, and performs cross-checks against
`platform.conf` role assignments.

Input files:
- `var/extra/networking.info`
- `var/extra/interface.info`
- `var/extra/netstat.info`
- `etc/platform/platform.conf`
- `etc/hosts`

### Container

Extracts Kubernetes cluster state: node health, pod status, helm releases,
container runtime info, CPU manager state, and cluster events.

Input files:
- `var/extra/containerization_kube.info`
- `var/extra/containerization_helm.info`
- `var/extra/containerization_host.info`
- `var/extra/containerization_events.info`
- `etc/default/kubelet`

### Software

Extracts software/patch state: installed releases, deploy status, build
info, and host running versions.

Input files:
- `var/extra/usm.info`
- `var/extra/software/software.json`
- `etc/build.info`
- `etc/platform/platform.conf`

### Platform

Extracts hardware and platform state: system identity (DMI), CPU topology,
memory usage, top processes, PCI devices, kernel/boot parameters, and BMC
sensor readings.

Input files:
- `var/extra/host.info`
- `var/extra/memory.info`
- `var/extra/process.info`
- `var/extra/bmc.info`

### Storage

Extracts storage subsystem state: Ceph cluster health (OSD tree, pools,
PG status, capacity), DRBD replication state, LVM layout (VG/PV/LV),
filesystem usage and inode consumption, physical disk SMART health, and
block device topology.

Input files:
- `var/extra/ceph.info`
- `var/extra/filesystem.info`
- `var/extra/disk.info`
- `var/extra/blockdev.info`
- `var/extra/iscsi.info`

## Verbosity Levels

| Level | Behavior |
|-------|----------|
| (none) | Print output file paths only |
| `-v` | Also print the full text summary to stdout |
| `-vv` | Also show which input files were found/missing and parse stats |
| `-vvv` | Also show host directory discovery debug info and file sizes |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success, all cross-checks passed |
| 1 | One or more cross-checks returned FAIL status |

## Bundle Layout

conftool supports both flat and nested collect bundle layouts:

```
# Flat
<bundle>/<hostname>_<timestamp>/var/extra/...

# Nested
<bundle>/<hostname>_<timestamp>/<hostname>_<timestamp>/var/extra/...
```

When multiple timestamp directories match a hostname, the most recent
(lexicographically last) is selected.

## Fallback Behavior

- If `networking.info` is empty or missing, the network domain falls back
  to parsing `sm.info` for network data (older StarlingX releases).
- If `host.info` is missing, the platform domain falls back to `sm.info`
  for CPU and kernel info via `/proc/cpuinfo` and `uname -a`.

## Testing

conftool includes a built-in test suite (103 tests) covering unit tests
for each domain's parsers and an end-to-end integration test.

### Running Tests

```bash
# Run all tests
./conftool --test

# Run with coverage report
./conftool --test --cov
```

### Test Structure

```
conftool/test/
├── mock_factory.py       # Shared test fixtures — real bundle data (anonymized)
├── test_host_utils.py    # Section parser, host discovery, formatting helpers
├── test_network.py       # ip link/addr/route parsing, full pipeline
├── test_container.py     # kubectl nodes/pods, helm list, full pipeline
├── test_software.py      # software list, deploy status, full pipeline
├── test_platform.py      # dmidecode, lscpu, meminfo, SM services
├── test_storage.py       # ceph, DRBD, df, lsblk, cross-checks
└── test_e2e.py           # Integration: full CLI subprocess against synthetic bundle
```

### Mock Factory

`mock_factory.py` provides:
- **Real data constants** — snippets extracted from production collect bundles
  (anonymized), ensuring parsers are tested against actual formats
- **`create_bundle()`** — builds a complete temporary bundle directory tree
  at runtime, used by both unit and integration tests
- **`make_section()` / `make_info_file()`** — helpers to construct `.info`
  files matching StarlingX's section-delimited format

### Test Approach

| Type | What it validates |
|------|-------------------|
| **Unit** | Individual parser functions produce correct data structures from real-format input |
| **Pipeline** | `load_config()` → `build_summary()` end-to-end for each domain |
| **Integration** | Full CLI invocation via subprocess: exit codes, output file creation, JSON validity, domain filtering, error handling |

No hardcoded paths or external dependencies — tests run anywhere with
Python 3.6+.
