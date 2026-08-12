//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands_test

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	baoCommands "github.com/michel-thebeau-WR/openbao-manager-go/baomon/commands"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	v1 "k8s.io/api/core/v1"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

// mockRekeyChecker implements RekeyChecker for testing.
type mockRekeyChecker struct {
	InProgress bool
	Err        error
}

func (m *mockRekeyChecker) CheckRekeyInProgress() (bool, error) {
	return m.InProgress, m.Err
}

// createGenerationSecretInK8s creates a generation secret in the fake clientset
// for use by snapshot metadata tests.
func createGenerationSecretInK8s(t *testing.T, clientset *fake.Clientset, namespace, name string, secret *baoConfig.GenerationSecret) {
	t.Helper()
	data, err := json.Marshal(secret)
	if err != nil {
		t.Fatalf("failed to marshal generation secret: %v", err)
	}

	immutable := true
	k8sSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": "001",
			},
		},
		Immutable: &immutable,
		Data: map[string][]byte{
			"data": data,
		},
	}

	ctx := context.Background()
	_, err = clientset.CoreV1().Secrets(namespace).Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create generation secret %s: %v", name, err)
	}
}

// validGenerationSecret returns a valid GenerationSecret for testing.
func validGenerationSecret() *baoConfig.GenerationSecret {
	return &baoConfig.GenerationSecret{
		Keys:       []string{"key0", "key1", "key2", "key3", "key4"},
		KeysBase64: []string{"a2V5MA==", "a2V5MQ==", "a2V5Mg==", "a2V5Mw==", "a2V5NA=="},
		RootToken:  "s.root-token-test",
	}
}

func TestCreateSnapshotMetadata_ValidGeneration(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	genName := "openbao-unseal-gen-001"
	secret := validGenerationSecret()

	createGenerationSecretInK8s(t, clientset, namespace, genName, secret)

	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        namespace,
		CurrentKeySecret: genName,
	}

	rekeyChecker := &mockRekeyChecker{InProgress: false}

	metadata, err := baoCommands.CreateSnapshotMetadata(cfg, rekeyChecker)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify generation name
	if metadata.GenerationName != genName {
		t.Errorf("GenerationName = %q, want %q", metadata.GenerationName, genName)
	}

	// Verify hash is non-empty and correctly computed
	if metadata.KeyDataHash == "" {
		t.Error("KeyDataHash should not be empty")
	}

	// Verify hash matches expected SHA-256
	data, _ := json.Marshal(secret)
	expectedHash := fmt.Sprintf("%x", sha256.Sum256(data))
	if metadata.KeyDataHash != expectedHash {
		t.Errorf("KeyDataHash = %q, want %q", metadata.KeyDataHash, expectedHash)
	}
}

func TestCreateSnapshotMetadata_RekeyInProgress(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	genName := "openbao-unseal-gen-001"
	secret := validGenerationSecret()

	createGenerationSecretInK8s(t, clientset, namespace, genName, secret)

	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        namespace,
		CurrentKeySecret: genName,
	}

	// Rekey is in progress — should refuse
	rekeyChecker := &mockRekeyChecker{InProgress: true}

	_, err := baoCommands.CreateSnapshotMetadata(cfg, rekeyChecker)
	if err == nil {
		t.Fatal("expected error when rekey is in progress, got nil")
	}

	if !strings.Contains(err.Error(), "rekey is in progress") {
		t.Errorf("expected error about rekey in progress, got: %v", err)
	}
}

func TestCreateSnapshotMetadata_NoCurrentKeySecret(t *testing.T) {
	clientset := fake.NewSimpleClientset()

	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		CurrentKeySecret: "", // empty
	}

	rekeyChecker := &mockRekeyChecker{InProgress: false}

	_, err := baoCommands.CreateSnapshotMetadata(cfg, rekeyChecker)
	if err == nil {
		t.Fatal("expected error when CurrentKeySecret is empty, got nil")
	}

	if !strings.Contains(err.Error(), "CurrentKeySecret is empty") {
		t.Errorf("expected error about empty CurrentKeySecret, got: %v", err)
	}
}

