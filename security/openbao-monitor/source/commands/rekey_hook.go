//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"fmt"
	"log/slog"
	"maps"
	"time"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	"k8s.io/client-go/rest"
)

// InitSecretShares and InitSecretThreshold define the Shamir parameters
// used when initializing OpenBao. Per requirement 9, these remain at 5/3.
const InitSecretShares = 5
const InitSecretThreshold = 3

// postIterationHook is called at the end of each run loop iteration.
// Set below to enable rekey-in-progress detection.
var postIterationHook func(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config, genSecret *baoConfig.GenerationSecret) error

func init() {
	// Register rekey detection as the post-iteration hook for the run loop.
	postIterationHook = handleRekeyIfNeeded
}

// handleRekeyIfNeeded checks if a rekey operation is in progress on any server
// and drives it to completion if so.
func handleRekeyIfNeeded(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config, genSecret *baoConfig.GenerationSecret) error {
	if genSecret == nil {
		// No generation secret loaded, can't participate in rekey
		return nil
	}

	// Use the first available healthy server to check rekey status
	for host := range maps.Keys(cfg.ServerAddresses) {
		client, err := cfg.SetupClient(host)
		if err != nil {
			continue
		}

		// Check health — only check rekey on initialized, unsealed servers
		health, err := checkHealth(host, client)
		if err != nil || !health.Initialized || health.Sealed {
			continue
		}

		// Create a rekey process to check status
		proc := &rekey.RekeyProcess{
			Config:    cfg,
			State:     rekey.StateIdle,
			NewShares: InitSecretShares,
			Threshold: InitSecretThreshold,
		}

		sys := client.Sys()
		inProgress, err := proc.CheckInProgress(sys)
		if err != nil {
			slog.Debug("Failed to check rekey status", "host", host, "err", err)
			continue
		}

		if inProgress {
			slog.Info("Rekey in progress detected, driving to completion", "host", host)
			if err := RecoverInProgressRekey(cfg, k8sConfig, sys); err != nil {
				slog.Error("Failed to drive rekey to completion", "host", host, "err", err)
			}
		}

		// Only need to check one healthy server for rekey status
		return nil
	}

	return nil
}

// RecoverInProgressRekey submits shards and stores the result for an in-progress rekey.
func RecoverInProgressRekey(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config, sys rekey.SysAPI) error {
	proc := &rekey.RekeyProcess{
		Config:    cfg,
		State:     rekey.StateInProgress,
		NewShares: InitSecretShares,
		Threshold: InitSecretThreshold,
	}

	// Get the nonce from the rekey status
	status, err := sys.RekeyStatus()
	if err != nil {
		return fmt.Errorf("failed to get rekey status: %w", err)
	}
	if !status.Started {
		return nil // Rekey no longer in progress
	}
	proc.Nonce = status.Nonce

	// Submit shards
	response, err := proc.SubmitShards(sys)
	if err != nil {
		return fmt.Errorf("failed to submit shards during rekey: %w", err)
	}

	// Store result as new generation — retry with backoff on transient failures.
	// The keys exist only in the RekeyUpdateResponse; if we fail to store them,
	// they're lost and the rekey becomes unrecoverable (must cancel and re-initiate).
	var storeErr error
	for attempt := 1; attempt <= 3; attempt++ {
		storeErr = proc.StoreResult(response)
		if storeErr == nil {
			break
		}
		slog.Error("Failed to store rekey result, retrying",
			"attempt", attempt, "err", storeErr)
		if attempt < 3 {
			time.Sleep(time.Duration(attempt) * 2 * time.Second)
		}
	}
	if storeErr != nil {
		return fmt.Errorf("failed to store rekey result after 3 attempts (keys may be lost): %w", storeErr)
	}

	// Re-read stored secret from K8s and confirm it matches what we stored.
	// This guards against silent storage corruption before proceeding to
	// verification (which would commit the new keys as active).
	stored, err := cfg.LoadGenerationSecret()
	if err != nil {
		return fmt.Errorf("failed to re-read generation secret after store: %w", err)
	}
	if len(stored.Keys) != len(response.Keys) {
		return fmt.Errorf("stored secret key count (%d) does not match response (%d)", len(stored.Keys), len(response.Keys))
	}
	for i, key := range response.Keys {
		if stored.Keys[i] != key {
			return fmt.Errorf("stored secret key[%d] does not match response", i)
		}
	}
	slog.Debug("Re-read verification passed: stored secret matches in-memory response")

	// Verify the rekey if verification was required
	if response.VerificationRequired {
		if err := proc.Verify(sys, response); err != nil {
			return fmt.Errorf("rekey verification failed: %w", err)
		}
	}

	slog.Info("Rekey driven to completion, new generation stored",
		"currentKeySecret", cfg.CurrentKeySecret)
	return nil
}
