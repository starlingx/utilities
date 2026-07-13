//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig_test

import (
	"testing"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"

	clientapi "github.com/openbao/openbao/api/v2"
	"k8s.io/client-go/kubernetes/fake"
)

func TestParseInitResponseToGeneration(t *testing.T) {
	resp := &clientapi.InitResponse{
		Keys:      []string{"aaa111", "bbb222", "ccc333", "ddd444", "eee555"},
		KeysB64:   []string{"YWFhMTEx", "YmJiMjIy", "Y2NjMzMz", "ZGRkNDQ0", "ZWVlNTU1"},
		RootToken: "s.root-token-abc",
	}

	genSecret, err := baoConfig.ParseInitResponseToGeneration(resp)
	if err != nil {
		t.Fatalf("ParseInitResponseToGeneration failed: %v", err)
	}

	if genSecret == nil {
		t.Fatal("baoConfig.ParseInitResponseToGeneration returned nil")
	}

	// Verify keys
	if len(genSecret.Keys) != 5 {
		t.Fatalf("expected 5 keys, got %d", len(genSecret.Keys))
	}
	for i, key := range resp.Keys {
		if genSecret.Keys[i] != key {
			t.Errorf("Keys[%d] = %q, want %q", i, genSecret.Keys[i], key)
		}
	}

	// Verify keys_base64
	if len(genSecret.KeysBase64) != 5 {
		t.Fatalf("expected 5 keys_base64, got %d", len(genSecret.KeysBase64))
	}
	for i, key := range resp.KeysB64 {
		if genSecret.KeysBase64[i] != key {
			t.Errorf("KeysBase64[%d] = %q, want %q", i, genSecret.KeysBase64[i], key)
		}
	}

	// Verify root token
	if genSecret.RootToken != resp.RootToken {
		t.Errorf("RootToken = %q, want %q", genSecret.RootToken, resp.RootToken)
	}
}

func TestParseInitResponseToGeneration_Validates(t *testing.T) {
	resp := &clientapi.InitResponse{
		Keys:      []string{"aaa111", "bbb222", "ccc333", "ddd444", "eee555"},
		KeysB64:   []string{"YWFhMTEx", "YmJiMjIy", "Y2NjMzMz", "ZGRkNDQ0", "ZWVlNTU1"},
		RootToken: "s.root-token-abc",
	}

	_, err := baoConfig.ParseInitResponseToGeneration(resp)
	if err != nil {
		t.Fatalf("ParseInitResponseToGeneration failed: %v", err)
	}

}

func TestParseInitResponseToGeneration_RoundTrip(t *testing.T) {
	// Simulate a full init → store → load round-trip
	resp := &clientapi.InitResponse{
		Keys:      []string{"key0hex", "key1hex", "key2hex", "key3hex", "key4hex"},
		KeysB64:   []string{"a2V5MGhleA==", "a2V5MWhleA==", "a2V5MmhleA==", "a2V5M2hleA==", "a2V5NGhleA=="},
		RootToken: "s.initial-root-token",
	}

	// Step 1: Parse init response to generation secret
	genSecret, err := baoConfig.ParseInitResponseToGeneration(resp)
	if err != nil {
		t.Fatalf("ParseInitResponseToGeneration failed: %v", err)
	}

	// Step 2: Store the generation secret using a fake clientset
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	// Compute next generation name (should be gen-001 since nothing exists)
	genName, err := cfg.NextGenerationName()
	if err != nil {
		t.Fatalf("NextGenerationName failed: %v", err)
	}
	if genName != "openbao-unseal-gen-001" {
		t.Fatalf("expected gen name %q, got %q", "openbao-unseal-gen-001", genName)
	}

	// Store the generation secret
	err = cfg.StoreGenerationSecret(genName, genSecret)
	if err != nil {
		t.Fatalf("StoreGenerationSecret failed: %v", err)
	}

	// Verify CurrentKeySecret was set
	if cfg.CurrentKeySecret != genName {
		t.Fatalf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, genName)
	}

	// Step 3: Load the generation secret back
	loaded, err := cfg.LoadGenerationSecret()
	if err != nil {
		t.Fatalf("LoadGenerationSecret failed: %v", err)
	}

	// Step 4: Verify round-trip integrity
	if len(loaded.Keys) != len(genSecret.Keys) {
		t.Fatalf("loaded key count %d != original %d", len(loaded.Keys), len(genSecret.Keys))
	}
	for i := range genSecret.Keys {
		if loaded.Keys[i] != genSecret.Keys[i] {
			t.Errorf("loaded Keys[%d] = %q, want %q", i, loaded.Keys[i], genSecret.Keys[i])
		}
	}
	for i := range genSecret.KeysBase64 {
		if loaded.KeysBase64[i] != genSecret.KeysBase64[i] {
			t.Errorf("loaded KeysBase64[%d] = %q, want %q", i, loaded.KeysBase64[i], genSecret.KeysBase64[i])
		}
	}
	if loaded.RootToken != genSecret.RootToken {
		t.Errorf("loaded RootToken = %q, want %q", loaded.RootToken, genSecret.RootToken)
	}
}
