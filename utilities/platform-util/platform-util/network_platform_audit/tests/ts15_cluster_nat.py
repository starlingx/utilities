# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import json

from network_platform_audit import state
from network_platform_audit.kube import _get_coredns_pid
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_checked
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available


def test_cluster_nat():
    cat = "TestSuite 15 - Kubernetes Cluster Networking"
    desc = [
        "1) Cluster-Service: get kubernetes ClusterIP (kubectl get svc kubernetes)",
        "2) Cluster-Pod: CoreDNS pod - ClusterIP:443 (nc via nsenter)",
        "3) Cluster-Host: CoreDNS pod - each endpoint IP:port directly (nc via nsenter)",
    ]
    print_category(cat, description=desc)

    if not tool_available("crictl") or not tool_available("nsenter"):
        log("[FAIL] crictl/nsenter not available - required for cluster networking checks")
        state.category_failures[cat].append("crictl or nsenter not installed")
        return

    rc, clusterip_out, _ = run_log_only(
        "kubectl get svc kubernetes -n default -o jsonpath='{.spec.clusterIP}'"
    )
    if rc != 0 or not clusterip_out:
        log_result("ClusterIP exists", "FAILED")
        state.category_failures[cat].append("failed to get kubernetes service ClusterIP")
        return

    k8s_clusterip = clusterip_out.strip().strip("'")
    log(f"[INFO] kubernetes ClusterIP: {k8s_clusterip}")

    pid = _get_coredns_pid()
    if not pid:
        log("[SKIP] coredns PID not found")
        return

    flag = "-6" if ":" in k8s_clusterip else ""
    rc, _, _ = run_checked(
        f"nsenter -n -t {pid} -- nc -vz -w 5 {flag} {k8s_clusterip} 443"
    )
    if rc == 0:
        log_result(f"CoreDNS pod -> ClusterIP {k8s_clusterip}:443", "PASS")
    else:
        log_result(f"CoreDNS pod -> ClusterIP {k8s_clusterip}:443", "FAILED")
        state.category_failures[cat].append(
            f"CoreDNS pod -> ClusterIP {k8s_clusterip}:443 failed"
        )

    rc_ep, ep_json, _ = run_log_only(
        "kubectl get endpoints kubernetes -n default -o json"
    )
    endpoints = []
    try:
        ep_data = json.loads(ep_json) if rc_ep == 0 and ep_json else {}
        for subset in ep_data.get("subsets", []):
            ports = subset.get("ports", [])
            svc_port = next(
                (p.get("port") for p in ports if p.get("name") == "https"),
                ports[0].get("port") if ports else 443
            )
            for addr in subset.get("addresses", []):
                ip = addr.get("ip", "")
                if ip:
                    endpoints.append((ip, svc_port))
    except Exception:
        pass

    if not endpoints:
        log("[SKIP] no endpoints found for kubernetes service")
        return

    for ep_ip, ep_port in endpoints:
        ep_flag = "-6" if ":" in ep_ip else ""
        rc, _, _ = run_checked(
            f"nsenter -n -t {pid} -- nc -vz -w 5 {ep_flag} {ep_ip} {ep_port}"
        )
        if rc == 0:
            log_result(f"CoreDNS pod -> Endpoint {ep_ip}:{ep_port}", "PASS")
        else:
            log_result(f"CoreDNS pod -> Endpoint {ep_ip}:{ep_port}", "FAILED")
            state.category_failures[cat].append(
                f"CoreDNS pod -> Endpoint {ep_ip}:{ep_port} failed"
            )
