//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"fmt"
	"log/slog"

	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	"github.com/pingcap/failpoint"
	"github.com/spf13/cobra"
)

// rekey command flags
var rekeyShares int
var rekeyThreshold int

var rekeyCmd = &cobra.Command{
	Use:   "rekey DNSHost",
	Short: "Initiate and drive a full rekey operation",
	Long: `Initiate a rekey operation on the specified OpenBao server.
This generates new unseal key shards and stores them as a new immutable
generation secret in Kubernetes. The previous generation secret is retained.

Requires --k8s flag since the new generation secret must be stored in Kubernetes.`,
	Args:              cobra.ExactArgs(1),
	PersistentPreRunE: setupCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		cmd.SilenceUsage = true
		host := args[0]

		slog.Debug("Action: rekey", "host", host)

		if !useK8sConfig {
			return fmt.Errorf("rekey requires --k8s flag to be set (generation secrets are stored in Kubernetes)")
		}

		// Create a client for the target host
		newClient, err := globalConfig.SetupClient(host)
		if err != nil {
			return fmt.Errorf("failed to setup client for host %s: %w", host, err)
		}

		// Check server health before proceeding
		healthResult, err := checkHealth(host, newClient)
		if err != nil {
			return fmt.Errorf("failed to check health on host %s: %w", host, err)
		}

		if !healthResult.Initialized {
			return fmt.Errorf("server on host %s is not initialized; cannot rekey an uninitialized server", host)
		}

		if healthResult.Sealed {
			return fmt.Errorf("server on host %s is sealed; unseal the server before attempting rekey", host)
		}

		// Discover the current generation if not already set
		if globalConfig.CurrentKeySecret == "" {
			if err := DiscoverCurrentGeneration(&globalConfig, nil); err != nil {
				return fmt.Errorf("failed to discover current generation: %w", err)
			}
			if globalConfig.CurrentKeySecret == "" {
				return fmt.Errorf("no generation secrets found; server must be initialized first")
			}
		}

		// Load the current generation secret to ensure we have keys available
		_, err = globalConfig.LoadGenerationSecret(globalConfig.CurrentKeySecret)
		if err != nil {
			return fmt.Errorf("failed to load current generation secret: %w", err)
		}

		// The openbao client's Sys() satisfies the rekey.SysAPI interface
		sys := newClient.Sys()

		// Create the rekey process
		proc := &rekey.RekeyProcess{
			Config:    &globalConfig,
			State:     rekey.StateIdle,
			NewShares: rekeyShares,
			Threshold: rekeyThreshold,
		}

		// Check if a rekey is already in progress
		inProgress, err := proc.CheckInProgress(sys)
		if err != nil {
			return fmt.Errorf("failed to check rekey status: %w", err)
		}
		if inProgress {
			slog.Info("Rekey already in progress, driving to completion", "host", host)
			if err := RecoverInProgressRekey(&globalConfig, nil, sys); err != nil {
				return fmt.Errorf("failed to drive in-progress rekey: %w", err)
			}
			slog.Info("In-progress rekey driven to completion",
				"host", host,
				"newGeneration", globalConfig.CurrentKeySecret)
			return nil
		}

		// Step 1: Initiate rekey
		slog.Info("Initiating rekey", "host", host, "shares", rekeyShares, "threshold", rekeyThreshold)

		err = proc.Start(sys)
		if err != nil {
			return fmt.Errorf("failed to initiate rekey: %w", err)
		}

		// Step 2: Submit shards
		slog.Info("Submitting unseal key shards for rekey")

		response, err := proc.SubmitShards(sys)
		if err != nil {
			return fmt.Errorf("failed to submit shards during rekey: %w", err)
		}

		// Failpoint 1: Rekey: After Shards Submitted, Before K8s Store
		// Simulates: crash after shards obtained from server, before K8s secret creation
		failpoint.Inject("fp_rekey_after_shards_before_store", func() {
			slog.Warn("Failpoint triggered: fp_rekey_after_shards_before_store")
			failpoint.Return(fmt.Errorf("failpoint: rekey after shards before store"))
		})

		// Step 3: Store the result as a new generation secret — retry on transient
		// failures. The keys exist only in the RekeyUpdateResponse; losing them
		// means the rekey is unrecoverable.
		slog.Info("Storing new generation secret")

		if err := proc.StoreResultWithRetry(response, 3); err != nil {
			return err
		}

		// Failpoint 3: After Pointer Updated, Before Verification
		// Simulates: crash after all data persisted, pointer updated, before verification
		failpoint.Inject("fp_rekey_after_pointer_before_verify", func() {
			slog.Warn("Failpoint triggered: fp_rekey_after_pointer_before_verify")
			failpoint.Return(fmt.Errorf("failpoint: rekey after pointer before verify"))
		})

		// Step 4: Verify the rekey (confirms we received correct keys)
		if !response.VerificationRequired {
			return fmt.Errorf("rekey did not require verification, but should have")
		}
		slog.Info("Verifying rekey with new keys")
		if err := proc.VerifyWithServer(sys, response); err != nil {
			return fmt.Errorf("rekey verification failed: %w", err)
		}

		slog.Info("Rekey operation completed successfully",
			"host", host,
			"newGeneration", globalConfig.CurrentKeySecret)
		return nil
	},
	PersistentPostRunE: cleanCmd,
}

var rekeyStatusCmd = &cobra.Command{
	Use:   "status DNSHost",
	Short: "Check if a rekey operation is in progress",
	Long:  `Query the specified OpenBao server to determine if a rekey operation is currently in progress.`,
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		cmd.SilenceUsage = true
		host := args[0]

		slog.Debug("Action: rekey status", "host", host)

		// Create a client for the target host
		newClient, err := globalConfig.SetupClient(host)
		if err != nil {
			return fmt.Errorf("failed to setup client for host %s: %w", host, err)
		}

		// Check server health
		healthResult, err := checkHealth(host, newClient)
		if err != nil {
			return fmt.Errorf("failed to check health on host %s: %w", host, err)
		}

		if !healthResult.Initialized {
			return fmt.Errorf("server on host %s is not initialized", host)
		}

		if healthResult.Sealed {
			return fmt.Errorf("server on host %s is sealed; cannot check rekey status", host)
		}

		// Use the rekey process to check status
		proc := &rekey.RekeyProcess{
			State: rekey.StateIdle,
		}

		sys := newClient.Sys()
		inProgress, err := proc.CheckInProgress(sys)
		if err != nil {
			return fmt.Errorf("failed to check rekey status: %w", err)
		}

		if inProgress {
			fmt.Printf("Rekey is IN PROGRESS on host %s\n", host)
		} else {
			fmt.Printf("No rekey in progress on host %s\n", host)
		}

		return nil
	},
}

func init() {
	rekeyCmd.Flags().IntVar(&rekeyShares, "shares", 5,
		"Number of key shares to generate during rekey")
	rekeyCmd.Flags().IntVar(&rekeyThreshold, "threshold", 3,
		"Number of key shares required to unseal after rekey")

	rekeyCmd.AddCommand(rekeyStatusCmd)
	RootCmd.AddCommand(rekeyCmd)
}
