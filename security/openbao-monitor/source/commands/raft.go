// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
package baoCommands

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"os"
	"strings"
	"time"

	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
	baoConfig "opendev.org/starlingx/utilities/openbao-monitor/config"
)

var customPayload string
var raftAddress string

// raftJoinFollower joins followerHost to the Raft cluster led by leaderAPIAddr.
// leaderAPIAddr must be covered by the server TLS cert SANs (use the -active
// service DNS name, not a raw pod IP: the cert's only IP SAN is 127.0.0.1).
func raftJoinFollower(cfg *baoConfig.MonitorConfig, followerHost, leaderAPIAddr string) error {
	client, err := cfg.SetupClient(followerHost)
	if err != nil {
		return fmt.Errorf("join: setup client for %s: %w", followerHost, err)
	}

	caPEM, err := os.ReadFile(cfg.CACert)
	if err != nil {
		return fmt.Errorf("join: read CA cert %q: %w", cfg.CACert, err)
	}

	req := &clientapi.RaftJoinRequest{
		LeaderAPIAddr: leaderAPIAddr,
		LeaderCACert:  strings.TrimSuffix(string(caPEM), "\n"),
	}

	res, err := client.Sys().RaftJoin(req)
	if err != nil {
		return fmt.Errorf("join: RaftJoin API for %s: %w", followerHost, err)
	}
	if !res.Joined {
		return fmt.Errorf("join: %s did not join (API returned joined=false)", followerHost)
	}
	slog.Info("join: follower joined raft cluster", "host", followerHost, "leader", leaderAPIAddr)
	return nil
}

const raftJoinInterval = 5 * time.Second

// raftJoinFollowerRetry retries raftJoinFollower until it succeeds, ctx is
// cancelled, or maxAttempts is reached. Early attempts can fail while the
// follower or leader is still converging on a fresh deploy.
func raftJoinFollowerRetry(ctx context.Context, cfg *baoConfig.MonitorConfig, followerHost, leaderAPIAddr string, maxAttempts int) error {
	var lastErr error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		lastErr = raftJoinFollower(cfg, followerHost, leaderAPIAddr)
		if lastErr == nil {
			return nil
		}
		slog.Debug("join: attempt failed, will retry",
			"host", followerHost, "attempt", attempt, "maxAttempts", maxAttempts, "err", lastErr)
		if attempt == maxAttempts {
			break
		}
		select {
		case <-ctx.Done():
			return fmt.Errorf("join: cancelled while joining %s: %w", followerHost, ctx.Err())
		case <-time.After(raftJoinInterval):
		}
	}
	return fmt.Errorf("join: %s failed after %d attempts: %w", followerHost, maxAttempts, lastErr)
}

var joinraftCmd = &cobra.Command{
	Use:   "joinRaft node",
	Short: "Joins the node to the raft cluster",
	Long: `Joins the node to the raft cluster.

The node will join the raft cluster, with the leader node address specified in
the flag raft-address. It will use the CACert file specified in the baomon
configs.

Or, the raft cluster specifications can be contained in a JSON file, which can
be pointed by the flag raft-config. Please consult the /sys/storage/raft page
in the Openbao API documentations for details.

One of the two above flags must be used to specify the raft cluster. Otherwise
the command will not run.
`,
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	SilenceUsage:       true,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Starting joinRaft", "node", args[0])

		switch {
		case customPayload != "":
			// JSON payload path: the helper only covers leader-address + CA.
			newClient, err := globalConfig.SetupClient(args[0])
			if err != nil {
				return fmt.Errorf("join: setup client for %s: %w", args[0], err)
			}
			var RJReq clientapi.RaftJoinRequest
			payloadbuf, err := os.ReadFile(customPayload)
			if err != nil {
				return fmt.Errorf("unable to open file for raft-config %v: %v", customPayload, err)
			}
			if err := json.Unmarshal(payloadbuf, &RJReq); err != nil {
				return fmt.Errorf("unable to marshal raft-config %v: %v", customPayload, err)
			}
			slog.Debug("Calling RaftJoin API command...")
			RJRes, err := newClient.Sys().RaftJoin(&RJReq)
			if err != nil {
				return fmt.Errorf("join: RaftJoin API for %s: %w", args[0], err)
			}
			if !RJRes.Joined {
				return fmt.Errorf("join: %s did not join (API returned joined=false)", args[0])
			}
			slog.Info("join: follower joined raft cluster", "host", args[0])
			return nil

		case raftAddress != "":
			// Bracket a bare IPv6 literal; leave a full URL untouched.
			leaderAddr := raftAddress
			if !strings.Contains(raftAddress, "://") {
				if ip := net.ParseIP(raftAddress); ip != nil && ip.To4() == nil {
					leaderAddr = "[" + raftAddress + "]"
				}
			}
			return raftJoinFollower(&globalConfig, args[0], leaderAddr)

		default:
			return fmt.Errorf("either raft-config or raft-address must be specified")
		}
	},
}

func init() {
	joinraftCmd.PersistentFlags().StringVar(&customPayload, "raft-config", "",
		"A JSON file containing the API parameters for joinRaft")
	joinraftCmd.PersistentFlags().StringVar(&raftAddress, "raft-address", "",
		"Address of the leader node in the raft cluster")
	RootCmd.AddCommand(joinraftCmd)
}