func TestValidateSnapshotMetadata_SecretExists(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	genName := "openbao-unseal-gen-001"
	secret := validGenerationSecret()

	createGenerationSecretInK8s(t, clientset, namespace, genName, secret)

	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        namespace,
		CurrentKeySecret: "openbao-unseal-gen-002", // different from metadata
	}

	// Compute expected hash
	data, _ := json.Marshal(secret)
	expectedHash := fmt.Sprintf("%x", sha256.Sum256(data))

	metadata := &baoCommands.SnapshotMetadata{
		GenerationName: genName,
		KeyDataHash:    expectedHash,
	}

	err := baoCommands.ValidateSnapshotMetadata(metadata, cfg)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify cfg.CurrentKeySecret was restored (not permanently changed)
	if cfg.CurrentKeySecret != "openbao-unseal-gen-002" {
		t.Errorf("CurrentKeySecret was not restored, got %q", cfg.CurrentKeySecret)
	}
}

func TestValidateSnapshotMetadata_SecretMissing(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"

	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        namespace,
		CurrentKeySecret: "openbao-unseal-gen-002",
	}

	metadata := &baoCommands.SnapshotMetadata{
		GenerationName: "openbao-unseal-gen-001", // does not exist in k8s
		KeyDataHash:    "abc123",
	}

	err := baoCommands.ValidateSnapshotMetadata(metadata, cfg)
	if err == nil {
		t.Fatal("expected error for missing generation secret, got nil")
	}

	if !strings.Contains(err.Error(), "no longer exists") {
		t.Errorf("expected error about secret not existing, got: %v", err)
	}
}

func TestComputeKeyDataHash(t *testing.T) {
	secret := validGenerationSecret()

	hash, err := baoCommands.ComputeKeyDataHash(secret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify the hash is deterministic (same input → same output)
	hash2, err := baoCommands.ComputeKeyDataHash(secret)
	if err != nil {
		t.Fatalf("unexpected error on second call: %v", err)
	}
	if hash != hash2 {
		t.Errorf("hash not deterministic: %q != %q", hash, hash2)
	}

	// Verify it's a valid sha256 hex string (64 chars)
	if len(hash) != 64 {
		t.Errorf("expected 64-char hex hash, got %d chars: %q", len(hash), hash)
	}

	// Verify manually computed hash matches
	data, _ := json.Marshal(secret)
	expectedHash := fmt.Sprintf("%x", sha256.Sum256(data))
	if hash != expectedHash {
		t.Errorf("hash = %q, want %q", hash, expectedHash)
	}

	// Verify different data produces different hash
	differentSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"diff0", "diff1", "diff2", "diff3", "diff4"},
		KeysBase64: []string{"ZGlmZjA=", "ZGlmZjE=", "ZGlmZjI=", "ZGlmZjM=", "ZGlmZjQ="},
		RootToken:  "s.different-token",
	}
	diffHash, err := baoCommands.ComputeKeyDataHash(differentSecret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if diffHash == hash {
		t.Error("different secrets should produce different hashes")
	}
}

func TestValidateSnapshotMetadata_NilMetadata(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	err := baoCommands.ValidateSnapshotMetadata(nil, cfg)
	if err == nil {
		t.Fatal("expected error for nil metadata, got nil")
	}

	if !strings.Contains(err.Error(), "nil") {
		t.Errorf("expected error about nil metadata, got: %v", err)
	}
}

func TestValidateSnapshotMetadata_EmptyGenerationName(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	metadata := &baoCommands.SnapshotMetadata{
		GenerationName: "",
		KeyDataHash:    "abc123",
	}

	err := baoCommands.ValidateSnapshotMetadata(metadata, cfg)
	if err == nil {
		t.Fatal("expected error for empty generation name, got nil")
	}

	if !strings.Contains(err.Error(), "empty generation name") {
		t.Errorf("expected error about empty generation name, got: %v", err)
	}
}
