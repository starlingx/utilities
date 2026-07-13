//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig_test

import (
	"bytes"
	"strings"
	"testing"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
)

func TestYAMLRoundTrip_NewFields(t *testing.T) {
	yamlInput := `
ServerAddresses:
  server-0:
    host: 10.0.0.1
    port: 8200
Tokens: {}
UnsealKeyShards: {}
Namespace: openbao
SecretPrefix: cluster-key
GenerationPrefix: openbao-unseal-gen
CurrentKeySecret: openbao-unseal-gen-002
k8s: true
in-cluster: false
`

	cfg := &baoConfig.MonitorConfig{}
	reader := strings.NewReader(yamlInput)
	err := cfg.ReadYAMLMonitorConfig(reader)
	if err != nil {
		t.Fatalf("ReadYAMLMonitorConfig failed: %v", err)
	}

	// Verify new fields were parsed correctly
	if cfg.GenerationPrefix != "openbao-unseal-gen" {
		t.Errorf("GenerationPrefix = %q, want %q", cfg.GenerationPrefix, "openbao-unseal-gen")
	}
	if cfg.CurrentKeySecret != "openbao-unseal-gen-002" {
		t.Errorf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, "openbao-unseal-gen-002")
	}

	// Write back to YAML
	var buf bytes.Buffer
	err = cfg.WriteYAMLMonitorConfig(&buf)
	if err != nil {
		t.Fatalf("WriteYAMLMonitorConfig failed: %v", err)
	}

	// Re-read the written YAML
	cfg2 := &baoConfig.MonitorConfig{}
	err = cfg2.ReadYAMLMonitorConfig(&buf)
	if err != nil {
		t.Fatalf("ReadYAMLMonitorConfig (round-trip) failed: %v", err)
	}

	// Verify fields survived round-trip
	if cfg2.GenerationPrefix != cfg.GenerationPrefix {
		t.Errorf("round-trip GenerationPrefix = %q, want %q", cfg2.GenerationPrefix, cfg.GenerationPrefix)
	}
	if cfg2.CurrentKeySecret != cfg.CurrentKeySecret {
		t.Errorf("round-trip CurrentKeySecret = %q, want %q", cfg2.CurrentKeySecret, cfg.CurrentKeySecret)
	}
	if cfg2.SecretPrefix != cfg.SecretPrefix {
		t.Errorf("round-trip SecretPrefix = %q, want %q", cfg2.SecretPrefix, cfg.SecretPrefix)
	}
}

func TestYAMLRoundTrip_EmptyNewFields(t *testing.T) {
	yamlInput := `
ServerAddresses:
  server-0:
    host: 10.0.0.1
    port: 8200
Tokens: {}
UnsealKeyShards: {}
Namespace: openbao
`

	cfg := &baoConfig.MonitorConfig{}
	reader := strings.NewReader(yamlInput)
	err := cfg.ReadYAMLMonitorConfig(reader)
	if err != nil {
		t.Fatalf("ReadYAMLMonitorConfig failed: %v", err)
	}

	// When not set, fields should be empty strings
	if cfg.GenerationPrefix != "" {
		t.Errorf("GenerationPrefix = %q, want empty", cfg.GenerationPrefix)
	}
	if cfg.CurrentKeySecret != "" {
		t.Errorf("CurrentKeySecret = %q, want empty", cfg.CurrentKeySecret)
	}

	// Write and re-read
	var buf bytes.Buffer
	err = cfg.WriteYAMLMonitorConfig(&buf)
	if err != nil {
		t.Fatalf("WriteYAMLMonitorConfig failed: %v", err)
	}

	cfg2 := &baoConfig.MonitorConfig{}
	err = cfg2.ReadYAMLMonitorConfig(&buf)
	if err != nil {
		t.Fatalf("ReadYAMLMonitorConfig (round-trip) failed: %v", err)
	}

	if cfg2.GenerationPrefix != "" {
		t.Errorf("round-trip GenerationPrefix = %q, want empty", cfg2.GenerationPrefix)
	}
	if cfg2.CurrentKeySecret != "" {
		t.Errorf("round-trip CurrentKeySecret = %q, want empty", cfg2.CurrentKeySecret)
	}
}

func TestGetCurrentRootToken_FromGenerationSecret(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		CurrentKeySecret: "openbao-unseal-gen-001",
	}
	cfg.SetLoadedGenerationSecret(&baoConfig.GenerationSecret{
		Keys:       []string{"k1", "k2", "k3", "k4", "k5"},
		KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
		RootToken:  "s.generationroottoken12345",
	})

	got := cfg.GetCurrentRootToken()
	if got != "s.generationroottoken12345" {
		t.Errorf("GetCurrentRootToken() = %q, want %q", got, "s.generationroottoken12345")
	}
}

