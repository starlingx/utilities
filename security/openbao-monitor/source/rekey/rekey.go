//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package rekey

import (
	"fmt"
	"log/slog"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	clientapi "github.com/openbao/openbao/api/v2"
)

// State represents the rekey process state machine states.
type State int

const (
	StateIdle       State = iota // No rekey in progress
	StateInitiated               // /sys/rekey/init called, waiting for shards
	StateInProgress              // Shares being submitted
	StateComplete                // New keys received from server
	StateStored                  // New generation secret written to k8s
	StateVerified                // Verification complete, server applied the rekey
)

// String returns the human-readable name of the state.
func (s State) String() string {
	switch s {
	case StateIdle:
		return "Idle"
	case StateInitiated:
		return "Initiated"
	case StateInProgress:
		return "InProgress"
	case StateComplete:
		return "Complete"
	case StateStored:
		return "Stored"
	case StateVerified:
		return "Verified"
	default:
		return "Unknown"
	}
}

// SysAPI abstracts the OpenBao sys API methods used by the rekey process.
// This enables unit testing with mock implementations.
type SysAPI interface {
	RekeyInit(config *clientapi.RekeyInitRequest) (*clientapi.RekeyStatusResponse, error)
	RekeyStatus() (*clientapi.RekeyStatusResponse, error)
	RekeyUpdate(shard, nonce string) (*clientapi.RekeyUpdateResponse, error)
	RekeyCancel() error
	RekeyVerificationUpdate(shard, nonce string) (*clientapi.RekeyVerificationUpdateResponse, error)
	RekeyVerificationStatus() (*clientapi.RekeyVerificationStatusResponse, error)
}

// ConfigLoader abstracts the config operations needed by the rekey process.
// This enables unit testing without real Kubernetes connections.
type ConfigLoader interface {
	LoadGenerationSecret(secretName string) (*baoConfig.GenerationSecret, error)
	NextGenerationName() (string, error)
	StoreAndVerifyGenerationAtName(genName string, secret *baoConfig.GenerationSecret, minShares, maxAttempts int) error
	GetCurrentRootToken() string
	GetCurrentKeySecret() string
}

// RekeyProcess manages the rekey lifecycle as a deterministic state machine.
type RekeyProcess struct {
	Config            ConfigLoader
	State             State
	NewShares         int
	Threshold         int
	Nonce             string // Stored nonce from rekey init
	VerificationNonce string // Stored nonce from rekey update (for verification step)

	// StoredGenName is the name of the generation secret written by StoreResultWithRetry.
	// The caller uses this to advance the authoritative current-key pointer
	// after server-side verification succeeds — the pointer must not advance
	// until the rekey is verified.
	StoredGenName string
}

// Start initiates the rekey process on the server by calling /sys/rekey/init.
// Transitions state from Idle to StateInitiated on success.
func (r *RekeyProcess) Start(sys SysAPI) error {
	slog.Debug("Starting rekey process", "shares", r.NewShares, "threshold", r.Threshold)

	// Avoid starting rekey if root token does not exist in configuration,
	// since we intend to store it in the generation secret.
	// This sanity issue should omit rekey before rekey starts.
	if r.Config.GetCurrentRootToken() == "" {
		return fmt.Errorf("current root token is empty; cannot start rekey without a root token to preserve")
	}

	initResp, err := sys.RekeyInit(&clientapi.RekeyInitRequest{
		SecretShares:        r.NewShares,
		SecretThreshold:     r.Threshold,
		RequireVerification: true,
	})
	if err != nil {
		return fmt.Errorf("failed to initiate rekey: %w", err)
	}
	if initResp == nil {
		return fmt.Errorf("rekey init response is nil")
	}
	if !initResp.Started {
		return fmt.Errorf("rekey init response indicates not started")
	}

	if !initResp.VerificationRequired {
		// Safety check: we always request verification. If the server does not
		// confirm it, abort rather than proceeding with an unverifiable rekey.
		return r.abortAndConfirm(sys, fmt.Errorf("server did not confirm verification_required; aborting rekey to prevent unverifiable key rotation"))
	}

	r.Nonce = initResp.Nonce
	r.State = StateInitiated
	slog.Info("Rekey initiated", "nonce", r.Nonce, "requireVerification", true)
	return nil
}

