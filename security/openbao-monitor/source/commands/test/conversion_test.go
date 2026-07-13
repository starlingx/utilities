//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands_test

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"testing"

	baoCommands "github.com/michel-thebeau-WR/openbao-manager-go/baomon/commands"
	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	v1 "k8s.io/api/core/v1"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/kubernetes/fake"
)

// createLegacyShardSecret creates a legacy shard secret in the fake clientset.
func createLegacyShardSecret(t *testing.T, clientset kubernetes.Interface, namespace, name, hexKey, base64Key string) {
	t.Helper()
	ks := baoConfig.KeySecret{
		Key:        []string{hexKey},
		KeyEncoded: []string{base64Key},
	}
	data, err := json.Marshal(ks)
	if err != nil {
		t.Fatalf("failed to marshal legacy key secret: %v", err)
	}

	secret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
		},
		Data: map[string][]byte{
			"strdata": data,
		},
	}

	ctx := context.Background()
	_, err = clientset.CoreV1().Secrets(namespace).Create(ctx, secret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create legacy shard secret %s: %v", name, err)
	}
}

// createLegacyRootSecret creates a legacy root token secret in the fake clientset.
func createLegacyRootSecret(t *testing.T, clientset kubernetes.Interface, namespace, name, rootToken string) {
	t.Helper()
	secret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
		},
		Data: map[string][]byte{
			"strdata": []byte(rootToken),
		},
	}

	ctx := context.Background()
	_, err := clientset.CoreV1().Secrets(namespace).Create(ctx, secret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create legacy root secret %s: %v", name, err)
	}
}

// createAllLegacySecrets creates all 5 shard secrets and the root token secret
// in the real legacy "strdata"-JSON format that the migration path consumes.
// This is the single shared helper used by both the conversion unit tests and
// the integration tests.
func createAllLegacySecrets(t *testing.T, clientset kubernetes.Interface, namespace, prefix string) {
	t.Helper()
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}
	createLegacyRootSecret(t, clientset, namespace, prefix+"-root", "s.root-token-123")
}

func TestDetectLegacySecrets_AllPresent(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	createAllLegacySecrets(t, clientset, namespace, prefix)

	found, err := baoCommands.DetectLegacySecretsWithClientset(clientset, namespace, prefix)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !found {
		t.Error("expected legacy secrets to be detected, got false")
	}
}

func TestDetectLegacySecrets_NonePresent(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	found, err := baoCommands.DetectLegacySecretsWithClientset(clientset, namespace, prefix)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if found {
		t.Error("expected no legacy secrets detected, got true")
	}
}

func TestDetectLegacySecrets_MissingRoot(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// Create only shard secrets (no root)
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}

	found, err := baoCommands.DetectLegacySecretsWithClientset(clientset, namespace, prefix)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if found {
		t.Error("expected false when root is missing, got true")
	}
}

func TestDetectLegacySecrets_MissingShard(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// Create only shards 0-3 (missing shard 4) and root
	for i := 0; i < 4; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}
	createLegacyRootSecret(t, clientset, namespace, prefix+"-root", "s.root-token-123")

	found, err := baoCommands.DetectLegacySecretsWithClientset(clientset, namespace, prefix)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if found {
		t.Error("expected false when a shard is missing, got true")
	}
}

func TestDetectLegacySecrets_DefaultNamespace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	prefix := "cluster-key"

	// Create secrets in default "openbao" namespace
	createAllLegacySecrets(t, clientset, "openbao", prefix)

	// Pass empty namespace - should default to "openbao"
	found, err := baoCommands.DetectLegacySecretsWithClientset(clientset, "", prefix)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !found {
		t.Error("expected legacy secrets detected with default namespace, got false")
	}
}

