//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig

import (
	"fmt"
	"net"
	"regexp"
	"strconv"
	"strings"
)

// PodDNSName builds the dashed-IP pod DNS name <dashed-ip>.<namespace>.<suffix>.
// IPv4 dots and IPv6 colons become dashes (172.16.0.5 -> 172-16-0-5,
// fe80::1 -> fe80--1). IPv6 addresses with a leading :: are rejected because they
// produce a leading dash, which does not form a valid pod DNS label. Returns an
// error on a malformed IP or leading ::.
func PodDNSName(podIP, namespace, suffix string) (string, error) {
	ip := net.ParseIP(podIP)
	if ip == nil {
		return "", fmt.Errorf("invalid pod IP %q", podIP)
	}

	var dashed string
	if ip.To4() != nil {
		dashed = strings.ReplaceAll(ip.String(), ".", "-")
	} else {
		compressed := ip.String()
		// Leading "::" (::, ::1, ::-prefixed) is an unsupported pod IP:
		// StarlingX pods get GUA/ULA addresses, never loopback. The dash it
		// produces is also parsed by CoreDNS as a reverse ip6.arpa query, not
		// a pod A record, so reject it rather than emit a bad name.
		if strings.HasPrefix(compressed, "::") {
			return "", fmt.Errorf("pod IP %q has a leading \"::\" which does not form a valid pod DNS name", podIP)
		}
		dashed = strings.ReplaceAll(compressed, ":", "-")
	}

	return fmt.Sprintf("%s.%s.%s", dashed, namespace, suffix), nil
}

// ServerURL builds the https://host:port URL, bracketing IPv6 literal hosts.
func ServerURL(host string, port int) string {
	return "https://" + net.JoinHostPort(host, strconv.Itoa(port))
}

// dnsHostPattern matches an RFC 1123 hostname: dot-separated LDH labels, each
// 1-63 chars (the {0,61} bound plus the two anchors), starting and ending
// alphanumeric, hyphens only interior.
var dnsHostPattern = regexp.MustCompile(
	`^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$`,
)

// IsValidServerHost reports whether host is an IP literal (including a bare
// IPv6 literal) or a valid RFC 1123 hostname. Single-label names are accepted;
// a trailing root dot and non-ASCII names are rejected.
func IsValidServerHost(host string) bool {
	if host == "" {
		return false
	}

	if net.ParseIP(host) != nil {
		return true
	}

	// A raw colon in a non-IP host means unbracketed IPv6 or a stray port.
	if strings.Contains(host, ":") {
		return false
	}

	return dnsHostPattern.MatchString(host)
}
