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
)

// HandleRekeyIfNeeded checks if a rekey operation is in progress on any server
// and drives it to completion if so. Called directly from runIteration.
func HandleRekeyIfNeeded(cfg *baoConfig.MonitorConfig, genSecret *baoConfig.GenerationSecret) error {
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

		sys := client.Sys()
		status, err := sys.RekeyStatus()
		if err != nil {
			slog.Debug("Failed to check rekey status", "host", host, "err", err)
			continue
		}

		if status != nil && status.Started {
			slog.Info("Rekey in progress detected, driving to completion", "host", host)
			if err := RecoverInProgressRekey(cfg, sys); err != nil {
				slog.Error("Failed to drive rekey to completion", "host", host, "err", err)
			}
		}

		// Only need to check one healthy server for rekey status
		return nil
	}

	return nil
}

// RecoverInProgressRekey submits shards and stores the result for an in-progress rekey.
func RecoverInProgressRekey(cfg *baoConfig.MonitorConfig, sys rekey.SysAPI) error {
	// Get the nonce from the rekey status
	status, err := sys.RekeyStatus()
	if err != nil {
		return fmt.Errorf("failed to get rekey status: %w", err)
	}
	if status == nil || !status.Started {
		return nil // Rekey no longer in progress
	}

	proc := &rekey.RekeyProcess{
		Config:    cfg,
		State:     rekey.StateInProgress,
		NewShares: status.N,
		Threshold: status.T,
		Nonce:     status.Nonce,
	}

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

	// Advance the pointer after verification (which applies the new key on the
	// server). A crash here leaves the pointer on a stale generation; recovery
	// is by rediscovery on unseal failure, not by trusting it.
	if err := cfg.ActivateGeneration(proc.StoredGenName, nil); err != nil {
		return fmt.Errorf("rekey verified but failed to advance current key pointer to %q: %w",
			proc.StoredGenName, err)
	}

	slog.Info("Rekey driven to completion, new generation active",
		"currentKeySecret", cfg.CurrentKeySecret)
	return nil
}