func TestGetCurrentRootToken_FallbackToLegacy(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		SecretPrefix: "cluster-key",
		Tokens: map[string]baoConfig.Token{
			"cluster-key-root": {Duration: 0, Key: "s.legacyroottoken1234567"},
		},
	}

	got := cfg.GetCurrentRootToken()
	if got != "s.legacyroottoken1234567" {
		t.Errorf("GetCurrentRootToken() = %q, want %q", got, "s.legacyroottoken1234567")
	}
}

func TestGetCurrentRootToken_NoTokenAvailable(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		Tokens: map[string]baoConfig.Token{},
	}

	got := cfg.GetCurrentRootToken()
	if got != "" {
		t.Errorf("GetCurrentRootToken() = %q, want empty", got)
	}
}

func TestGetUnsealKeys_FromGenerationSecret(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		CurrentKeySecret: "openbao-unseal-gen-001",
	}
	expectedKeys := []string{"key1", "key2", "key3", "key4", "key5"}
	cfg.SetLoadedGenerationSecret(&baoConfig.GenerationSecret{
		Keys:       expectedKeys,
		KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
		RootToken:  "s.roottoken123456789012",
	})

	got := cfg.GetUnsealKeys()
	if len(got) != 5 {
		t.Fatalf("GetUnsealKeys() returned %d keys, want 5", len(got))
	}
	for i, key := range got {
		if key != expectedKeys[i] {
			t.Errorf("GetUnsealKeys()[%d] = %q, want %q", i, key, expectedKeys[i])
		}
	}
}

func TestGetUnsealKeys_FallbackToLegacy(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		UnsealKeyShards: map[string]baoConfig.KeyShards{
			"cluster-key-0": {Key: "legacykey0", KeyBase64: "bGVnYWN5a2V5MA=="},
			"cluster-key-1": {Key: "legacykey1", KeyBase64: "bGVnYWN5a2V5MQ=="},
		},
	}

	got := cfg.GetUnsealKeys()
	if len(got) != 2 {
		t.Fatalf("GetUnsealKeys() returned %d keys, want 2", len(got))
	}

	// Check that both keys are present (map ordering is non-deterministic)
	keySet := make(map[string]bool)
	for _, k := range got {
		keySet[k] = true
	}
	if !keySet["legacykey0"] || !keySet["legacykey1"] {
		t.Errorf("GetUnsealKeys() = %v, expected to contain legacykey0 and legacykey1", got)
	}
}

func TestGetUnsealKeys_EmptyWhenNoData(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{
		UnsealKeyShards: map[string]baoConfig.KeyShards{},
	}

	got := cfg.GetUnsealKeys()
	if len(got) != 0 {
		t.Errorf("GetUnsealKeys() returned %d keys, want 0", len(got))
	}
}

func TestGetUnsealKeys_NilUnsealKeyShards(t *testing.T) {
	// When no generation secret is loaded and UnsealKeyShards is nil
	// (struct zero-value), ranging over nil map is safe in Go — returns
	// zero iterations. This is the realistic "absent" case on a fresh config.
	cfg := &baoConfig.MonitorConfig{}

	got := cfg.GetUnsealKeys()
	if len(got) != 0 {
		t.Errorf("GetUnsealKeys() with nil UnsealKeyShards returned %d keys, want 0", len(got))
	}
}

func TestSetLoadedGenerationSecret(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{}

	// Initially nil
	if cfg.GetLoadedGenerationSecret() != nil {
		t.Error("loadedGenerationSecret should be nil initially")
	}

	secret := &baoConfig.GenerationSecret{
		Keys:       []string{"k1", "k2", "k3", "k4", "k5"},
		KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
		RootToken:  "s.roottoken123456789012",
	}
	cfg.SetLoadedGenerationSecret(secret)

	if cfg.GetLoadedGenerationSecret() == nil {
		t.Fatal("loadedGenerationSecret should not be nil after SetLoadedGenerationSecret")
	}
	if cfg.GetLoadedGenerationSecret().RootToken != "s.roottoken123456789012" {
		t.Errorf("RootToken = %q, want %q", cfg.GetLoadedGenerationSecret().RootToken, "s.roottoken123456789012")
	}

	// Setting to nil should clear it
	cfg.SetLoadedGenerationSecret(nil)
	if cfg.GetLoadedGenerationSecret() != nil {
		t.Error("loadedGenerationSecret should be nil after SetLoadedGenerationSecret(nil)")
	}
}

func TestGetRootTokenName_DefaultPrefix(t *testing.T) {
	cfg := baoConfig.MonitorConfig{}
	got := cfg.GetRootTokenName()
	if got != "cluster-key-root" {
		t.Errorf("getRootTokenName() = %q, want %q", got, "cluster-key-root")
	}
}

func TestGetRootTokenName_CustomPrefix(t *testing.T) {
	cfg := baoConfig.MonitorConfig{SecretPrefix: "my-prefix"}
	got := cfg.GetRootTokenName()
	if got != "my-prefix-root" {
		t.Errorf("getRootTokenName() = %q, want %q", got, "my-prefix-root")
	}
}
