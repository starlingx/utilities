//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package rekey_test

import (
	"fmt"
	"testing"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	clientapi "github.com/openbao/openbao/api/v2"
)

// --- Mock implementations ---

// mockSysAPI provides a configurable mock for the SysAPI interface.
type mockSysAPI struct {
	// RekeyInit behavior
	rekeyInitResp *clientapi.RekeyStatusResponse
	rekeyInitErr  error

	// RekeyStatus behavior
	rekeyStatusResp *clientapi.RekeyStatusResponse
	rekeyStatusErr  error

	// RekeyUpdate behavior
	rekeyUpdateResponses []*clientapi.RekeyUpdateResponse
	rekeyUpdateErrs      []error
	rekeyUpdateCallCount int

	// RekeyCancel behavior
	rekeyCancelErr   error
	rekeyCancelCalls int

	// RekeyVerificationUpdate behavior
	rekeyVerifyResponses []*clientapi.RekeyVerificationUpdateResponse
	rekeyVerifyErrs      []error
	rekeyVerifyCallCount int

	// RekeyVerificationCancel behavior
	rekeyVerifyCancelErr   error
	rekeyVerifyCancelCalls int
}

func (m *mockSysAPI) RekeyInit(config *clientapi.RekeyInitRequest) (*clientapi.RekeyStatusResponse, error) {
	return m.rekeyInitResp, m.rekeyInitErr
}

func (m *mockSysAPI) RekeyStatus() (*clientapi.RekeyStatusResponse, error) {
	return m.rekeyStatusResp, m.rekeyStatusErr
}

func (m *mockSysAPI) RekeyUpdate(shard, nonce string) (*clientapi.RekeyUpdateResponse, error) {
	idx := m.rekeyUpdateCallCount
	m.rekeyUpdateCallCount++

	if idx < len(m.rekeyUpdateErrs) && m.rekeyUpdateErrs[idx] != nil {
		return nil, m.rekeyUpdateErrs[idx]
	}
	if idx < len(m.rekeyUpdateResponses) {
		return m.rekeyUpdateResponses[idx], nil
	}
	return nil, fmt.Errorf("unexpected RekeyUpdate call %d", idx)
}

func (m *mockSysAPI) RekeyCancel() error {
	m.rekeyCancelCalls++
	return m.rekeyCancelErr
}

func (m *mockSysAPI) RekeyVerificationUpdate(shard, nonce string) (*clientapi.RekeyVerificationUpdateResponse, error) {
	idx := m.rekeyVerifyCallCount
	m.rekeyVerifyCallCount++

	if idx < len(m.rekeyVerifyErrs) && m.rekeyVerifyErrs[idx] != nil {
		return nil, m.rekeyVerifyErrs[idx]
	}
	if idx < len(m.rekeyVerifyResponses) {
		return m.rekeyVerifyResponses[idx], nil
	}
	return nil, fmt.Errorf("unexpected RekeyVerificationUpdate call %d", idx)
}

func (m *mockSysAPI) RekeyVerificationCancel() error {
	m.rekeyVerifyCancelCalls++
	return m.rekeyVerifyCancelErr
}

// mockConfigLoader provides a configurable mock for the ConfigLoader interface.
type mockConfigLoader struct {
	// LoadGenerationSecret behavior
	loadedSecret *baoConfig.GenerationSecret
	loadErr      error

	// NextGenerationName behavior
	nextGenName string
	nextGenErr  error

	// StoreGenerationSecret behavior
	storeErr      error
	storedGenName string
	storedSecret  *baoConfig.GenerationSecret
	storeCalls    int

	// GetCurrentRootToken behavior
	currentRootToken string

	// GetCurrentKeySecret behavior
	currentKeySecret string
}

func (m *mockConfigLoader) LoadGenerationSecret(secretName string) (*baoConfig.GenerationSecret, error) {
	return m.loadedSecret, m.loadErr
}

func (m *mockConfigLoader) NextGenerationName() (string, error) {
	return m.nextGenName, m.nextGenErr
}

func (m *mockConfigLoader) StoreGenerationSecret(genName string, secret *baoConfig.GenerationSecret) error {
	m.storeCalls++
	m.storedGenName = genName
	m.storedSecret = secret
	return m.storeErr
}

func (m *mockConfigLoader) GetCurrentRootToken() string {
	return m.currentRootToken
}

func (m *mockConfigLoader) GetCurrentKeySecret() string {
	return m.currentKeySecret
}

// --- Helper to create a standard test generation secret ---

