# Copyright (c) 2026 Wind River Systems, Inc.
# SPDX-License-Identifier: Apache-2.0

import ipaddress
import re

from network_platform_audit import state
from network_platform_audit.kube import _kubectl
from network_platform_audit.log import log
from network_platform_audit.log import log_result
from network_platform_audit.log import print_category
from network_platform_audit.run import run_log_only
from network_platform_audit.run import tool_available
from network_platform_audit.sysinv import _get_addrpool_list
from network_platform_audit.sysinv import _get_network_addrpool_list
from network_platform_audit.sysinv import build_pools_by_network_type


def _check_nodes_ready(cat):
    rc, nodes_out, _ = _kubectl("get nodes --no-headers")
    if rc != 0:
        state.category_failures[cat].append("kubectl get nodes failed")
    else:
        not_ready = [line for line in nodes_out.splitlines() if "NotReady" in line]
        if not_ready:
            for line in not_ready:
                node_name = line.split()[0]
                log_result(f"node {node_name}: Ready", "FAILED")
                state.category_failures[cat].append(f"node {node_name} is NotReady")
        else:
            log_result("all Kubernetes nodes Ready", "PASS")


def _check_critical_pods_running(cat):
    rc_ks, pods_ks, _ = _kubectl("get pods -n kube-system --no-headers")
    rc_cs, pods_cs, _ = _kubectl("get pods -n calico-system --no-headers")
    all_pods_out = ""
    if rc_ks == 0 and pods_ks:
        all_pods_out += pods_ks + "\n"
    if rc_cs == 0 and pods_cs:
        all_pods_out += pods_cs + "\n"

    critical_pods = ["calico-node", "kube-proxy", "coredns", "multus"]
    if all_pods_out:
        for pod_prefix in critical_pods:
            pod_lines = [line for line in all_pods_out.splitlines() if pod_prefix in line]
            if not pod_lines:
                log_result(f"pod {pod_prefix} in kube-system/calico-system", "FAILED")
                state.category_failures[cat].append(f"pod {pod_prefix} not found in kube-system or calico-system")
                continue
            all_running = all("Running" in line for line in pod_lines)
            if all_running:
                log_result(f"pod {pod_prefix} Running", "PASS")
            else:
                not_running = [line.split()[0] for line in pod_lines if "Running" not in line]
                log_result(f"pod {pod_prefix} Running", "FAILED")
                state.category_failures[cat].append(f"pods not Running: {not_running}")
    else:
        state.category_failures[cat].append("kubectl get pods failed for kube-system and calico-system")


def _check_critical_service_endpoints(cat):
    rc, ep_out, _ = _kubectl("get endpoints -A --no-headers")
    if rc != 0:
        log_result("kubectl get endpoints -A", "FAILED")
        state.category_failures[cat].append("kubectl get endpoints -A failed - cannot check critical service endpoints")
    elif not ep_out:
        log("[INFO] kubectl get endpoints returned no output - skipping endpoint check")
    else:
        empty_eps = [line for line in ep_out.splitlines() if "<none>" in line]
        critical_svcs = {"kubernetes", "coredns", "kube-dns"}
        critical_empty = []
        for line in empty_eps:
            parts = line.split()
            svc_name = parts[1] if len(parts) > 1 else ""
            if any(cs in svc_name for cs in critical_svcs):
                log_result(f"endpoints {svc_name}: not empty", "FAILED")
                state.category_failures[cat].append(f"critical service {svc_name} has empty endpoints")
                critical_empty.append(svc_name)
        if not critical_empty:
            log_result("no empty critical service endpoints", "PASS")


def _collect_k8s_cidrs():
    pod_cidrs, svc_cidrs = [], []
    rc, nodes_out, _ = _kubectl("get nodes -o jsonpath='{range .items[*]}{.spec.podCIDR}{\"\\n\"}{end}'")
    if rc == 0 and nodes_out:
        pod_cidrs = [c.strip() for c in nodes_out.replace("'", "").splitlines() if c.strip()]
    rc, apiserver_out, _ = run_log_only(
        "ps aux | grep kube-apiserver | grep -oP '(?<=--service-cluster-ip-range=)[^ ]+'"
    )
    if rc == 0 and apiserver_out:
        svc_cidrs = [c.strip() for c in apiserver_out.splitlines() if c.strip()]
    rc, kcm_out, _ = run_log_only(
        "ps aux | grep kube-controller-manager | grep -oP '(?<=--cluster-cidr=)[^ ]+'"
    )
    if rc == 0 and kcm_out:
        pod_cidrs += [c.strip() for c in kcm_out.splitlines() if c.strip()]
    pod_cidrs = list(set(pod_cidrs))
    svc_cidrs = list(set(svc_cidrs))
    return pod_cidrs, svc_cidrs


