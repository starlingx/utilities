# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# All mutable globals for network_platform_audit.
# Every module imports this module and accesses globals as state.VARIABLE.
# Mutable scalars are rebound via state.VARIABLE = ... (not from-import).

from collections import defaultdict

# ---------------------------------------------------------------------------
# Logging / report
# ---------------------------------------------------------------------------
REPORT_FILE = "/var/log/network_diag.log"
LOG_WIDTH = 90
PAUSE_ENABLED = False
VERBOSE = False
LOG_BUFFER = []
REPORT_FD = None

# Per-category result tracking
category_failures = defaultdict(list)
category_warnings = defaultdict(list)
current_category = None
executed_categories = []

# ---------------------------------------------------------------------------
# System / platform state (populated by startup_checks)
# ---------------------------------------------------------------------------
SYSTEM_MODE = "duplex"
DC_ROLE = "none"
HOST_LIST = []
IS_SIMPLEX = False

# ---------------------------------------------------------------------------
# SSH session state
# ---------------------------------------------------------------------------
SSH_USER = "sysadmin"
SSH_PASSWORD = None
SSH_FAILED_HOSTS = set()

# Private 0700 directory under /run that holds ControlMaster sockets.
# Created lazily on first open_ssh_session() call; removed in close_all_sessions().
SSH_SOCKET_DIR = None

# Persistent SSH ControlMaster connections: hostname -> socket path
ssh_sessions = {}

# True when --ssh-pass is not provided and there are remote hosts
REMOTE_KERNEL_SKIPPED = False

# Hosts skipped only because --ssh-pass was not provided (no connection failure)
SSH_NO_PASS_HOSTS = set()

# ---------------------------------------------------------------------------
# Timeouts (seconds) — overridable via --cmd-timeout / --tcpdump-timeout
# ---------------------------------------------------------------------------
CMD_TIMEOUT = 30
TCPDUMP_TIMEOUT = 20

# ---------------------------------------------------------------------------
# Subcloud filtering (set from args)
# ---------------------------------------------------------------------------
SUBCLOUD_NAME = None
SUBCLOUD_RANGE_START = None
SUBCLOUD_RANGE_END = None
SUBCLOUD_OAM_IP = None

# ---------------------------------------------------------------------------
# Platform capabilities (populated by startup_checks)
# ---------------------------------------------------------------------------
# True when 'system show' reports https_enabled = True
HTTPS_ENABLED = False

# The HTTP/HTTPS service port from service-parameter (service=http,
# section=config, name=https_port or http_port).  None = not customised or
# not yet resolved.  Cached here so it is read only once per run.
HTTP_SERVICE_PORT = None

# ---------------------------------------------------------------------------
# Cross-test shared state
# ---------------------------------------------------------------------------
# Populated by test_addrpools(); consumed by test_heartbeat_extended().
# Empty list means the subnet-membership check is skipped (standalone run).
_multicast_subnets = []