func testGenerationSecret() *baoConfig.GenerationSecret {
	return &baoConfig.GenerationSecret{
		Keys:       []string{"key0", "key1", "key2", "key3", "key4"},
		KeysBase64: []string{"a2V5MA==", "a2V5MQ==", "a2V5Mg==", "a2V5Mw==", "a2V5NA=="},
		RootToken:  "s.root-token-abc123",
	}
}

// --- Test: Happy path (Start → SubmitShards → StoreResult → Stored) ---

func TestRekeyHappyPath(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started:              true,
			Nonce:                "test-nonce-123",
			N:                    5,
			T:                    3,
			VerificationRequired: true,
		},
		rekeyUpdateResponses: []*clientapi.RekeyUpdateResponse{
			{Complete: false, Nonce: "test-nonce-123"},
			{Complete: false, Nonce: "test-nonce-123"},
			{
				Complete: true,
				Nonce:    "test-nonce-123",
				Keys:     []string{"newkey0", "newkey1", "newkey2", "newkey3", "newkey4"},
				KeysB64:  []string{"bmV3a2V5MA==", "bmV3a2V5MQ==", "bmV3a2V5Mg==", "bmV3a2V5Mw==", "bmV3a2V5NA=="},
			},
		},
	}

	mockCfg := &mockConfigLoader{
		loadedSecret:     testGenerationSecret(),
		currentRootToken: "s.root-token-abc123",
		nextGenName:      "openbao-unseal-gen-002",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Step 1: Start
	err := proc.Start(mockSys)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}
	if proc.State != rekey.StateInitiated {
		t.Errorf("expected rekey.StateInitiated, got %v", proc.State)
	}
	if proc.Nonce != "test-nonce-123" {
		t.Errorf("expected nonce 'test-nonce-123', got %q", proc.Nonce)
	}

	// Step 2: SubmitShards
	resp, err := proc.SubmitShards(mockSys)
	if err != nil {
		t.Fatalf("SubmitShards failed: %v", err)
	}
	if proc.State != rekey.StateComplete {
		t.Errorf("expected rekey.StateComplete, got %v", proc.State)
	}
	if !resp.Complete {
		t.Error("expected response.Complete to be true")
	}
	if len(resp.Keys) != 5 {
		t.Errorf("expected 5 new keys, got %d", len(resp.Keys))
	}

	// Step 3: StoreResult
	err = proc.StoreResult(resp)
	if err != nil {
		t.Fatalf("StoreResult failed: %v", err)
	}
	if proc.State != rekey.StateStored {
		t.Errorf("expected rekey.StateStored, got %v", proc.State)
	}

	// Verify stored secret
	if mockCfg.storedGenName != "openbao-unseal-gen-002" {
		t.Errorf("expected stored gen name 'openbao-unseal-gen-002', got %q", mockCfg.storedGenName)
	}
	if mockCfg.storedSecret == nil {
		t.Fatal("expected stored secret to be non-nil")
	}
	if mockCfg.storedSecret.RootToken != "s.root-token-abc123" {
		t.Errorf("expected root token preserved, got %q", mockCfg.storedSecret.RootToken)
	}
	if len(mockCfg.storedSecret.Keys) != 5 {
		t.Errorf("expected 5 keys stored, got %d", len(mockCfg.storedSecret.Keys))
	}
}

// --- Test: Cancel on shard submission error ---

func TestRekey_CancelOnSubmitError(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started:              true,
			Nonce:                "error-nonce",
			N:                    5,
			T:                    3,
			VerificationRequired: true,
		},
		// First update succeeds, second fails
		rekeyUpdateResponses: []*clientapi.RekeyUpdateResponse{
			{Complete: false, Nonce: "error-nonce"},
		},
		rekeyUpdateErrs: []error{
			nil,
			fmt.Errorf("server sealed: connection refused"),
		},
	}

	mockCfg := &mockConfigLoader{
		loadedSecret:     testGenerationSecret(),
		currentRootToken: "s.root-token-abc123",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Start succeeds
	err := proc.Start(mockSys)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}

	// SubmitShards should fail and cancel
	_, err = proc.SubmitShards(mockSys)
	if err == nil {
		t.Fatal("expected SubmitShards to fail")
	}

	// State should be reset to Idle after cancel
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle after cancel, got %v", proc.State)
	}

	// Verify cancel was called
	if mockSys.rekeyCancelCalls != 1 {
		t.Errorf("expected 1 cancel call, got %d", mockSys.rekeyCancelCalls)
	}
}

