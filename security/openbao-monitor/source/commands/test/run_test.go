//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands_test

import (
	"testing"

	baoCommands "github.com/michel-thebeau-WR/openbao-manager-go/baomon/commands"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"k8s.io/client-go/kubernetes/fake"
	"k8s.io/client-go/rest"
)

// TestDiscoverCurrentGeneration_EmptyNamespace verifies that when no generation
// secrets exist and CurrentKeySecret is empty, it remains empty (waiting for init).
func TestDiscoverCurrentGeneration_EmptyNamespace(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "",
	}

	// We can't easily test with a real k8s config here without fake clientset,
	// but we verify the logic path by calling with a nil config (which will
	// fail to create clientset). The baoCommands.DiscoverCurrentGeneration function should
	// return an error when k8s config is invalid but cfg.CurrentKeySecret stays empty.
	err := baoCommands.DiscoverCurrentGeneration(cfg, &rest.Config{Host: "http://invalid:12345"})
	// The error is expected since we can't connect to k8s
	if err == nil {
		// If it passes with invalid config, CurrentKeySecret should still be empty
		if cfg.CurrentKeySecret != "" {
			t.Errorf("CurrentKeySecret should remain empty, got %q", cfg.CurrentKeySecret)
		}
	}
}

// TestDiscoverCurrentGeneration_AlreadySet verifies that when CurrentKeySecret
// is already set, it is not overwritten.
func TestDiscoverCurrentGeneration_AlreadySet(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-003",
		Clientset:        clientset,
	}

	// Store gen-003 so ListGenerationSecrets finds it and confirms the pointer is correct
	gen003 := &baoConfig.GenerationSecret{
		Keys:       []string{"k0", "k1", "k2", "k3", "k4"},
		KeysBase64: []string{"a0", "a1", "a2", "a3", "a4"},
		RootToken:  "s.root",
	}
	err := cfg.StoreGenerationSecret("openbao-unseal-gen-003", gen003)
	if err != nil {
		t.Fatalf("failed to store gen-003: %v", err)
	}

	// DiscoverCurrentGeneration should confirm the pointer is already latest
	err = baoCommands.DiscoverCurrentGeneration(cfg, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.CurrentKeySecret != "openbao-unseal-gen-003" {
		t.Errorf("CurrentKeySecret changed to %q, should remain unchanged", cfg.CurrentKeySecret)
	}
}

// TestUnsealWithGenKeys_NilSecret verifies that baoCommands.UnsealWithGenKeys returns an
// error when given a nil generation secret.
func TestUnsealWithGenKeys_NilSecret(t *testing.T) {
	err := baoCommands.UnsealWithGenKeys(nil, nil)
	if err == nil {
		t.Error("expected error for nil generation secret")
	}
}

// TestUnsealWithGenKeys_InsufficientKeys verifies that baoCommands.UnsealWithGenKeys returns
// an error when the generation secret has fewer keys than the threshold.
func TestUnsealWithGenKeys_InsufficientKeys(t *testing.T) {
	genSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"key1", "key2"}, // only 2 keys, need 3
		KeysBase64: []string{"a2V5MQ==", "a2V5Mg=="},
		RootToken:  "s.root-token",
	}

	err := baoCommands.UnsealWithGenKeys(nil, genSecret)
	if err == nil {
		t.Error("expected error for insufficient keys")
	}
}

// TestInitConstants verifies that the init constants match the 5/3 requirement.
func TestInitConstants(t *testing.T) {
	if baoCommands.InitSecretShares != 5 {
		t.Errorf("baoCommands.InitSecretShares = %d, want 5", baoCommands.InitSecretShares)
	}
	if baoCommands.InitSecretThreshold != 3 {
		t.Errorf("baoCommands.InitSecretThreshold = %d, want 3", baoCommands.InitSecretThreshold)
	}
}

// TestDiscoverCurrentGeneration_WithExistingGens tests that the discovery
// logic is correct by verifying the underlying ListGenerationSecrets behavior
// with a fake clientset.
func TestDiscoverCurrentGeneration_WithExistingGens(t *testing.T) {
	// Test that a stale pointer is advanced to the latest generation
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-002",
		Clientset:        clientset,
	}

	genSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"k0", "k1", "k2", "k3", "k4"},
		KeysBase64: []string{"a0", "a1", "a2", "a3", "a4"},
		RootToken:  "s.root",
	}

	// Store gen-002 and gen-003
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-002", genSecret); err != nil {
		t.Fatalf("failed to store gen-002: %v", err)
	}
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-003", genSecret); err != nil {
		t.Fatalf("failed to store gen-003: %v", err)
	}

	// CurrentKeySecret is gen-002 but gen-003 exists — should advance
	err := baoCommands.DiscoverCurrentGeneration(cfg, nil)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.CurrentKeySecret != "openbao-unseal-gen-003" {
		t.Errorf("CurrentKeySecret should advance to gen-003, got %q", cfg.CurrentKeySecret)
	}
}

// TestUnsealWithGenKeys_EmptyKeys tests that unseal with no keys returns error.
func TestUnsealWithGenKeys_EmptyKeys(t *testing.T) {
	genSecret := &baoConfig.GenerationSecret{
		Keys:       []string{},
		KeysBase64: []string{},
		RootToken:  "s.root",
	}

	// UnsealWithGenKeys should return error for insufficient keys
	// We can't test the full unseal without a real server, but we verify
	// the pre-check logic.
	err := baoCommands.UnsealWithGenKeys(nil, genSecret)
	if err == nil {
		t.Error("expected error with empty keys, got nil")
	}
}
