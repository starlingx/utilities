//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"context"
	"fmt"
	"log/slog"
	"maps"
	"os"
	"os/signal"
	"syscall"
	"time"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
	"k8s.io/client-go/rest"
)

// waitInterval is the seconds between monitoring iterations.
var waitInterval int

// heartbeatPath is the file touched by the run loop to signal liveness to
// the kubelet probe. The bash health_check function checks this file age.
const heartbeatPath = "/workdir/health/heartbeat"

// touchHeartbeat updates the heartbeat file modification time so the
// liveness probe (bash health_check) sees the manager as alive.
func touchHeartbeat() {
	if err := os.MkdirAll("/workdir/health", 0755); err != nil {
		slog.Debug("Failed to create health directory", "err", err)
		return
	}
	now := time.Now()
	if err := os.Chtimes(heartbeatPath, now, now); err != nil {
		// File may not exist yet, create it
		f, createErr := os.Create(heartbeatPath)
		if createErr != nil {
			slog.Debug("Failed to create heartbeat file", "err", createErr)
			return
		}
		f.Close()
	}
}

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "Full lifecycle management loop for OpenBao",
	Long: `Run the full OpenBao lifecycle management loop. This replaces the bash
main loop and handles: init detection, unseal, raft join, rekey-in-progress
recovery, and periodic healthchecks.

On startup:
  - Discover/validate current generation from Kubernetes

Each iteration:
  - Refresh pod addresses from Kubernetes
  - Load current generation secret
  - For each server: check health, handle init/sealed/raft-join
  - Check for rekey-in-progress and drive to completion
  - Sleep WaitInterval seconds before next iteration`,
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	SilenceUsage:       true,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Action: run")
		if globalConfig.WaitInterval != 0 {
			waitInterval = globalConfig.WaitInterval
		}

		if !useK8sConfig {
			return fmt.Errorf("run requires --k8s flag to be set (generation secrets are stored in Kubernetes)")
		}

		k8sConfig, err := getK8sConfig()
		if err != nil {
			return fmt.Errorf("failed to get kubernetes config: %w", err)
		}

		return runMainLoop(&globalConfig, k8sConfig)
	},
}

// runMainLoop implements the full lifecycle management loop.
// On startup: discovers current generation, runs one-time startup phase (init+join).
// Then enters infinite loop unsealing servers and checking for rekey-in-progress.
func runMainLoop(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config) error {
	// Set up context with signal handling for clean shutdown
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	// Phase 1: Ensure we have a valid CurrentKeySecret
	if err := DiscoverCurrentGeneration(cfg, k8sConfig); err != nil {
		slog.Warn("Failed to discover current generation on startup", "err", err)
		// Not fatal — init will create gen-001 if needed
	}

	// Phase 2: One-time startup phase (init uninitialized servers, join followers)
	if err := startupPhase(cfg, k8sConfig); err != nil {
		slog.Error("Startup phase failed", "err", err)
		// Not fatal — servers may come up later, retryable in next iteration
	}

	slog.Info("Run loop starting",
		"currentKeySecret", cfg.CurrentKeySecret,
		"waitInterval", waitInterval)

	// Phase 3: Main monitoring loop
	for {
		select {
		case <-ctx.Done():
			slog.Info("Received shutdown signal, exiting run loop")
			return nil
		default:
		}

		if err := runIteration(cfg, k8sConfig); err != nil {
			// Fatal errors are returned; transient errors are logged in runIteration
			return err
		}

		touchHeartbeat()
		slog.Debug("Iteration complete, sleeping", "seconds", waitInterval)
		select {
		case <-ctx.Done():
			slog.Info("Received shutdown signal during sleep, exiting")
			return nil
		case <-time.After(time.Duration(waitInterval) * time.Second):
		}
	}
}

