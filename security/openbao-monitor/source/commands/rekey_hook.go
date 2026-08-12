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

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	"k8s.io/client-go/rest"
)

// InitSecretShares and InitSecretThreshold define the Shamir parameters
// used when initializing OpenBao. Per requirement 9, these remain at 5/3.
const InitSecretShares = 5
const InitSecretThreshold = 3

// HandleRekeyIfNeeded checks if a rekey operation is in progress on any server
// and drives it to completion if so. Called directly from runIteration.
func HandleRekeyIfNeeded(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config, genSecret *baoConfig.GenerationSecret) error {
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

	// Store with retry + read-back verification
	if err := proc.StoreResultWithRetry(response, 3); err != nil {
		return err
	}

	// Server-side verification
	if err := proc.VerifyWithServer(sys, response); err != nil {
		return fmt.Errorf("rekey verification failed: %w", err)
	}

	slog.Info("Rekey driven to completion, new generation stored",
		"currentKeySecret", cfg.CurrentKeySecret)
	return nil
}