// --- Test: Cancel on LoadGenerationSecret error ---

func TestRekey_CancelOnLoadError(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started:              true,
			Nonce:                "load-err-nonce",
			N:                    5,
			T:                    3,
			VerificationRequired: true,
		},
	}

	mockCfg := &mockConfigLoader{
		loadErr:          fmt.Errorf("generation secret not found"),
		currentRootToken: "s.root-token-abc123",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Start succeeds
	err := proc.Start(mockSys)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}

	// SubmitShards fails due to load error, should cancel
	_, err = proc.SubmitShards(mockSys)
	if err == nil {
		t.Fatal("expected SubmitShards to fail due to load error")
	}

	// State reset to Idle
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle, got %v", proc.State)
	}

	// Cancel was called
	if mockSys.rekeyCancelCalls != 1 {
		t.Errorf("expected 1 cancel call, got %d", mockSys.rekeyCancelCalls)
	}
}

// --- Test: CheckInProgress returns correct status ---

func TestRekeyCheckInProgress(t *testing.T) {
	tests := []struct {
		name     string
		started  bool
		err      error
		wantBool bool
		wantErr  bool
	}{
		{
			name:     "rekey in progress",
			started:  true,
			wantBool: true,
		},
		{
			name:     "no rekey in progress",
			started:  false,
			wantBool: false,
		},
		{
			name:    "status check error",
			err:     fmt.Errorf("connection refused"),
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			mockSys := &mockSysAPI{
				rekeyStatusResp: &clientapi.RekeyStatusResponse{
					Started: tt.started,
				},
				rekeyStatusErr: tt.err,
			}

			proc := &rekey.RekeyProcess{
				Config: &mockConfigLoader{},
				State:  rekey.StateIdle,
			}

			inProgress, err := proc.CheckInProgress(mockSys)
			if tt.wantErr {
				if err == nil {
					t.Fatal("expected error, got nil")
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if inProgress != tt.wantBool {
				t.Errorf("expected inProgress=%v, got %v", tt.wantBool, inProgress)
			}
		})
	}
}

// --- Test: Cancel resets state ---

func TestRekeyCancel(t *testing.T) {
	mockSys := &mockSysAPI{}

	proc := &rekey.RekeyProcess{
		Config: &mockConfigLoader{},
		State:  rekey.StateInitiated,
		Nonce:  "some-nonce",
	}

	err := proc.Cancel(mockSys)
	if err != nil {
		t.Fatalf("Cancel failed: %v", err)
	}
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle after cancel, got %v", proc.State)
	}
	if mockSys.rekeyCancelCalls != 1 {
		t.Errorf("expected 1 cancel call, got %d", mockSys.rekeyCancelCalls)
	}
}

// --- Test: Cancel returns error from server ---

func TestRekeyCancel_ServerError(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyCancelErr: fmt.Errorf("server unavailable"),
	}

	proc := &rekey.RekeyProcess{
		Config: &mockConfigLoader{},
		State:  rekey.StateInProgress,
	}

	err := proc.Cancel(mockSys)
	if err == nil {
		t.Fatal("expected error from cancel")
	}
	// State should NOT be reset on cancel failure
	if proc.State != rekey.StateInProgress {
		t.Errorf("expected rekey.StateInProgress (unchanged), got %v", proc.State)
	}
}

// --- Test: Start fails when server returns error ---

func TestRekeyStart_ServerError(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyInitErr: fmt.Errorf("server sealed"),
	}

	proc := &rekey.RekeyProcess{
		Config:    &mockConfigLoader{},
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	err := proc.Start(mockSys)
	if err == nil {
		t.Fatal("expected Start to fail")
	}
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle (unchanged), got %v", proc.State)
	}
}

// --- Test: Start fails when response indicates not started ---

func TestRekeyStart_NotStarted(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started: false,
		},
	}

	proc := &rekey.RekeyProcess{
		Config:    &mockConfigLoader{},
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	err := proc.Start(mockSys)
	if err == nil {
		t.Fatal("expected Start to fail when not started")
	}
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle (unchanged), got %v", proc.State)
	}
}

// --- Test: StoreResult with nil response ---

func TestRekeyStoreResult_NilResponse(t *testing.T) {
	proc := &rekey.RekeyProcess{
		Config: &mockConfigLoader{currentRootToken: "token"},
		State:  rekey.StateComplete,
	}

	err := proc.StoreResult(nil)
	if err == nil {
		t.Fatal("expected error for nil response")
	}
}