// startupPhase performs one-time initialization before the main monitoring loop.
// If any server is already initialized (regardless of seal status), we conclude
// that initialization was previously completed and return immediately — unseal
// and raft-join are handled by the main monitoring loop.
// Only when NO server has ever been initialized do we run init on the first one.
func startupPhase(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config) error {
	slog.Info("Startup phase: checking cluster initialization state")

	// Wait for pod addresses to be available from Kubernetes
	if err := cfg.MigratePodConfig(k8sConfig); err != nil {
		return fmt.Errorf("startup: failed to refresh pod config: %w", err)
	}

	// Check each server — if ANY is already initialized, init was already done.
	// We deliberately ignore seal status: a sealed-but-initialized server still
	// proves that initialization completed previously. The main loop will unseal it.
	//
	// Track whether we successfully reached at least one server: failing to
	// connect (SetupClient) or failing a health check is NOT the same as a
	// server being uninitialized. We must not fall through to init unless at
	// least one server was actually queried successfully.
	reachedAny := false
	for host := range maps.Keys(cfg.ServerAddresses) {
		client, err := cfg.SetupClient(host)
		if err != nil {
			slog.Error("Startup: failed to setup client", "host", host, "err", err)
			continue
		}
		health, err := checkHealth(host, client)
		if err != nil {
			slog.Error("Startup: health check failed", "host", host, "err", err)
			continue
		}
		reachedAny = true
		if health.Initialized {
			slog.Info("Startup: found initialized server, init previously completed",
				"host", host, "sealed", health.Sealed)
			return nil
		}
	}

	// If we could not reach any server, we cannot determine initialization
	// state — do not proceed to init. Return an error so the caller retries.
	if !reachedAny {
		return fmt.Errorf("startup: could not reach any server — cannot determine initialization state")
	}

	// No initialized server found — perform first-time initialization
	firstHost := firstServerHost(cfg)
	if firstHost == "" {
		return fmt.Errorf("startup: no server addresses configured")
	}
	slog.Info("Startup: no initialized server found, initializing first server",
		"host", firstHost)
	client, err := cfg.SetupClient(firstHost)
	if err != nil {
		return fmt.Errorf("startup: failed to setup client for init: %w", err)
	}
	if err := runInitAndStore(cfg, client, firstHost); err != nil {
		return fmt.Errorf("startup: init failed: %w", err)
	}
	// Reload generation after successful init
	if err := DiscoverCurrentGeneration(cfg, k8sConfig); err != nil {
		return fmt.Errorf("startup: discover generation after init: %w", err)
	}

	slog.Info("Startup phase complete")
	return nil
}

// firstServerHost returns the first host from ServerAddresses deterministically.
// For single-server AIO-SX this is the only host; for multi-server this picks
// one to be initialized first (arbitrary but deterministic).
func firstServerHost(cfg *baoConfig.MonitorConfig) string {
	for host := range cfg.ServerAddresses {
		return host
	}
	return ""
}

// discoverCurrentGeneration sets CurrentKeySecret from Kubernetes if it's empty.
// DiscoverCurrentGeneration ensures CurrentKeySecret points to the latest
// generation secret in Kubernetes. If empty, it discovers and sets it. If
// already set, it verifies the pointer matches the latest generation — a stale
// pointer (e.g. from a crash after rekey stored a new generation but before
// config was persisted) would cause unseal failures.
func DiscoverCurrentGeneration(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config) error {
	gens, err := cfg.ListGenerationSecrets()
	if err != nil {
		return fmt.Errorf("failed to list generation secrets: %w", err)
	}

	if len(gens) == 0 {
		slog.Info("No generation secrets found in Kubernetes, waiting for init")
		return nil
	}

	latest := gens[len(gens)-1]

	if cfg.CurrentKeySecret == "" {
		cfg.CurrentKeySecret = latest
		slog.Info("Discovered current generation from Kubernetes",
			"currentKeySecret", cfg.CurrentKeySecret)
	} else if cfg.CurrentKeySecret != latest {
		slog.Warn("CurrentKeySecret is stale, advancing to latest generation",
			"stale", cfg.CurrentKeySecret, "latest", latest)
		cfg.CurrentKeySecret = latest
	}

	return nil
}

// runIteration performs a single pass of the run loop:
// refresh pods, load generation secret, check each server, handle rekey.
func runIteration(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config) error {
	// Refresh pod addresses from Kubernetes
	if err := cfg.MigratePodConfig(k8sConfig); err != nil {
		slog.Error("Failed to refresh pod config, will retry next iteration", "err", err)
		return nil // Transient error, continue
	}

	// Load current generation secret (if we have one).
	// genSecret may be nil here if CurrentKeySecret is empty — this happens
	// before init has completed (no generation secrets exist in K8s yet).
	// The nil is handled downstream: processServer returns an error for sealed
	// servers and logs warnings for other states.
	var genSecret *baoConfig.GenerationSecret
	if cfg.CurrentKeySecret != "" {
		var err error
		genSecret, err = cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
		if err != nil {
			slog.Error("Failed to load generation secret, attempting rediscovery",
				"name", cfg.CurrentKeySecret, "err", err)
			// Clear stale pointer so DiscoverCurrentGeneration picks latest.
			// The stale genSecret (nil from failed load) will not be used below
			// because we return immediately. Next iteration will load from the
			// newly-discovered CurrentKeySecret.
			cfg.CurrentKeySecret = ""
			discoverErr := DiscoverCurrentGeneration(cfg, k8sConfig)
			if discoverErr != nil {
				slog.Error("Failed to rediscover generation", "err", discoverErr)
			}
			return nil
		}
	}

	// Process each server
	for host := range maps.Keys(cfg.ServerAddresses) {
		if err := processServer(cfg, host, genSecret); err != nil {
			// Log per-server errors and continue to next server
			slog.Error("Error processing server", "host", host, "err", err)
			continue
		}
	}

	// Check for rekey-in-progress and drive to completion
	if err := HandleRekeyIfNeeded(cfg, k8sConfig, genSecret); err != nil {
		slog.Error("Error checking rekey status", "err", err)
	}

	return nil
}