func TestMigrateLegacySecrets_FullMigration(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	createAllLegacySecrets(t, clientset, namespace, prefix)

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify CurrentKeySecret was updated
	expectedGenName := "openbao-unseal-gen-001"
	if cfg.CurrentKeySecret != expectedGenName {
		t.Errorf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, expectedGenName)
	}

	// Verify the generation secret was created
	ctx := context.Background()
	genSecret, err := clientset.CoreV1().Secrets(namespace).Get(ctx, expectedGenName, metaV1.GetOptions{})
	if err != nil {
		t.Fatalf("failed to get generation secret: %v", err)
	}

	// Verify immutable is set
	if genSecret.Immutable == nil || !*genSecret.Immutable {
		t.Error("expected generation secret to be immutable")
	}

	// Verify labels
	expectedLabels := map[string]string{
		"app":        "openbao",
		"component":  "unseal-keys",
		"generation": "001",
	}
	for key, expected := range expectedLabels {
		if got := genSecret.Labels[key]; got != expected {
			t.Errorf("label %q = %q, want %q", key, got, expected)
		}
	}

	// Verify data content - keys in order
	rawData, ok := genSecret.Data["data"]
	if !ok {
		t.Fatal("generation secret has no 'data' key")
	}

	var stored baoConfig.GenerationSecret
	if err := json.Unmarshal(rawData, &stored); err != nil {
		t.Fatalf("failed to unmarshal stored data: %v", err)
	}

	// Verify 5 keys in order
	if len(stored.Keys) != 5 {
		t.Fatalf("expected 5 keys, got %d", len(stored.Keys))
	}
	for i := 0; i < 5; i++ {
		expectedKey := fmt.Sprintf("abcdef%d", i)
		if stored.Keys[i] != expectedKey {
			t.Errorf("Keys[%d] = %q, want %q", i, stored.Keys[i], expectedKey)
		}
		expectedB64 := base64.StdEncoding.EncodeToString([]byte(fmt.Sprintf("abcdef%d", i)))
		if stored.KeysBase64[i] != expectedB64 {
			t.Errorf("KeysBase64[%d] = %q, want %q", i, stored.KeysBase64[i], expectedB64)
		}
	}

	// Verify root token
	if stored.RootToken != "s.root-token-123" {
		t.Errorf("RootToken = %q, want %q", stored.RootToken, "s.root-token-123")
	}

	// Verify legacy secrets were NOT deleted
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		_, err := clientset.CoreV1().Secrets(namespace).Get(ctx, name, metaV1.GetOptions{})
		if err != nil {
			t.Errorf("legacy secret %q was deleted (should be retained): %v", name, err)
		}
	}
	_, err = clientset.CoreV1().Secrets(namespace).Get(ctx, prefix+"-root", metaV1.GetOptions{})
	if err != nil {
		t.Errorf("legacy root secret was deleted (should be retained): %v", err)
	}
}

func TestMigrateLegacySecrets_PartialSecrets_Error(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// Only create shards 0-2 (missing 3 and 4) + root
	for i := 0; i < 3; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}
	createLegacyRootSecret(t, clientset, namespace, prefix+"-root", "s.root-token-123")

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err == nil {
		t.Fatal("expected error for partial legacy secrets, got nil")
	}

	// Error should list missing secrets
	if !strings.Contains(err.Error(), "cluster-key-3") {
		t.Errorf("expected error to mention 'cluster-key-3', got: %v", err)
	}
	if !strings.Contains(err.Error(), "cluster-key-4") {
		t.Errorf("expected error to mention 'cluster-key-4', got: %v", err)
	}

	// Verify no generation secret was created
	ctx := context.Background()
	_, getErr := clientset.CoreV1().Secrets(namespace).Get(ctx, "openbao-unseal-gen-001", metaV1.GetOptions{})
	if getErr == nil {
		t.Error("generation secret should not have been created when secrets are missing")
	}
}

func TestMigrateLegacySecrets_MissingRootToken_Error(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// Create all 5 shards but no root token
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err == nil {
		t.Fatal("expected error for missing root token, got nil")
	}

	// Error should mention the missing root secret
	if !strings.Contains(err.Error(), "cluster-key-root") {
		t.Errorf("expected error to mention 'cluster-key-root', got: %v", err)
	}
}

func TestMigrateLegacySecrets_IdempotentRerun(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	createAllLegacySecrets(t, clientset, namespace, prefix)

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	// First migration
	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err != nil {
		t.Fatalf("first migration failed: %v", err)
	}

	expectedGenName := "openbao-unseal-gen-001"
	if cfg.CurrentKeySecret != expectedGenName {
		t.Fatalf("CurrentKeySecret after first migration = %q, want %q", cfg.CurrentKeySecret, expectedGenName)
	}

	// Second migration (idempotent re-run) — should succeed
	cfg2 := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}
	err = baoCommands.MigrateLegacySecretsWithClientset(cfg2, clientset)
	if err != nil {
		t.Fatalf("idempotent re-run failed: %v", err)
	}

	if cfg2.CurrentKeySecret != expectedGenName {
		t.Errorf("CurrentKeySecret after idempotent re-run = %q, want %q", cfg2.CurrentKeySecret, expectedGenName)
	}
}