def _build_non_k8s_pool_nets(addrpools, pools_by_type):
    k8s_pool_names = {
        p.get("name", "")
        for net_type in ("cluster-pod", "cluster-service")
        for p in pools_by_type.get(net_type, [])
    }
    pool_nets = []
    for pool in addrpools:
        if pool.get("name", "") in k8s_pool_names:
            continue
        network = pool.get("network", pool.get("subnet", ""))
        prefix = pool.get("prefix", pool.get("prefix_length", ""))
        if network and prefix:
            try:
                pool_nets.append(ipaddress.ip_network(f"{network}/{prefix}", strict=False))
            except ValueError:
                pass
    return pool_nets


def _check_cidr_pool_overlap(cat, pod_cidrs, svc_cidrs, pool_nets):
    overlap_found = False
    if not pod_cidrs and not svc_cidrs:
        log("[WARN] could not collect PodCIDR or ServiceCIDR from any source "
            "(kubectl, kube-apiserver, kube-controller-manager) - overlap check skipped")
        state.category_warnings[cat].append(
            "PodCIDR/ServiceCIDR overlap check skipped: no k8s CIDR data available"
        )
    else:
        for cidr in pod_cidrs + svc_cidrs:
            try:
                k8s_net = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                continue
            for pool_net in pool_nets:
                if k8s_net.overlaps(pool_net):
                    overlap_found = True
                    log_result(f"k8s CIDR {cidr} overlaps sysinv pool {pool_net}", "FAILED")
                    state.category_failures[cat].append(f"k8s CIDR {cidr} overlaps sysinv pool {pool_net}")

        if not overlap_found:
            log_result("no PodCIDR/ServiceCIDR overlap with sysinv addrpools", "PASS")


def _get_api_server_vip():
    api_vip = None
    api_port = "6443"
    try:
        with open("/etc/kubernetes/admin.conf") as f:
            content = f.read()
        m = re.search(r"server:\s*https://\[([^\]]+)\]:(\d+)", content)
        if m:
            api_vip = m.group(1)
            api_port = m.group(2)
        else:
            m = re.search(r"server:\s*https://([^:\[\]]+):(\d+)", content)
            if m:
                api_vip = m.group(1)
                api_port = m.group(2)
    except Exception:
        pass
    return api_vip, api_port


def _check_api_server_healthz(cat, api_vip, api_port):
    if api_vip:
        url_vip = f"[{api_vip}]" if ":" in api_vip else api_vip
        rc, curl_out, _ = run_log_only(["curl", "-sk", f"https://{url_vip}:{api_port}/healthz"])
        if rc == 0 and "ok" in curl_out:
            log_result(f"Kubernetes API server {api_vip}:{api_port}/healthz", "PASS")
        else:
            log_result(f"Kubernetes API server {api_vip}:{api_port}/healthz", "FAILED")
            state.category_failures[cat].append(f"API server {api_vip}:{api_port}/healthz did not return 'ok'")
    else:
        log("[INFO] could not determine API server VIP - skipping /healthz check")


def test_k8s_nodes():
    cat = "TestSuite 13 - Kubernetes Nodes and Pods"
    desc = [
        "1) kubectl get nodes - verify no NotReady",
        "2) kubectl get pods -n kube-system - critical pods Running",
        "3) kubectl get endpoints -A - no empty endpoints for critical services",
        "4) PodCIDR/ServiceCIDR vs sysinv addrpools overlap check",
        "5) curl /healthz on Kubernetes API server VIP",
    ]
    print_category(cat, description=desc)

    if not tool_available("kubectl"):
        log("[FAIL] kubectl not available - required for Kubernetes checks")
        state.category_failures[cat].append("kubectl not installed")
        return

    _check_nodes_ready(cat)

    _check_critical_pods_running(cat)

    _check_critical_service_endpoints(cat)

    pod_cidrs, svc_cidrs = _collect_k8s_cidrs()

    addrpools = _get_addrpool_list()
    net_addrpools = _get_network_addrpool_list()
    pools_by_type = build_pools_by_network_type(net_addrpools, addrpools)
    if net_addrpools is None:
        log_result("system network-addrpool-list: command not available in this platform version", "WARN")
        state.category_warnings[cat].append("system network-addrpool-list not available in this platform version")
        return
    pool_nets = _build_non_k8s_pool_nets(addrpools, pools_by_type)

    _check_cidr_pool_overlap(cat, pod_cidrs, svc_cidrs, pool_nets)

    api_vip, api_port = _get_api_server_vip()
    _check_api_server_healthz(cat, api_vip, api_port)