// --- Test: StoreResult with empty root token ---

func TestRekeyStoreResult_EmptyRootToken(t *testing.T) {
	mockCfg := &mockConfigLoader{
		currentRootToken: "", // empty
	}

	proc := &rekey.RekeyProcess{
		Config: mockCfg,
		State:  rekey.StateComplete,
	}

	resp := &clientapi.RekeyUpdateResponse{
		Complete: true,
		Keys:     []string{"k0", "k1", "k2", "k3", "k4"},
		KeysB64:  []string{"b0", "b1", "b2", "b3", "b4"},
	}

	err := proc.StoreResult(resp)
	if err == nil {
		t.Fatal("expected error when root token is empty")
	}
}

// --- Test: Simulated server sealed mid-rekey ---

func TestRekey_ServerSealedMidRekey(t *testing.T) {
	// Simulates: Start succeeds, first shard submitted OK, then server becomes sealed
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started:              true,
			Nonce:                "sealed-nonce",
			N:                    5,
			T:                    3,
			VerificationRequired: true,
		},
		rekeyUpdateResponses: []*clientapi.RekeyUpdateResponse{
			{Complete: false, Nonce: "sealed-nonce"},
		},
		rekeyUpdateErrs: []error{
			nil,
			fmt.Errorf("server is sealed"),
		},
	}

	mockCfg := &mockConfigLoader{
		loadedSecret:     testGenerationSecret(),
		currentRootToken: "s.root-token-abc123",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Start
	err := proc.Start(mockSys)
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}

	// SubmitShards should fail due to sealed server
	_, err = proc.SubmitShards(mockSys)
	if err == nil {
		t.Fatal("expected SubmitShards to fail due to sealed server")
	}

	// Verify cancel was attempted and state reset
	if proc.State != rekey.StateIdle {
		t.Errorf("expected rekey.StateIdle after sealed-mid-rekey, got %v", proc.State)
	}
	if mockSys.rekeyCancelCalls != 1 {
		t.Errorf("expected 1 cancel call, got %d", mockSys.rekeyCancelCalls)
	}
}

// --- Test: Interrupted resume (CheckInProgress detects rekey) ---

func TestRekey_InterruptedResume(t *testing.T) {
	// Simulates: pod restarts, CheckInProgress finds rekey in progress,
	// then SubmitShards completes successfully on threshold=3
	mockSys := &mockSysAPI{
		rekeyStatusResp: &clientapi.RekeyStatusResponse{
			Started:  true,
			Nonce:    "resume-nonce",
			N:        5,
			T:        3,
			Progress: 0, // No shards submitted yet (fresh restart)
			Required: 3,
		},
		rekeyUpdateResponses: []*clientapi.RekeyUpdateResponse{
			{Complete: false, Nonce: "resume-nonce"},
			{Complete: false, Nonce: "resume-nonce"},
			{
				Complete: true,
				Nonce:    "resume-nonce",
				Keys:     []string{"rk0", "rk1", "rk2", "rk3", "rk4"},
				KeysB64:  []string{"cmswMA==", "cmswMQ==", "cmswMg==", "cmswMw==", "cmswNA=="},
			},
		},
	}

	mockCfg := &mockConfigLoader{
		loadedSecret:     testGenerationSecret(),
		currentRootToken: "s.root-token-abc123",
		nextGenName:      "openbao-unseal-gen-003",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Step 1: Detect in-progress rekey (simulates restart detection)
	inProgress, err := proc.CheckInProgress(mockSys)
	if err != nil {
		t.Fatalf("CheckInProgress failed: %v", err)
	}
	if !inProgress {
		t.Fatal("expected rekey in progress")
	}

	// Simulate setting the nonce from the status response (as the run loop would do)
	proc.Nonce = mockSys.rekeyStatusResp.Nonce
	proc.State = rekey.StateInProgress

	// Step 2: Submit shards to resume
	resp, err := proc.SubmitShards(mockSys)
	if err != nil {
		t.Fatalf("SubmitShards failed on resume: %v", err)
	}
	if !resp.Complete {
		t.Error("expected rekey to complete")
	}
	if proc.State != rekey.StateComplete {
		t.Errorf("expected rekey.StateComplete, got %v", proc.State)
	}

	// Step 3: Store result
	err = proc.StoreResult(resp)
	if err != nil {
		t.Fatalf("StoreResult failed: %v", err)
	}
	if proc.State != rekey.StateStored {
		t.Errorf("expected rekey.StateStored, got %v", proc.State)
	}
	if mockCfg.storedGenName != "openbao-unseal-gen-003" {
		t.Errorf("expected gen name 'openbao-unseal-gen-003', got %q", mockCfg.storedGenName)
	}
}

// --- Test: State String representation ---

func TestStateString(t *testing.T) {
	tests := []struct {
		state    rekey.State
		expected string
	}{
		{rekey.StateIdle, "Idle"},
		{rekey.StateInitiated, "Initiated"},
		{rekey.StateInProgress, "InProgress"},
		{rekey.StateComplete, "Complete"},
		{rekey.StateStored, "Stored"},
		{rekey.State(99), "Unknown"},
	}

	for _, tt := range tests {
		t.Run(tt.expected, func(t *testing.T) {
			if got := tt.state.String(); got != tt.expected {
				t.Errorf("State(%d).String() = %q, want %q", tt.state, got, tt.expected)
			}
		})
	}
}

// --- Tests for Verify() ---

func TestRekeyVerify_HappyPath(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyVerifyResponses: []*clientapi.RekeyVerificationUpdateResponse{
			{Complete: false, Nonce: "verify-nonce-1"},
			{Complete: false, Nonce: "verify-nonce-1"},
			{Complete: true, Nonce: "verify-nonce-1"},
		},
	}

	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "verify-nonce-1",
	}

	response := &clientapi.RekeyUpdateResponse{
		Complete:             true,
		Keys:                 []string{"newkey0", "newkey1", "newkey2", "newkey3", "newkey4"},
		KeysB64:              []string{"bk0", "bk1", "bk2", "bk3", "bk4"},
		VerificationRequired: true,
		VerificationNonce:    "verify-nonce-1",
	}

	err := proc.Verify(mockSys, response)
	if err != nil {
		t.Fatalf("Verify() returned unexpected error: %v", err)
	}
	if proc.State != rekey.StateVerified {
		t.Errorf("expected StateVerified, got %v", proc.State)
	}
	if mockSys.rekeyVerifyCallCount != 3 {
		t.Errorf("expected 3 verification update calls, got %d", mockSys.rekeyVerifyCallCount)
	}
}