func TestMigrateLegacySecrets_DefaultPrefix(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	createAllLegacySecrets(t, clientset, namespace, prefix)

	// Leave SecretPrefix empty — should default to "cluster-key"
	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     "",
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.CurrentKeySecret != "openbao-unseal-gen-001" {
		t.Errorf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, "openbao-unseal-gen-001")
	}
}

// createLegacyShardsExcept creates the 5 legacy shards with valid data, except
// shard `badIndex` which is created with the provided override (hex, b64).
// The root token secret is also created (valid).
func createLegacyShardsWithOverride(t *testing.T, clientset kubernetes.Interface, namespace, prefix string, badIndex int, hexOverride, b64Override string) {
	t.Helper()
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		if i == badIndex {
			hexKey = hexOverride
			base64Key = b64Override
		}
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}
	createLegacyRootSecret(t, clientset, namespace, prefix+"-root", "s.root-token-123")
}

// TestMigrateLegacySecrets_InvalidBase64_Refused verifies the migration refuses
// to freeze a generation secret when a shard's keys_base64 is not valid base64
// (a corruption signal), rather than storing an unrepairable immutable secret.
func TestMigrateLegacySecrets_InvalidBase64_Refused(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// Shard 2 has a hex key but a base64 value that cannot decode.
	createLegacyShardsWithOverride(t, clientset, namespace, prefix, 2, "abcdef2", "not-valid-base64!!")

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err == nil {
		t.Fatal("expected error for invalid base64 shard, got nil")
	}
	if !strings.Contains(err.Error(), "base64") {
		t.Errorf("expected error to mention base64, got: %v", err)
	}

	// Critically: no generation secret should have been created (nothing frozen).
	ctx := context.Background()
	_, getErr := clientset.CoreV1().Secrets(namespace).Get(ctx, "openbao-unseal-gen-001", metaV1.GetOptions{})
	if getErr == nil {
		t.Error("generation secret was created despite invalid base64 — a bad secret was frozen")
	}
}

// TestMigrateLegacySecrets_EmptyRootToken_Refused verifies the migration refuses
// to freeze a generation secret when the root token secret exists but is empty
// (structural validation catches the empty root token before the store).
func TestMigrateLegacySecrets_EmptyRootToken_Refused(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	// All 5 shards valid, root token secret present but empty/whitespace.
	for i := 0; i < 5; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		hexKey := fmt.Sprintf("abcdef%d", i)
		base64Key := base64.StdEncoding.EncodeToString([]byte(hexKey))
		createLegacyShardSecret(t, clientset, namespace, name, hexKey, base64Key)
	}
	// Root secret exists (so it is not "missing") but trims to empty.
	createLegacyRootSecret(t, clientset, namespace, prefix+"-root", "   ")

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset)
	if err == nil {
		t.Fatal("expected error for empty root token, got nil")
	}

	// No generation secret should have been frozen.
	ctx := context.Background()
	_, getErr := clientset.CoreV1().Secrets(namespace).Get(ctx, "openbao-unseal-gen-001", metaV1.GetOptions{})
	if getErr == nil {
		t.Error("generation secret was created despite empty root token — a bad secret was frozen")
	}
}

// TestMigrateLegacySecrets_ReadBackVerified confirms the happy path passes the
// post-store read-back verification (the migration reloads and validates the
// stored generation secret before reporting success).
func TestMigrateLegacySecrets_ReadBackVerified(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	namespace := "openbao"
	prefix := "cluster-key"

	createAllLegacySecrets(t, clientset, namespace, prefix)

	cfg := &baoConfig.MonitorConfig{
		Namespace:        namespace,
		SecretPrefix:     prefix,
		GenerationPrefix: "openbao-unseal-gen",
	}

	if err := baoCommands.MigrateLegacySecretsWithClientset(cfg, clientset); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// The stored secret must be reloadable and valid (read-back succeeded).
	loaded, err := cfg.LoadGenerationSecret("openbao-unseal-gen-001")
	if err != nil {
		t.Fatalf("stored generation secret failed to reload/validate: %v", err)
	}
	if len(loaded.Keys) != 5 {
		t.Errorf("expected 5 keys after migration, got %d", len(loaded.Keys))
	}
}
