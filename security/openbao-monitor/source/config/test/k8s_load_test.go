//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig_test

import (
	"context"
	"encoding/json"
	"testing"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"

	v1 "k8s.io/api/core/v1"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

// createK8sSecretFromGeneration is a test helper that creates a k8s secret
// in the fake clientset from a GenerationSecret (or raw bytes for malformed tests).
func createK8sSecretFromGeneration(t *testing.T, clientset *fake.Clientset, namespace, name string, secret *baoConfig.GenerationSecret) {
	t.Helper()
	data, err := json.Marshal(secret)
	if err != nil {
		t.Fatalf("failed to marshal generation secret for test setup: %v", err)
	}
	createK8sSecretFromRawData(t, clientset, namespace, name, data)
}

func createK8sSecretFromRawData(t *testing.T, clientset *fake.Clientset, namespace, name string, rawData []byte) {
	t.Helper()
	immutable := true
	k8sSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": baoConfig.ExtractSeqNum(name),
			},
		},
		Immutable: &immutable,
		Data: map[string][]byte{
			"data": rawData,
		},
	}

	ctx := context.Background()
	_, err := clientset.CoreV1().Secrets(namespace).Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create test secret: %v", err)
	}
}

func TestLoadGenerationSecret_NormalLoad(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	secret := validTestSecret()
	createK8sSecretFromGeneration(t, clientset, "openbao", "openbao-unseal-gen-001", secret)

	loaded, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify the loaded secret matches what was stored
	if loaded.RootToken != secret.RootToken {
		t.Errorf("RootToken = %q, want %q", loaded.RootToken, secret.RootToken)
	}
	if len(loaded.Keys) != len(secret.Keys) {
		t.Errorf("Keys count = %d, want %d", len(loaded.Keys), len(secret.Keys))
	}
	for i := range loaded.Keys {
		if loaded.Keys[i] != secret.Keys[i] {
			t.Errorf("Keys[%d] = %q, want %q", i, loaded.Keys[i], secret.Keys[i])
		}
	}
	if len(loaded.KeysBase64) != len(secret.KeysBase64) {
		t.Errorf("KeysBase64 count = %d, want %d", len(loaded.KeysBase64), len(secret.KeysBase64))
	}
	for i := range loaded.KeysBase64 {
		if loaded.KeysBase64[i] != secret.KeysBase64[i] {
			t.Errorf("KeysBase64[%d] = %q, want %q", i, loaded.KeysBase64[i], secret.KeysBase64[i])
		}
	}

	// Verify the secret was cached via SetLoadedGenerationSecret
	if cfg.GetLoadedGenerationSecret() == nil {
		t.Fatal("expected loadedGenerationSecret to be cached, got nil")
	}
	if cfg.GetLoadedGenerationSecret().RootToken != secret.RootToken {
		t.Errorf("cached RootToken = %q, want %q", cfg.GetLoadedGenerationSecret().RootToken, secret.RootToken)
	}
}

func TestLoadGenerationSecret_SecretNotFound(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-999",
	}

	// No secret created — should get a "not found" error
	_, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for missing secret, got nil")
	}

	if !contains(err.Error(), "not found") {
		t.Errorf("expected error to mention 'not found', got: %v", err)
	}
}

func TestLoadGenerationSecret_EmptyCurrentKeySecret(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "", // empty
	}

	_, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for empty CurrentKeySecret, got nil")
	}

	if !contains(err.Error(), "generation secret name is empty") {
		t.Errorf("expected error to mention 'generation secret name is empty', got: %v", err)
	}
}

func TestLoadGenerationSecret_MalformedJSON(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	// Create a secret with invalid JSON in the "data" field
	createK8sSecretFromRawData(t, clientset, "openbao", "openbao-unseal-gen-001", []byte("{not valid json"))

	_, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for malformed JSON, got nil")
	}

	if !contains(err.Error(), "failed to unmarshal") {
		t.Errorf("expected error to mention 'failed to unmarshal', got: %v", err)
	}
}

func TestLoadGenerationSecret_WrongKeyCount(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	// Create a secret with mismatched key/base64 lengths (invalid)
	badSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"key0", "key1", "key2"},
		KeysBase64: []string{"a2V5MA==", "a2V5MQ=="},
		RootToken:  "s.roottoken123",
	}
	createK8sSecretFromGeneration(t, clientset, "openbao", "openbao-unseal-gen-001", badSecret)

	_, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for mismatched key lengths, got nil")
	}

	if !contains(err.Error(), "failed validation") {
		t.Errorf("expected error to mention 'failed validation', got: %v", err)
	}
}

func TestLoadGenerationSecret_EmptyRootToken(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	// Create a secret with empty root token
	badSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"key0", "key1", "key2", "key3", "key4"},
		KeysBase64: []string{"a2V5MA==", "a2V5MQ==", "a2V5Mg==", "a2V5Mw==", "a2V5NA=="},
		RootToken:  "", // empty
	}
	createK8sSecretFromGeneration(t, clientset, "openbao", "openbao-unseal-gen-001", badSecret)

	_, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for empty root token, got nil")
	}

	if !contains(err.Error(), "failed validation") {
		t.Errorf("expected error to mention 'failed validation', got: %v", err)
	}
}

func TestLoadGenerationSecret_NoDataField(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	// Create a secret with no "data" key (use a different field name)
	immutable := true
	k8sSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      "openbao-unseal-gen-001",
			Namespace: "openbao",
		},
		Immutable: &immutable,
		Data: map[string][]byte{
			"wrong-key": []byte(`{"keys":["k"],"keys_base64":["a"],"root_token":"t"}`),
		},
	}

	ctx := context.Background()
	_, err := clientset.CoreV1().Secrets("openbao").Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create test secret: %v", err)
	}

	_, err = cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err == nil {
		t.Fatal("expected error for missing 'data' field, got nil")
	}

	if !contains(err.Error(), "no 'data' field") {
		t.Errorf("expected error to mention \"no 'data' field\", got: %v", err)
	}
}

func TestLoadGenerationSecret_DefaultNamespace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "", // empty — should use default "openbao"
		GenerationPrefix: "openbao-unseal-gen",
		CurrentKeySecret: "openbao-unseal-gen-001",
	}

	secret := validTestSecret()
	createK8sSecretFromGeneration(t, clientset, "openbao", "openbao-unseal-gen-001", secret)

	loaded, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if loaded.RootToken != secret.RootToken {
		t.Errorf("RootToken = %q, want %q", loaded.RootToken, secret.RootToken)
	}
}