func TestRekeyVerify_NilResponse(t *testing.T) {
	mockSys := &mockSysAPI{}
	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "verify-nonce-1",
	}

	err := proc.Verify(mockSys, nil)
	if err == nil {
		t.Fatal("expected error for nil response, got nil")
	}
}

func TestRekeyVerify_NoVerificationNonce(t *testing.T) {
	mockSys := &mockSysAPI{}
	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "", // empty
	}

	response := &clientapi.RekeyUpdateResponse{
		Complete: true,
		Keys:     []string{"k0", "k1", "k2", "k3", "k4"},
	}

	err := proc.Verify(mockSys, response)
	if err == nil {
		t.Fatal("expected error for empty verification nonce, got nil")
	}
}

func TestRekeyVerify_InsufficientKeys(t *testing.T) {
	mockSys := &mockSysAPI{}
	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "verify-nonce-1",
	}

	response := &clientapi.RekeyUpdateResponse{
		Complete: true,
		Keys:     []string{"k0", "k1"}, // only 2, need 3
	}

	err := proc.Verify(mockSys, response)
	if err == nil {
		t.Fatal("expected error for insufficient keys, got nil")
	}
}

func TestRekeyVerify_APIError_CancelsVerification(t *testing.T) {
	mockSys := &mockSysAPI{
		rekeyVerifyResponses: []*clientapi.RekeyVerificationUpdateResponse{
			{Complete: false, Nonce: "verify-nonce-1"},
		},
		rekeyVerifyErrs: []error{
			nil,
			fmt.Errorf("verification API error"),
		},
	}

	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "verify-nonce-1",
	}

	response := &clientapi.RekeyUpdateResponse{
		Complete: true,
		Keys:     []string{"k0", "k1", "k2", "k3", "k4"},
	}

	err := proc.Verify(mockSys, response)
	if err == nil {
		t.Fatal("expected error from verification API failure, got nil")
	}
	if mockSys.rekeyVerifyCancelCalls != 1 {
		t.Errorf("expected 1 verification cancel call, got %d", mockSys.rekeyVerifyCancelCalls)
	}
}