// processServer checks a single server's health and takes appropriate action
// during steady-state monitoring. The main loop only handles unsealing sealed
// servers — initialization and raft join are handled exclusively in startupPhase.
func processServer(cfg *baoConfig.MonitorConfig, host string, genSecret *baoConfig.GenerationSecret) error {
	client, err := cfg.SetupClient(host)
	if err != nil {
		return fmt.Errorf("failed to setup client for host %s: %w", host, err)
	}

	health, err := checkHealth(host, client)
	if err != nil {
		return fmt.Errorf("health check failed for host %s: %w", host, err)
	}

	switch {
	case !health.Initialized:
		// In steady-state, uninitialized servers should not appear.
		// Init and raft-join are handled at startup. If a server appears
		// uninitialized here, it indicates pod replacement or PVC loss —
		// a restart of baomon will re-run startupPhase to handle it.
		slog.Error("Server not initialized during steady-state monitoring",
			"host", host)

	case health.Sealed:
		slog.Info("Server is sealed, attempting unseal", "host", host)
		if genSecret == nil {
			return fmt.Errorf("cannot unseal host %s: no generation secret loaded", host)
		}
		if err := UnsealWithGenKeys(client, genSecret); err != nil {
			return fmt.Errorf("unseal failed for host %s: %w", host, err)
		}
		slog.Info("Unseal successful", "host", host)

	case health.ClusterID == "":
		// Initialized and unsealed but no cluster membership. This is an
		// abnormal state (possible data corruption or misconfiguration).
		// Do not auto-heal — flag for manual investigation.
		slog.Error("Server initialized and unsealed but has no cluster membership — "+
			"possible data corruption or misconfiguration, requires manual intervention",
			"host", host)

	default:
		slog.Debug("Server healthy", "host", host,
			"version", health.Version, "clusterID", health.ClusterID)
	}

	return nil
}

// runInitAndStore initializes an OpenBao server and stores the result as a
// new immutable generation secret. Uses 5 shares / 3 threshold per requirement 9.
func runInitAndStore(cfg *baoConfig.MonitorConfig, client *clientapi.Client, host string) error {
	slog.Info("Initializing OpenBao server",
		"host", host, "shares", InitSecretShares, "threshold", InitSecretThreshold)

	// Pre-flight: verify K8s connectivity before calling /sys/init.
	// Once init is called, the keys only exist in the response — if we can't
	// store them to K8s afterward, they're lost.
	_, err := cfg.ListGenerationSecrets()
	if err != nil {
		return fmt.Errorf("pre-flight K8s check failed (cannot list secrets): %w", err)
	}

	opts := &clientapi.InitRequest{
		SecretShares:    InitSecretShares,
		SecretThreshold: InitSecretThreshold,
	}

	response, err := client.Sys().Init(opts)
	if err != nil {
		return fmt.Errorf("init API call failed: %w", err)
	}

	// Build and validate generation secret from init response
	genSecret, err := baoConfig.ParseInitResponseToGeneration(response)
	if err != nil {
		return fmt.Errorf("parsing init response to generation: %w", err)
	}
	if err := baoConfig.ValidateGenerationSecret(genSecret); err != nil {
		return fmt.Errorf("init produced invalid generation secret: %w", err)
	}

	// Store + verify using shared helper (retry on transient K8s failures)
	genName, err := cfg.StoreAndVerifyGeneration(genSecret, InitSecretThreshold)
	if err != nil {
		return err
	}

	// Cache the loaded secret in memory
	cfg.SetLoadedGenerationSecret(genSecret)

	slog.Info("Init complete, generation secret stored",
		"host", host, "generation", genName)

	// Unseal the freshly initialized server
	slog.Info("Unsealing freshly initialized server", "host", host)
	if err := UnsealWithGenKeys(client, genSecret); err != nil {
		slog.Error("Failed to unseal after init", "host", host, "err", err)
		// Not fatal — the next iteration will attempt unseal
	}

	return nil
}

// unsealWithGenKeys submits threshold keys from the generation secret to unseal
// a sealed OpenBao server.
func UnsealWithGenKeys(client *clientapi.Client, genSecret *baoConfig.GenerationSecret) error {
	if genSecret == nil {
		return fmt.Errorf("generation secret is nil")
	}

	keysNeeded := InitSecretThreshold
	if len(genSecret.Keys) < keysNeeded {
		return fmt.Errorf("not enough keys: need %d, have %d", keysNeeded, len(genSecret.Keys))
	}

	for i := 0; i < keysNeeded; i++ {
		result, err := client.Sys().Unseal(genSecret.Keys[i])
		if err != nil {
			return fmt.Errorf("unseal failed on key %d: %w", i, err)
		}
		if !result.Sealed {
			slog.Debug("Server unsealed", "keysUsed", i+1)
			return nil
		}
		slog.Debug("Unseal progress", "submitted", i+1, "threshold", result.T, "progress", result.Progress)
	}

	return fmt.Errorf("server still sealed after submitting %d keys", keysNeeded)
}

func init() {
	runCmd.Flags().IntVar(&waitInterval, "waitInterval", 5, "wait time in seconds between each check iteration")
	RootCmd.AddCommand(runCmd)
}