// SubmitShards loads current generation keys and submits threshold keys
// sequentially to the rekey operation. On error, it cancels the rekey to
// avoid leaving the server in a stuck state.
// Returns the final RekeyUpdateResponse when complete.
func (r *RekeyProcess) SubmitShards(sys SysAPI) (*clientapi.RekeyUpdateResponse, error) {
	slog.Debug("Submitting shards for rekey", "threshold", r.Threshold)

	// Load the current generation's keys
	genSecret, err := r.Config.LoadGenerationSecret(r.Config.GetCurrentKeySecret())
	if err != nil {
		return nil, r.abortAndConfirm(sys, fmt.Errorf("failed to load generation secret for rekey: %w", err))
	}

	status, err := sys.RekeyStatus()
	if err != nil {
		return nil, r.abortAndConfirm(sys, err)
	}
	if status == nil || status.Required < 1 {
		return nil, r.abortAndConfirm(sys, fmt.Errorf("rekey status has no required key count"))
	}
	required := status.Required
	progress := status.Progress
	if progress < 0 || progress >= required {
		return nil, r.abortAndConfirm(sys, fmt.Errorf("invalid rekey progress %d for required key count %d", progress, required))
	}

	r.State = StateInProgress

	// Pre-check: ensure we have enough keys before starting submission.
	// Failing mid-loop after partial submission would leave the server in a
	// harder-to-recover state.
	if len(genSecret.Keys) < required {
		return nil, r.abortAndConfirm(sys, fmt.Errorf("not enough keys: need %d, have %d", r.Threshold, len(genSecret.Keys)))
	}

	// Submit threshold keys sequentially
	var finalResp *clientapi.RekeyUpdateResponse
	for i := progress; i < required; i++ {
		resp, err := sys.RekeyUpdate(genSecret.Keys[i], r.Nonce)
		if err != nil {
			return nil, r.abortAndConfirm(sys, fmt.Errorf("failed to submit shard %d during rekey: %w", i, err))
		}

		if resp == nil {
			return nil, r.abortAndConfirm(sys, fmt.Errorf("rekey shard %d returned a nil response", i))
		}

		if resp.Complete {
			finalResp = resp
			break
		}
	}

	if finalResp == nil || !finalResp.Complete {
		return nil, r.abortAndConfirm(sys, fmt.Errorf("rekey did not complete after submitting %d threshold keys", r.Threshold))
	}

	// Capture the verification nonce for the verify step
	if finalResp.VerificationRequired {
		r.VerificationNonce = finalResp.VerificationNonce
		slog.Debug("Verification required", "verificationNonce", r.VerificationNonce)
	}

	r.State = StateComplete
	slog.Info("Rekey shard submission complete, new keys received",
		"verificationRequired", finalResp.VerificationRequired)
	return finalResp, nil
}

func (r *RekeyProcess) storeResult(response *clientapi.RekeyUpdateResponse, maxAttempts int) error {
	if response == nil {
		return fmt.Errorf("cannot store nil rekey response")
	}

	slog.Debug("Storing rekey result as new generation secret")

	// Preserve root token from the current generation — rekey does not change it
	currentRootToken := r.Config.GetCurrentRootToken()
	if currentRootToken == "" {
		return fmt.Errorf("current root token is empty, cannot preserve in new generation")
	}

	// Assemble the new generation secret
	newSecret := &baoConfig.GenerationSecret{
		Keys:       response.Keys,
		KeysBase64: response.KeysB64,
		RootToken:  currentRootToken,
	}

	// Compute the next generation name
	nextGen, err := r.Config.NextGenerationName()
	if err != nil {
		return fmt.Errorf("failed to compute next generation name: %w", err)
	}

	err = r.Config.StoreAndVerifyGenerationAtName(nextGen, newSecret, r.NewShares, maxAttempts)
	if err != nil {
		return fmt.Errorf("failed to store new generation secret %s: %w", nextGen, err)
	}

	// Record the stored generation name so the caller can advance the
	// authoritative pointer after verification. The pointer itself is NOT
	// updated here — only after the server confirms the rekey via Verify.
	r.StoredGenName = nextGen

	r.State = StateStored
	slog.Info("Rekey generation stored", "name", nextGen, "verificationRequired", response.VerificationRequired)
	return nil
}