func TestRekeyVerify_DoesNotComplete(t *testing.T) {
	// All responses say not complete — should cancel
	mockSys := &mockSysAPI{
		rekeyVerifyResponses: []*clientapi.RekeyVerificationUpdateResponse{
			{Complete: false, Nonce: "verify-nonce-1"},
			{Complete: false, Nonce: "verify-nonce-1"},
			{Complete: false, Nonce: "verify-nonce-1"},
		},
	}

	proc := &rekey.RekeyProcess{
		State:             rekey.StateStored,
		Threshold:         3,
		VerificationNonce: "verify-nonce-1",
	}

	response := &clientapi.RekeyUpdateResponse{
		Complete: true,
		Keys:     []string{"k0", "k1", "k2", "k3", "k4"},
	}

	err := proc.Verify(mockSys, response)
	if err == nil {
		t.Fatal("expected error when verification does not complete, got nil")
	}
	if mockSys.rekeyVerifyCancelCalls != 1 {
		t.Errorf("expected 1 verification cancel call, got %d", mockSys.rekeyVerifyCancelCalls)
	}
}

func TestRekeyHappyPath_WithVerification(t *testing.T) {
	// Full flow: Start → SubmitShards → StoreResult → Verify
	mockSys := &mockSysAPI{
		rekeyInitResp: &clientapi.RekeyStatusResponse{
			Started:              true,
			Nonce:                "rekey-nonce-1",
			N:                    5,
			T:                    3,
			VerificationRequired: true,
		},
		rekeyUpdateResponses: []*clientapi.RekeyUpdateResponse{
			{Complete: false, Nonce: "rekey-nonce-1"},
			{Complete: false, Nonce: "rekey-nonce-1"},
			{
				Complete:             true,
				Nonce:                "rekey-nonce-1",
				Keys:                 []string{"new0", "new1", "new2", "new3", "new4"},
				KeysB64:              []string{"bn0", "bn1", "bn2", "bn3", "bn4"},
				VerificationRequired: true,
				VerificationNonce:    "verify-nonce-abc",
			},
		},
		rekeyVerifyResponses: []*clientapi.RekeyVerificationUpdateResponse{
			{Complete: false, Nonce: "verify-nonce-abc"},
			{Complete: false, Nonce: "verify-nonce-abc"},
			{Complete: true, Nonce: "verify-nonce-abc"},
		},
	}

	mockCfg := &mockConfigLoader{
		loadedSecret:     testGenerationSecret(),
		currentRootToken: "s.root-token-abc123",
		nextGenName:      "openbao-unseal-gen-002",
	}

	proc := &rekey.RekeyProcess{
		Config:    mockCfg,
		State:     rekey.StateIdle,
		NewShares: 5,
		Threshold: 3,
	}

	// Step 1: Start
	err := proc.Start(mockSys)
	if err != nil {
		t.Fatalf("Start() error: %v", err)
	}
	if proc.State != rekey.StateInitiated {
		t.Fatalf("expected StateInitiated, got %v", proc.State)
	}

	// Step 2: SubmitShards
	resp, err := proc.SubmitShards(mockSys)
	if err != nil {
		t.Fatalf("SubmitShards() error: %v", err)
	}
	if proc.State != rekey.StateComplete {
		t.Fatalf("expected StateComplete, got %v", proc.State)
	}
	if proc.VerificationNonce != "verify-nonce-abc" {
		t.Fatalf("expected VerificationNonce to be captured, got %q", proc.VerificationNonce)
	}

	// Step 3: StoreResult
	err = proc.StoreResult(resp)
	if err != nil {
		t.Fatalf("StoreResult() error: %v", err)
	}
	if proc.State != rekey.StateStored {
		t.Fatalf("expected StateStored, got %v", proc.State)
	}

	// Step 4: Verify
	err = proc.Verify(mockSys, resp)
	if err != nil {
		t.Fatalf("Verify() error: %v", err)
	}
	if proc.State != rekey.StateVerified {
		t.Errorf("expected StateVerified, got %v", proc.State)
	}

	// Verify the stored secret has the new keys
	if mockCfg.storedSecret == nil {
		t.Fatal("no secret was stored")
	}
	if len(mockCfg.storedSecret.Keys) != 5 {
		t.Errorf("expected 5 keys stored, got %d", len(mockCfg.storedSecret.Keys))
	}
	if mockCfg.storedSecret.Keys[0] != "new0" {
		t.Errorf("expected first key 'new0', got %q", mockCfg.storedSecret.Keys[0])
	}
}

func TestStateString_Verified(t *testing.T) {
	if got := rekey.StateVerified.String(); got != "Verified" {
		t.Errorf("StateVerified.String() = %q, want %q", got, "Verified")
	}
}
