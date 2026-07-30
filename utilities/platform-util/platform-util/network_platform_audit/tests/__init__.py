# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0
#
# ---------------------------------------------------------------------------
# Suite catalogue
# ---------------------------------------------------------------------------
#
# ts01_availability  - Host Availability
#   Purpose:  Detect hosts that are degraded, failed, or offline so that
#             operator attention is directed before network checks begin.
#   Data:     system host-list
#   Check:    availability and operational fields per host
#   FAILED:   availability != available or operational != enabled
#
# ts02_interfaces    - Interfaces vs Kernel
#   Purpose:  Confirm that the sysinv interface model (type, MTU, VLAN ID,
#             bond membership) matches the live kernel state on every host,
#             catching configuration drift between the DB and the dataplane.
#   Data:     system host-if-list (per host, local and remote via SSH)
#   Check:    DB interface type / MTU / VLAN-ID / bond members vs kernel:
#               - ip link show (UP flag, state, MTU)
#               - /proc/net/bonding/<ifname> (bond mode, slave list)
#               - /proc/net/vlan/<ifname>   (VLAN ID)
#   FAILED:   DB says ethernet but kernel shows a bond or VLAN device;
#             DB says ae (bond) but /proc/net/bonding entry missing;
#             DB bond mode does not match kernel Bonding Mode string;
#             DB uses_list member not listed as Slave Interface in kernel;
#             DB says vlan but /proc/net/vlan/<ifname> missing or VID mismatch
#
# ts03_sriov         - SR-IOV
#   Purpose:  Verify that SR-IOV virtual functions are instantiated in the
#             kernel with the correct count, MAC addresses, and driver bindings
#             as specified in the sysinv DB.
#   Data:     system host-if-list, system host-if-show (per VF interface)
#   Check:    sysinv numvfs vs kernel sriov_numvfs; VF MAC addresses;
#             kernel driver vs ethtool -i; firmware version via ethtool -i
#   FAILED:   sriov_numvfs mismatch; VF MAC not found in ip link output;
#             kernel driver does not match sriov_vf_driver setting
#
# ts04_addresses     - Addresses vs Kernel
#   Purpose:  Ensure every IP address provisioned in sysinv is actually
#             assigned to the correct kernel interface on each host,
#             detecting address assignment failures or manual overrides.
#   Data:     system host-addr-list (per host)
#   Check:    each DB IPv4/IPv6 address present in ip addr show on the
#             correct kernel interface
#   FAILED:   address not found in kernel ip addr show output
#
# ts05_routes        - Static Routes vs Kernel
#   Purpose:  Validate that all static routes defined in sysinv are
#             programmed in the kernel routing table, and flag unexpected
#             kernel routes that are not tracked in the DB.
#   Data:     system host-route-list (per host)
#   Check:    each DB static route present in kernel routing table
#             (ip route show / ip -6 route show);
#             IPv6 routes validated for src address family on new SW versions
#   FAILED:   DB route not found in kernel routing table
#   WARN:     kernel route not present in DB (unexpected kernel route)
#
# ts06_ports         - Port / PCI Information
#   Purpose:  Confirm that the physical NICs registered in sysinv are present
#             in the system PCI bus and are bound to the expected kernel driver.
#   Data:     system host-port-list (per host)
#   Check:    PCI address present in lspci output;
#             kernel driver matches ethtool -i driver field
#   FAILED:   PCI address not in lspci; driver mismatch
#
# ts07_lldp          - LLDP Neighbors
#   Purpose:  Cross-check the LLDP neighbor table in sysinv against live
#             lldpctl output to detect stale DB entries or undiscovered
#             physical adjacencies.
#   Data:     system host-lldp-neighbor-list (per host)
#   Check:    DB neighbor (chassis-id, port-id) found in live lldpctl output
#   WARN:     DB neighbor not seen in live lldpctl; live neighbor not in DB
#
# ts08_addrpools     - Networks and Address Pools
#   Purpose:  Verify platform network reachability and pool consistency:
#             every network has a pool, floating addresses and gateways are
#             reachable, and pool ranges do not overlap.
#   Data:     system network-list, addrpool-list, network-addrpool-list
#   Check:    every network has at least one pool;
#             floating address of each pool is reachable (ping);
#             pool gateway is reachable (ping);
#             no two pool ranges overlap (CIDR containment check);
#             floating addresses reachable from all remote hosts (SSH + ping)
#   FAILED:   network has no pool; pool floating address unreachable
#   WARN:     gateway unreachable; pool ranges overlap
#
# ts09_dns           - DNS
#   Purpose:  Confirm that the platform DNS configuration is consistent and
#             that nameservers are reachable and resolving platform hostnames
#             correctly, on every host in the system.
#   Data:     system dns-show, /etc/resolv.conf, getent hosts (per host,
#             local + remote via SSH)
#   Check:    nameservers from sysinv match /etc/resolv.conf;
#             each nameserver: ICMP ping, TCP port 53, UDP port 53 - reachable
#             requires ping success AND (TCP-53 or UDP-53) success;
#             forward resolution of controller-0 and controller on every host
#   FAILED:   all configured nameservers unreachable; hostname does not
#             resolve on a host
#   WARN:     sysinv and resolv.conf nameserver lists differ;
#             some (not all) nameservers unreachable (partial availability)
#
# ts10_dhcp          - DHCP (dnsmasq)
#   Purpose:  Verify that the dnsmasq DHCP/TFTP service is running and
#             serving the expected hosts, ensuring PXE boot infrastructure
#             is functional.
#   Data:     ss -ulnp / ss -tlnp, dnsmasq.leases, dnsmasq.addn_hosts,
#             dnsmasq.addn_conf, /etc/hosts
#   Check:    dnsmasq UDP/TCP listening sockets present;
#             TFTP port 69 in LISTEN;
#             dnsmasq.leases file exists;
#             dnsmasq host-record IPs reachable (ping);
#             /etc/hosts name resolution on all hosts (local + remote via SSH),
#             ping skipped for loopback entries (127.0.0.1, ::1)
#   FAILED:   dnsmasq not listening; TFTP port not in LISTEN;
#             host-record IP unreachable; /etc/hosts entry does not resolve
#
# ts11_heartbeat     - Heartbeat (hbsAgent / hbsClient)
#   Purpose:  Confirm that the heartbeat service is running and
#             exchanging multicast traffic on the correct management and
#             cluster-host interfaces between controller peers.
#   Data:     ss -ulnp, /etc/hosts, address-pool multicast subnet
#   Check:    hbsAgent and hbsClient UDP sockets present;
#             agent bound to an interface in the management multicast subnet;
#             tcpdump capture confirms heartbeat traffic on mgmt and
#             cluster-host interfaces (duplex only)
#   FAILED:   hbsAgent or hbsClient socket not found
#   WARN:     agent bound to interface outside the expected multicast subnet
#
# ts12_ipsec         - IPsec (swanctl)
#   Purpose:  Verify that IPsec Security Associations between controllers
#             are established and that the pxeboot service port is reachable,
#             ensuring secure inter-controller communication.
#   Data:     swanctl --list-sas, ss -tlnp, dnsmasq pxeboot config
#   Check:    pxeboot TCP port 64764 in LISTEN on controllers;
#             swanctl SAs in ESTABLISHED state
#   FAILED:   port 64764 not in LISTEN; SA not ESTABLISHED
#
# ts13_k8s           - Kubernetes Nodes, Pods, Endpoints
#   Purpose:  Ensure the Kubernetes cluster is healthy: all nodes ready,
#             critical networking pods running, and core service endpoints
#             populated.
#   Data:     kubectl get nodes, kubectl get pods -A, kubectl get endpoints -A
#   Check:    all nodes in Ready state;
#             critical pods Running: calico-node, kube-proxy, coredns, multus;
#             critical service endpoints not <none>: kubernetes, coredns, kube-dns;
#             PodCIDR / ServiceCIDR overlap detection (when CIDR data available)
#   FAILED:   node NotReady; critical pod not Running; critical endpoint is <none>
#
# ts14_coredns       - CoreDNS In-Cluster Resolution
#   Purpose:  Validate end-to-end in-cluster DNS resolution by entering the
#             CoreDNS network namespace and resolving both cluster-internal
#             and platform hostnames.
#   Data:     crictl pods, crictl inspectp (pod PID), nsenter -n
#   Check:    kubernetes.default.svc.cluster.local resolves inside CoreDNS NS;
#             controller-0 resolves via CoreDNS (forwarded to dnsmasq)
#   FAILED:   CoreDNS pod PID not found; in-cluster resolution fails
#
# ts15_cluster_nat   - Kubernetes Cluster Networking / DNAT
#   Purpose:  Confirm that Kubernetes ClusterIP DNAT rules are programmed in
#             nftables and that TCP connectivity to the cluster API server
#             works from within the pod network namespace.
#   Data:     kubectl get svc kubernetes, nft list ruleset, nc (via nsenter)
#   Check:    ClusterIP appears in nftables DNAT rules;
#             TCP connectivity to ClusterIP:443 from CoreDNS namespace;
#             TCP connectivity to each CoreDNS endpoint IP:port directly
#   FAILED:   ClusterIP absent from nftables; TCP connection refused/timed out
#
# ts16_gnp           - Firewall / GlobalNetworkPolicy
#   Purpose:  Verify that Calico GlobalNetworkPolicies allow the correct
#             platform subnets and destination ports, and that the resulting
#             iptables/nftables chains are present on every target host.
#   Data:     kubectl get globalnetworkpolicies -o json,
#             kubectl get globalnetworksets -o json,
#             iptables-save / nft list ruleset (per host via SSH)
#   Check:    each sysinv pool subnet appears in matching GNP ingress nets
#             (literal CIDR or via GlobalNetworkSet / ipset reference);
#             GNP chain is present in iptables/nftables on each target host;
#             GNP destination ports (ports_allow) appear in the translated
#             iptables/nftables chain (literal dport match or covered by a
#             broader port range);
#             systemcontroller subnets included in GNP rules (DC only)
#   FAILED:   pool subnet absent from GNP; GNP chain missing on host
#   WARN:     GNP subnet or port present in the GNP but not found in the
#             translated iptables/nftables chain; orphan GNP subnet with no
#             matching sysinv pool
#
# ts17_openstack     - OpenStack / Keystone Endpoints
#   Purpose:  Confirm that sysinv-related OpenStack service endpoints are
#             listening on the expected ports and are TCP-accessible from the
#             active controller.
#   Data:     openstack endpoint list, ss -tlnp
#   Check:    each unique port from sysinv endpoint URLs in LISTEN;
#             TCP connection to publicURL and internalURL succeeds
#   FAILED:   endpoint port not in LISTEN; TCP connection refused
#
# ts18_mtu           - MTU Functional (end-to-end path MTU)
#   Purpose:  Detect MTU mismatches or path fragmentation issues by sending
#             full-size ICMP probes (DF bit set) sized to each interface MTU
#             across all platform networks between the local controller and
#             every remote host; additionally probes jumbo (9000) capability
#             on networks configured below that size.
#   Data:     system host-if-list, system host-addr-list
#   Check:    for each platform network, send a full-size ICMP probe
#             (payload = interface MTU - IP/ICMP overhead, DF bit set)
#             from the local controller to every remote host IP on that subnet;
#             tests both IPv4 (ping -M do -s) and IPv6 (ping6 -M do -s);
#             on networks below jumbo (9000), also probes a fixed 9000-byte
#             payload with fragmentation allowed (informational)
#   FAILED:   ping returns fragmentation-needed or unreachable at the
#             configured MTU; path cannot carry MTU-sized frames end-to-end
#   WARN:     jumbo (9000) probe fails even with fragmentation allowed
#
# ts19_dc_systemcontroller - Distributed Cloud: System Controller
#   Purpose:  From the system controller, validate each managed subcloud:
#             reachability, DNS, firewall rules, critical service ports, and
#             optionally k8s node health via SSH.
#   Data:     dcmanager subcloud list, dcmanager subcloud show,
#             SSH to subcloud via --subcloud-oam-ip (optional)
#   Check:    per subcloud: availability != offline;
#             management gateway reachable (ping);
#             subcloud DNS resolves platform hostnames;
#             GNP contains systemcontroller subnet in ingress rules;
#             firewall TCP/UDP ports accessible on the subcloud: mgmt-network
#             ports (platform_firewall.SUBCLOUD + http service port) against
#             the mgmt IP, oam-network ports (OAM_COMMON) against
#             --subcloud-oam-ip when provided (falls back to GNP-derived
#             ports when sysinv is unavailable); ports known not to apply are
#             excluded (Docker registry/token, fixed HTTPS 8443, Ceph RGW
#             unless confirmed via SSH, SM heartbeat);
#             (if --subcloud-oam-ip) host availability + k8s node Ready state
#   FAILED:   subcloud offline; gateway unreachable; GNP missing SC subnet;
#             TCP/UDP port timeout; k8s node NotReady
#   WARN:     TCP port refused (service not running); UDP result inconclusive;
#             OAM firewall check skipped when --subcloud-oam-ip not provided
#
# ts20_dc_subcloud   - Distributed Cloud: Subcloud
#   Purpose:  From the subcloud, verify the connectivity path back to the
#             system controller: routing, reachability, IPsec SA state,
#             DNS resolution, and firewall port reachability.
#   Data:     system show (central_cloud_url), ip route show, ping,
#             swanctl --list-sas, dig,
#             sysinv.common.platform_firewall.SYSTEMCONTROLLER/OAM_COMMON/OAM_DC
#   Check:    route to system controller management IP exists in kernel;
#             system controller management IP reachable (ping + TCP 22/443);
#             IPsec SA towards system controller in ESTABLISHED state;
#             DNS resolves controller-0 on the subcloud;
#             SC OAM floating IP reachable via TCP 8443 (if available);
#             firewall TCP/UDP ports accessible on the SC: mgmt-network ports
#             (SYSTEMCONTROLLER + http service port) against the SC mgmt IP,
#             oam-network ports (OAM_COMMON + OAM_DC) against the SC OAM
#             floating IP; SM heartbeat ports excluded (controller-to-
#             controller only, never reachable from a subcloud)
#   FAILED:   route missing; SC IP unreachable; IPsec SA not ESTABLISHED;
#             DNS resolution fails; SC TCP/UDP port timeout
#   WARN:     SC TCP port refused or UDP result inconclusive (service not
#             applied, e.g. Analytics NodePorts)
#
# ---------------------------------------------------------------------------
# Result verdicts
# ---------------------------------------------------------------------------
#
# PASS   - the measured value matches the expected value or the service is
#           reachable and healthy.
# FAILED - a definite mismatch or unreachable service.  Recorded in
#           state.category_failures[cat]; the suite is marked FAILED in the
#           final summary.
# WARN   - a non-critical deviation that warrants investigation but does not
#           cause an outright failure verdict.  Recorded in
#           state.category_warnings[cat].
# SKIP   - a prerequisite was unavailable (no SSH password, required tool not
#           installed, host unreachable, simplex/DC topology mismatch).  The
#           check is bypassed without a FAILED verdict.
#
# ---------------------------------------------------------------------------
# On-system deployment note
# ---------------------------------------------------------------------------
#
# The on-system script is a single bundled file produced by:
#
#   python3 tools/bundle_network_platform_audit.py -o network_platform_audit
#
# The bundler concatenates modules in dependency order (state -> log -> run ->
# ssh -> sysinv -> kube -> ts01 ... ts20 -> __main__) and strips all internal
# imports.  It also embeds the network_diagnostics script (from
# scripts/network_diagnostics) as a self-contained fallback function, followed
# by dispatcher.py which selects the appropriate tool at runtime.
#
# Runtime behaviour of the bundle
# --------------------------------
# When executed, dispatcher.dispatch() runs first and checks four conditions:
#   1. /etc/platform/openrc exists on the local host.
#   2. The hostname matches controller-0 or controller-1.
#   3. Sourcing openrc and running `system show` succeeds (platform services up).
#   4. sm-query reports controller-services as active.
#
# If all conditions pass  -> full network_platform_audit (all ts01-ts20 suites).
# Otherwise               -> node-local network_diagnostics (no DB/CLI required).
#
# The fallback path is suitable for workers, storage nodes, standby controllers,
# and any node where platform services are unavailable.  Arguments exclusive to
# network_platform_audit (--verbose, --ssh-pass, --subcloud*) are silently
# ignored when the fallback path is taken.
#
# This file (tests/__init__.py) is intentionally excluded from the bundling
# process: it contains only documentation and is not referenced by any module
# at runtime.
