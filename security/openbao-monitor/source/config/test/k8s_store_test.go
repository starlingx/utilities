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

// validTestSecret returns a GenerationSecret with valid test data (5 keys).
func validTestSecret() *baoConfig.GenerationSecret {
	return &baoConfig.GenerationSecret{
		Keys:       []string{"key0", "key1", "key2", "key3", "key4"},
		KeysBase64: []string{"a2V5MA==", "a2V5MQ==", "a2V5Mg==", "a2V5Mw==", "a2V5NA=="},
		RootToken:  "s.roottoken123",
	}
}

func TestStoreGenerationSecret_NormalCreation(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	secret := validTestSecret()
	genName := "openbao-unseal-gen-001"

	err := cfg.StoreGenerationSecret(genName, secret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify CurrentKeySecret was updated
	if cfg.CurrentKeySecret != genName {
		t.Errorf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, genName)
	}

	// Verify the secret was created in k8s
	ctx := context.Background()
	k8sSecret, err := clientset.CoreV1().Secrets("openbao").Get(ctx, genName, metaV1.GetOptions{})
	if err != nil {
		t.Fatalf("failed to get created secret: %v", err)
	}

	// Verify immutable is set
	if k8sSecret.Immutable == nil || !*k8sSecret.Immutable {
		t.Error("expected secret to be immutable")
	}

	// Verify labels
	expectedLabels := map[string]string{
		"app":        "openbao",
		"component":  "unseal-keys",
		"generation": "001",
	}
	for key, expected := range expectedLabels {
		if got := k8sSecret.Labels[key]; got != expected {
			t.Errorf("label %q = %q, want %q", key, got, expected)
		}
	}

	// Verify data can be deserialized back to GenerationSecret
	rawData, ok := k8sSecret.Data["data"]
	if !ok {
		t.Fatal("secret has no 'data' key")
	}

	var stored baoConfig.GenerationSecret
	if err := json.Unmarshal(rawData, &stored); err != nil {
		t.Fatalf("failed to unmarshal stored data: %v", err)
	}

	if stored.RootToken != secret.RootToken {
		t.Errorf("stored RootToken = %q, want %q", stored.RootToken, secret.RootToken)
	}
	if len(stored.Keys) != len(secret.Keys) {
		t.Errorf("stored Keys count = %d, want %d", len(stored.Keys), len(secret.Keys))
	}
	for i := range stored.Keys {
		if stored.Keys[i] != secret.Keys[i] {
			t.Errorf("stored Keys[%d] = %q, want %q", i, stored.Keys[i], secret.Keys[i])
		}
	}
}

func TestStoreGenerationSecret_AlreadyExistsSameData(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	secret := validTestSecret()
	genName := "openbao-unseal-gen-001"

	// Pre-create the secret with identical data (simulating a retry scenario)
	data, err := json.Marshal(secret)
	if err != nil {
		t.Fatalf("failed to marshal secret: %v", err)
	}

	immutable := true
	existingSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      genName,
			Namespace: "openbao",
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
	_, err = clientset.CoreV1().Secrets("openbao").Create(ctx, existingSecret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to pre-create secret: %v", err)
	}

	// Now call StoreGenerationSecret — should succeed (idempotent)
	err = cfg.StoreGenerationSecret(genName, secret)
	if err != nil {
		t.Fatalf("expected success for identical data, got error: %v", err)
	}

	// Verify CurrentKeySecret was updated
	if cfg.CurrentKeySecret != genName {
		t.Errorf("CurrentKeySecret = %q, want %q", cfg.CurrentKeySecret, genName)
	}
}

func TestStoreGenerationSecret_AlreadyExistsDifferentData(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	secret := validTestSecret()
	genName := "openbao-unseal-gen-001"

	// Pre-create the secret with DIFFERENT data (simulating corruption/conflict)
	differentSecret := &baoConfig.GenerationSecret{
		Keys:       []string{"other0", "other1", "other2", "other3", "other4"},
		KeysBase64: []string{"b3RoZXIw", "b3RoZXIx", "b3RoZXIy", "b3RoZXIz", "b3RoZXI0"},
		RootToken:  "s.differentroot",
	}
	differentData, err := json.Marshal(differentSecret)
	if err != nil {
		t.Fatalf("failed to marshal different secret: %v", err)
	}

	immutable := true
	existingSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      genName,
			Namespace: "openbao",
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": "001",
			},
		},
		Immutable: &immutable,
		Data: map[string][]byte{
			"data": differentData,
		},
	}

	ctx := context.Background()
	_, err = clientset.CoreV1().Secrets("openbao").Create(ctx, existingSecret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to pre-create secret: %v", err)
	}

	// Now call StoreGenerationSecret — should fail
	err = cfg.StoreGenerationSecret(genName, secret)
	if err == nil {
		t.Fatal("expected error for different data, got nil")
	}

	// Verify the error mentions corruption/conflict
	if !contains(err.Error(), "different data") {
		t.Errorf("expected error to mention 'different data', got: %v", err)
	}

	// Verify CurrentKeySecret was NOT updated
	if cfg.CurrentKeySecret == genName {
		t.Error("CurrentKeySecret should not be updated on conflict")
	}
}

func TestStoreGenerationSecret_DefaultNamespace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "", // empty — should use default "openbao"
		GenerationPrefix: "openbao-unseal-gen",
	}

	secret := validTestSecret()
	genName := "openbao-unseal-gen-001"

	err := cfg.StoreGenerationSecret(genName, secret)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Verify the secret was created in the default namespace
	ctx := context.Background()
	_, err = clientset.CoreV1().Secrets("openbao").Get(ctx, genName, metaV1.GetOptions{})
	if err != nil {
		t.Fatalf("secret not found in default namespace 'openbao': %v", err)
	}
}

func TestStoreGenerationSecret_SeqNumLabel(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	secret := validTestSecret()

	tests := []struct {
		genName     string
		expectedSeq string
	}{
		{"openbao-unseal-gen-001", "001"},
		{"openbao-unseal-gen-042", "042"},
		{"openbao-unseal-gen-100", "100"},
	}

	for _, tt := range tests {
		t.Run(tt.genName, func(t *testing.T) {
			err := cfg.StoreGenerationSecret(tt.genName, secret)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			ctx := context.Background()
			k8sSecret, err := clientset.CoreV1().Secrets("openbao").Get(ctx, tt.genName, metaV1.GetOptions{})
			if err != nil {
				t.Fatalf("failed to get secret: %v", err)
			}

			if got := k8sSecret.Labels["generation"]; got != tt.expectedSeq {
				t.Errorf("generation label = %q, want %q", got, tt.expectedSeq)
			}
		})
	}
}
