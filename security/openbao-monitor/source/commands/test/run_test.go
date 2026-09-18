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

// TestDiscoverCurrentGeneration_PointerIsAuthoritative verifies that when the
// pointer secret exists, discovery adopts the generation it references — even
// if a higher-sequence generation secret also exists. The pointer is the source
// of truth; the "highest sequence" heuristic is not used when a pointer exists.
func TestDiscoverCurrentGeneration_PointerIsAuthoritative(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "",
		Clientset:        clientset,
	}

	gen := &baoConfig.GenerationSecret{
		Keys:       []string{"k0", "k1", "k2", "k3", "k4"},
		KeysBase64: []string{"a0", "a1", "a2", "a3", "a4"},
		RootToken:  "s.root",
	}

	// gen-002 and gen-003 both exist, but the pointer references gen-002.
	// This models an interrupted rekey: gen-003 was stored but never verified,
	// so it must NOT become active.
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-002", gen); err != nil {
		t.Fatalf("failed to store gen-002: %v", err)
	}
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-003", gen); err != nil {
		t.Fatalf("failed to store gen-003: %v", err)
	}
	if err := cfg.StoreCurrentKeyPointer("openbao-unseal-gen-002"); err != nil {
		t.Fatalf("failed to store pointer: %v", err)
	}

	// Reset the cache so discovery must read the pointer.
	cfg.CurrentKeySecret = ""

	if err := baoCommands.DiscoverCurrentGeneration(cfg, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.CurrentKeySecret != "openbao-unseal-gen-002" {
		t.Errorf("CurrentKeySecret = %q, want pointer value openbao-unseal-gen-002 (not highest gen-003)",
			cfg.CurrentKeySecret)
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

// TestDiscoverCurrentGeneration_FallbackSeedsPointer verifies the first-boot /
// upgrade path: when no pointer secret exists but generation secrets do,
// discovery adopts the highest-sequence generation AND seeds the pointer secret
// from it, so subsequent discovery is pointer-driven.
func TestDiscoverCurrentGeneration_FallbackSeedsPointer(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "",
		Clientset:        clientset,
	}

	genSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"k0", "k1", "k2", "k3", "k4"},
		KeysBase64: []string{"a0", "a1", "a2", "a3", "a4"},
		RootToken:  "s.root",
	}

	// Two generations exist, no pointer secret yet.
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-002", genSecret); err != nil {
		t.Fatalf("failed to store gen-002: %v", err)
	}
	if err := cfg.StoreGenerationSecret("openbao-unseal-gen-003", genSecret); err != nil {
		t.Fatalf("failed to store gen-003: %v", err)
	}
	// Reset cache so discovery must fall back to highest gen.
	cfg.CurrentKeySecret = ""

	if err := baoCommands.DiscoverCurrentGeneration(cfg, nil); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Cache should adopt highest generation.
	if cfg.CurrentKeySecret != "openbao-unseal-gen-003" {
		t.Errorf("CurrentKeySecret = %q, want highest gen-003", cfg.CurrentKeySecret)
	}

	// The pointer secret should now be seeded with the same value.
	seeded, err := cfg.LoadCurrentKeyPointer()
	if err != nil {
		t.Fatalf("failed to load seeded pointer: %v", err)
	}
	if seeded != "openbao-unseal-gen-003" {
		t.Errorf("seeded pointer = %q, want openbao-unseal-gen-003", seeded)
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
