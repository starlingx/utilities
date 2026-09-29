//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"context"
	"errors"
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
	k8sErrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/rest"
)

// waitInterval is the seconds between monitoring iterations.
var waitInterval int

// heartbeatPath is the file touched by the run loop to signal liveness to
// the kubelet probe. The bash health_check function checks this file age.
const heartbeatPath = "/workdir/health/heartbeat"

var errUnsealCandidateRejected = errors.New("unseal candidate rejected")
var errNoGenerationUnsealed = errors.New("no known generation could unseal the server")

// Limit of the # of recovery passes before escalation
const unsealEscalationThreshold = 10

// UnsealEscalationTracker tracks consecutive failed unseal/recovery attempts
// and emits a terminal signal once the threshold is exceeded.
type UnsealEscalationTracker struct {
	FailureCount  int
	Threshold     int
	SignalEmitted bool
	LastError     string
	// pendingName/pendingSecret hold a deferred pointer-repair: a recovery
	// unseal succeeded but the CurrentKeySecret pointer write failed, so the
	// next iteration retries ActivateGeneration.
	pendingName   string
	pendingSecret *baoConfig.GenerationSecret
}

// IncrementFailure records a failed attempt and returns true the first time the
// failure count reaches the threshold (so the terminal signal is emitted once).
func (t *UnsealEscalationTracker) IncrementFailure(reason string) bool {
	t.FailureCount++
	t.LastError = reason
	if t.FailureCount >= t.Threshold && !t.SignalEmitted {
		t.SignalEmitted = true
		return true // Signal should be emitted
	}
	return false
}