// Verify completes the rekey verification step by submitting threshold new keys
// to the server. This confirms the client received the correct keys and triggers
// the server to actually apply the new master key.
func (r *RekeyProcess) Verify(sys SysAPI, response *clientapi.RekeyUpdateResponse) error {
	if response == nil {
		return fmt.Errorf("cannot verify with nil rekey response")
	}
	if r.VerificationNonce == "" {
		return fmt.Errorf("no verification nonce available; was RequireVerification set?")
	}
	if len(response.Keys) < r.Threshold {
		return fmt.Errorf("not enough new keys for verification: need %d, have %d",
			r.Threshold, len(response.Keys))
	}

	slog.Debug("Submitting new keys for rekey verification",
		"threshold", r.Threshold, "verificationNonce", r.VerificationNonce)

	// Submit threshold new keys to verify we received them correctly
	for i := 0; i < r.Threshold; i++ {
		verifyResp, err := sys.RekeyVerificationUpdate(response.Keys[i], r.VerificationNonce)
		if err != nil {
			return fmt.Errorf("rekey verification failed on shard %d: %w", i, err)
		}

		if verifyResp != nil && verifyResp.Complete {
			r.State = StateVerified
			slog.Info("Rekey verification complete, server has applied new master key")
			return nil
		}
	}

	// If we submitted threshold keys and didn't get Complete, something is wrong
	return fmt.Errorf("rekey verification did not complete after submitting %d keys", r.Threshold)
}

// CheckInProgress queries the rekey status on the server and returns true
// if a rekey operation is currently in progress.
func (r *RekeyProcess) CheckInProgress(sys SysAPI) (bool, error) {
	status, err := sys.RekeyStatus()
	if err != nil {
		return false, fmt.Errorf("failed to check rekey status: %w", err)
	}

	if status == nil {
		return false, fmt.Errorf("nil rekey status response")
	}

	if status.Started {
		return true, nil
	}

	verification, err := sys.RekeyVerificationStatus()
	if err != nil {
		return false, fmt.Errorf("failed to check rekey verification status: %w", err)
	}
	if verification == nil {
		return false, fmt.Errorf("nil rekey verification status response")
	}
	return verification.Started, nil
}

func (r *RekeyProcess) abortAndConfirm(sys SysAPI, cause error) error {
	if err := r.CancelAndConfirm(sys); err != nil {
		return fmt.Errorf("rekey cancellation for issue '%v' failed: %w", cause, err)
	}
	return fmt.Errorf("rekey cancelled. reason: %v", cause)
}

func (r *RekeyProcess) CancelAndConfirm(sys SysAPI) error {
	if err := sys.RekeyCancel(); err != nil {
		return fmt.Errorf("failed to cancel rekey: %w", err)
	}

	inProgress, err := r.CheckInProgress(sys)
	if err != nil {
		return fmt.Errorf("rekey cancel outcome is unknown: %w", err)
	}
	if inProgress {
		return fmt.Errorf("rekey remains in progress after cancellation")
	}
	r.State = StateIdle
	return nil
}

func (r *RekeyProcess) CancelInProgress(sys SysAPI) error {
	inProgress, err := r.CheckInProgress(sys)
	if err != nil {
		return err
	}
	if !inProgress {
		return nil
	}
	return r.CancelAndConfirm(sys)
}

// Cancel aborts a rekey operation in progress on the server and resets
// the process state to Idle.
func (r *RekeyProcess) Cancel(sys SysAPI) error {
	slog.Debug("Cancelling rekey process")

	err := sys.RekeyCancel()
	if err != nil {
		return fmt.Errorf("failed to cancel rekey: %w", err)
	}

	r.State = StateIdle
	slog.Info("Rekey cancelled, state reset to Idle")
	return nil
}

// StoreResultWithRetry persists the rekey result with up to maxAttempts retries
// on transient failures. After successful store, it re-reads the secret from
// Kubernetes and verifies key-by-key that the stored data matches the response.
//
// This guards against:
//   - Transient K8s API failures (retry with exponential backoff)
//   - Silent storage corruption (read-back comparison)
func (r *RekeyProcess) StoreResultWithRetry(response *clientapi.RekeyUpdateResponse, maxAttempts int) error {
	return r.storeResult(response, maxAttempts)
}

// VerifyWithServer completes the server-side rekey verification step if
// verification was required. Returns nil without action if the response
// does not require verification.
func (r *RekeyProcess) VerifyWithServer(sys SysAPI, response *clientapi.RekeyUpdateResponse) error {
	if response == nil {
		return fmt.Errorf("cannot verify nil rekey response")
	}
	if !response.VerificationRequired {
		return nil
	}
	return r.Verify(sys, response)
}