// ResetFailures clears the failure count and signal state after a success.
func (t *UnsealEscalationTracker) ResetFailures() {
	t.FailureCount = 0
	t.SignalEmitted = false
	t.LastError = ""
}

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

	trackers := make(map[string]*UnsealEscalationTracker)

	// Phase 3: Main monitoring loop
	for {
		select {
		case <-ctx.Done():
			slog.Info("Received shutdown signal, exiting run loop")
			return nil
		default:
		}

		if err := runIteration(cfg, k8sConfig, trackers); err != nil {
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

// DiscoverCurrentGeneration reconciles cfg.CurrentKeySecret (an in-memory cache)
// from the authoritative mutable pointer secret in Kubernetes.
//
// Behavior:
//   - Pointer secret exists: adopt the generation it references. We do NOT
//     second-guess it against the highest sequence number, so an interrupted
//     rekey does not silently activate a stored-but-unverified generation.
//   - Pointer secret absent but generation secrets exist: this is a first boot
//     under the pointer model (or an upgrade from a pre-pointer system). Adopt
//     the highest-sequence generation and seed the pointer secret from it.
//   - Neither pointer nor generations exist: leave CurrentKeySecret empty and
//     wait for init to create gen-001 and the pointer.
func DiscoverCurrentGeneration(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config) error {
	pointer, err := cfg.LoadCurrentKeyPointer()
	if err != nil {
		return fmt.Errorf("failed to load current key pointer: %w", err)
	}

	if pointer != "" {
		if cfg.CurrentKeySecret != pointer {
			slog.Info("Reconciled current generation from pointer secret",
				"previous", cfg.CurrentKeySecret, "current", pointer)
		}
		cfg.CurrentKeySecret = pointer
		return nil
	}

	// No pointer secret yet — fall back to the highest-sequence generation.
	gens, err := cfg.ListGenerationSecrets()
	if err != nil {
		return fmt.Errorf("failed to list generation secrets: %w", err)
	}

	if len(gens) == 0 {
		slog.Info("No pointer secret and no generation secrets found, waiting for init")
		return nil
	}

	latest := gens[len(gens)-1]
	slog.Warn("No pointer secret found; seeding it from the highest-sequence generation",
		"latest", latest)

	if err := cfg.ActivateGeneration(latest, nil); err != nil {
		return fmt.Errorf("failed to activate generation %v: %v", latest, err)
	}

	return nil
}

// runIteration performs a single pass of the run loop:
// refresh pods, load generation secret, check each server, handle rekey.
func runIteration(cfg *baoConfig.MonitorConfig, k8sConfig *rest.Config, trackers map[string]*UnsealEscalationTracker) error {
	// Refresh pod addresses from Kubernetes
	k8sAvailable := true
	if err := cfg.MigratePodConfig(k8sConfig); err != nil {
		if !baoConfig.IsTransientK8sError(err) {
			return fmt.Errorf("failed to refresh pod config with non-transient Kubernetes error: %w", err)
		}
		k8sAvailable = false
		slog.Error("Failed to refresh pod config, will retry next iteration", "err", err)
	}

	if k8sAvailable {
		// If a server is gone from the refreshed address list (e.g. its pod was
		// deleted), drop its tracker so stale retry/escalation state does not
		// persist. Guarded by k8sAvailable: the list is authoritative only then.
		for host := range trackers {
			if _, exists := cfg.ServerAddresses[host]; !exists {
				delete(trackers, host)
			}
		}
	}

	// Load current generation secret (if we have one).
	// genSecret may be nil here if CurrentKeySecret is empty — this happens
	// before init has completed (no generation secrets exist in K8s yet).
	// The nil is handled downstream: processServer returns an error for sealed
	// servers and logs warnings for other states.
	var genSecret *baoConfig.GenerationSecret
	if !k8sAvailable {
		genSecret = cfg.GetLoadedGenerationSecret()
		if cfg.CurrentKeySecret == "" || genSecret == nil || len(cfg.ServerAddresses) == 0 {
			slog.Warn("Restricted mode (K8s API unavailable) cannot operate without a confirmed cached generation and server addresses")
			return nil
		}
	} else if cfg.CurrentKeySecret == "" {
		// CurrentKeySecret is empty — re-read the authoritative pointer in case
		// init created it since the last iteration, so a freshly-initialized
		// cluster starts unsealing promptly.
		if err := DiscoverCurrentGeneration(cfg, k8sConfig); err != nil {
			slog.Error("Failed to discover current generation", "err", err)
			return nil
		}
	}

	if k8sAvailable && cfg.CurrentKeySecret != "" {
		var err error
		genSecret, err = cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
		if err != nil {
			slog.Error("Failed to load generation secret from current pointer",
				"name", cfg.CurrentKeySecret, "err", err)
			switch {
			case k8sErrors.IsNotFound(err), k8sErrors.IsInvalid(err):
				genSecret = nil
			case baoConfig.IsTransientK8sError(err):
				k8sAvailable = false
				genSecret = cfg.GetLoadedGenerationSecret()
				if genSecret == nil || len(cfg.ServerAddresses) == 0 {
					slog.Warn("Restricted mode (transient K8s error loading current generation) cannot operate without a confirmed cached generation and server addresses")
					return nil
				}
			default:
				return fmt.Errorf("failed to load current generation: %w", err)
			}
		} else {
			cfg.SetLoadedGenerationSecret(genSecret)
		}
	}

	// Process each server
	activeGeneration := cfg.CurrentKeySecret
	for host := range maps.Keys(cfg.ServerAddresses) {
		tracker, ok := trackers[host]
		if !ok {
			tracker = &UnsealEscalationTracker{Threshold: unsealEscalationThreshold}
			trackers[host] = tracker
		}
		if err := processServer(cfg, host, genSecret, tracker, k8sAvailable); err != nil {
			// Log per-server errors and continue to next server
			slog.Error("Error processing server", "host", host, "err", err)
			continue
		}
		if cfg.CurrentKeySecret != activeGeneration {
			activeGeneration = cfg.CurrentKeySecret
			genSecret = cfg.GetLoadedGenerationSecret()
		}
	}

	// Check for rekey-in-progress and drive to completion
	if k8sAvailable {
		if err := HandleRekeyIfNeeded(cfg, genSecret); err != nil {
			slog.Error("Error checking rekey status", "err", err)
		}
	}

	return nil
}

func recoverGenerationByUnseal(cfg *baoConfig.MonitorConfig, client *clientapi.Client, skipName string) (string, *baoConfig.GenerationSecret, error) {
	gens, err := cfg.ListGenerationSecrets()
	if err != nil {
		return "", nil, fmt.Errorf("recovery: list generations %w", err)
	}
	if len(gens) == 0 {
		return "", nil, errNoGenerationUnsealed
	}

	for i := len(gens) - 1; i >= 0; i-- {
		name := gens[i]
		if name == skipName {
			continue
		}
		gen, err := cfg.LoadGenerationSecret(name)
		if err != nil {
			if k8sErrors.IsNotFound(err) || k8sErrors.IsInvalid(err) {
				slog.Debug("Skipping unusable generation", "generation", name, "err", err)
				continue
			}
			return "", nil, fmt.Errorf("recovery: load generation %q: %w", name, err)
		}

		matched, err := tryGenerationByUnseal(client, name, gen)
		if err != nil {
			return "", nil, err
		}
		if matched {
			return name, gen, nil
		}
		slog.Debug("Generation did not unseal server", "generation", name)
	}

	return "", nil, errNoGenerationUnsealed
}

func tryGenerationByUnseal(client *clientapi.Client, name string, gen *baoConfig.GenerationSecret) (bool, error) {
	if err := UnsealWithGenKeys(client, gen); err != nil {
		if isUnsealCandidateRejection(err) {
			return false, nil
		}
		return false, fmt.Errorf("recovery: generation %v unseal attempt failed: %v", name, err)
	}
	return true, nil
}

func isUnsealCandidateRejection(err error) bool {
	if errors.Is(err, errUnsealCandidateRejected) {
		return true
	}
	var responseErr *clientapi.ResponseError
	return errors.As(err, &responseErr) && responseErr.StatusCode == 400
}

// processServer checks a single server's health and takes appropriate action
// during steady-state monitoring. The main loop only handles unsealing sealed
// servers — initialization and raft join are handled exclusively in startupPhase.
func processServer(cfg *baoConfig.MonitorConfig, host string, genSecret *baoConfig.GenerationSecret, tracker *UnsealEscalationTracker, allowRecovery bool) error {
	if allowRecovery && tracker.pendingName != "" {
		if err := cfg.ActivateGeneration(tracker.pendingName, tracker.pendingSecret); err != nil {
			slog.Warn("Failed to repair current generation pointer", "host", host,
				"generation", tracker.pendingName, "error", err)
		} else {
			genSecret = tracker.pendingSecret
			tracker.pendingName = ""
			tracker.pendingSecret = nil
		}
	}

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

		// Try unseal with the current generation
		if genSecret != nil {
			if err := UnsealWithGenKeys(client, genSecret); err == nil {
				slog.Info("Unseal successful", "host", host)
				tracker.ResetFailures()
				return nil
			} else if !isUnsealCandidateRejection(err) {
				return fmt.Errorf("unseal attempt with current generation failed for host %v: %v", host, err)
			}
			slog.Debug("Unseal failed with current generation", "host", host, "currentGen", cfg.CurrentKeySecret)
		} else {
			slog.Debug("No usable current generation loaded", "host", host, "currentGen", cfg.CurrentKeySecret)
		}

		if !allowRecovery {
			return fmt.Errorf("kubernetes unavailable; historical generation recovery is disabled")
		}

		recoveredGen, recoveredSecret, err := recoverGenerationByUnseal(cfg, client, cfg.CurrentKeySecret)
		if err != nil {
			if !errors.Is(err, errNoGenerationUnsealed) {
				return err
			}

			// No generation unsealed the server.
			escalationTriggered := tracker.IncrementFailure(err.Error())

			if escalationTriggered {
				// Escalation threshold crossed
				slog.Error("Maximum trial reached for unsealing with all known generation keys", "host", host)
			} else if tracker.FailureCount == 1 {
				// Signal a warning on the first try
				slog.Warn("No known generation could unseal the server", "host", host)
			}

			// No logs for trial 2 to threshold - 1
			return nil
		}

		// Recovery succeeded
		previousGen := cfg.CurrentKeySecret
		tracker.ResetFailures()
		if err := cfg.ActivateGeneration(recoveredGen, recoveredSecret); err != nil {
			// Not a fatal error
			tracker.pendingName = recoveredGen
			tracker.pendingSecret = recoveredSecret
			slog.Error("Failed to update current generation pointer after recovery",
				"host", host, "recovered generation", recoveredGen, "err", err)
		} else {
			slog.Info("Server unsealed via recovery and pointer updated",
				"host", host, "old generation", previousGen, "newGen", recoveredGen)
		}

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
		tracker.ResetFailures()
	}

	return nil
}

// runInitAndStore initializes an OpenBao server and stores the result as a
// new immutable generation secret.
func runInitAndStore(cfg *baoConfig.MonitorConfig, client *clientapi.Client, host string) error {
	slog.Info("Initializing OpenBao server",
		"host", host, "shares", secretShares, "threshold", secretThreshold)

	// Pre-flight: verify K8s connectivity before calling /sys/init.
	// Once init is called, the keys only exist in the response — if we can't
	// store them to K8s afterward, they're lost.
	_, err := cfg.ListGenerationSecrets()
	if err != nil {
		return fmt.Errorf("pre-flight K8s check failed (cannot list secrets): %w", err)
	}

	opts := &clientapi.InitRequest{
		SecretShares:    secretShares,
		SecretThreshold: secretThreshold,
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

	// Store + verify using shared helper (retry on transient K8s failures)
	genName, err := cfg.StoreAndVerifyGeneration(genSecret, secretShares)
	if err != nil {
		return err
	}

	reloaded, err := cfg.LoadGenerationSecret(genName)
	if err != nil {
		return fmt.Errorf("pre-unseal validation failed for %v, %v", genName, err)
	}

	if err := cfg.ActivateGeneration(genName, reloaded); err != nil {
		return err
	}

	slog.Info("Init complete, generation secret stored",
		"host", host, "generation", genName)

	// Unseal the freshly initialized server
	slog.Info("Unsealing freshly initialized server", "host", host)
	if err := UnsealWithGenKeys(client, reloaded); err != nil {
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

	if len(genSecret.Keys) == 0 {
		return fmt.Errorf("generation holds no key shards: %w", errUnsealCandidateRejected)
	}
	if client == nil {
		return fmt.Errorf("unseal client is nil")
	}

	status, err := client.Sys().ResetUnsealProcess()
	if err != nil {
		return err
	}
	if status == nil || !status.Sealed || status.Progress != 0 || status.T < 1 {
		return fmt.Errorf("cannot confirm a fresh unseal attempt")
	}
	keysNeeded := status.T

	if len(genSecret.Keys) < keysNeeded {
		return fmt.Errorf("generation has %d shard(s) but server requires %d: %w", len(genSecret.Keys), keysNeeded, errUnsealCandidateRejected)
	}

	for i := 0; i < keysNeeded; i++ {
		result, err := client.Sys().Unseal(genSecret.Keys[i])
		if err != nil {
			return fmt.Errorf("unseal failed on key %d: %w", i, err)
		}
		if result == nil {
			return fmt.Errorf("unseal returned no status for key %v", i)
		}
		if !result.Sealed {
			if i+1 < keysNeeded {
				return fmt.Errorf("server became unsealed before this attempt supplied the threshold; candidate is not proven")
			}
			slog.Debug("Server unsealed", "keysUsed", i+1)
			return nil
		}
		slog.Debug("Unseal progress", "submitted", i+1, "threshold", result.T, "progress", result.Progress)
	}

	return fmt.Errorf("submitted %d shard(s) but server did not unseal: %w", keysNeeded, errUnsealCandidateRejected)
}

func init() {
	runCmd.Flags().IntVar(&waitInterval, "waitInterval", 5, "wait time in seconds between each check iteration")
	runCmd.Flags().IntVar(&secretShares, "secret-shares", 5, "The number of shares that the root key will split to")
	runCmd.Flags().IntVar(&secretThreshold, "secret-threshold", 3, "The number of shares required to unseal")
	RootCmd.AddCommand(runCmd)
}
