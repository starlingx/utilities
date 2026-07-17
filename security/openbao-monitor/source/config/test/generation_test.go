//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig_test

import (
	"context"
	"testing"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"

	v1 "k8s.io/api/core/v1"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
	"k8s.io/client-go/rest"
)

// newFakeRestConfig returns a dummy rest.Config. The fake clientset doesn't use
// it, but our functions require one. We override the clientset creation in tests
// by using a helper that accepts a kubernetes.Interface.
func newFakeRestConfig() *rest.Config {
	return &rest.Config{Host: "https://fake:6443"}
}

// createFakeGenSecret creates a generation secret in the fake clientset with
// the proper labels for listing.
func createFakeGenSecret(t *testing.T, clientset *fake.Clientset, namespace, name, seqNum string) {
	t.Helper()
	secret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      name,
			Namespace: namespace,
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": seqNum,
			},
		},
		Data: map[string][]byte{
			"data": []byte(`{"keys":["a","b","c","d","e"],"keys_base64":["YQ==","Yg==","Yw==","ZA==","ZQ=="],"root_token":"s.root123"}`),
		},
	}
	_, err := clientset.CoreV1().Secrets(namespace).Create(
		context.Background(), secret, metaV1.CreateOptions{})
	if err != nil {
		t.Fatalf("failed to create fake secret %s: %v", name, err)
	}
}

func TestExtractSeqNum(t *testing.T) {
	tests := []struct {
		name     string
		input    string
		expected string
	}{
		{"standard gen name", "openbao-unseal-gen-001", "001"},
		{"higher number", "openbao-unseal-gen-042", "042"},
		{"custom prefix", "my-prefix-123", "123"},
		{"no hyphen", "nohyphen", ""},
		{"trailing hyphen", "name-", ""},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := baoConfig.ExtractSeqNum(tt.input)
			if result != tt.expected {
				t.Errorf("baoConfig.ExtractSeqNum(%q) = %q, want %q", tt.input, result, tt.expected)
			}
		})
	}
}

func TestValidateGenerationSecret(t *testing.T) {
	tests := []struct {
		name      string
		secret    *baoConfig.GenerationSecret
		expectErr bool
		errSubstr string
	}{
		{
			name: "valid secret",
			secret: &baoConfig.GenerationSecret{
				Keys:       []string{"k1", "k2", "k3", "k4", "k5"},
				KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
				RootToken:  "s.roottoken",
			},
			expectErr: false,
		},
		{
			name:      "nil secret",
			secret:    nil,
			expectErr: true,
			errSubstr: "nil",
		},
		{
			name: "wrong key count",
			secret: &baoConfig.GenerationSecret{
				Keys:       []string{"k1", "k2", "k3"},
				KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
				RootToken:  "s.roottoken",
			},
			expectErr: true,
			errSubstr: "keys_base64 length (5) does not match keys length (3)",
		},
		{
			name: "wrong keys_base64 count",
			secret: &baoConfig.GenerationSecret{
				Keys:       []string{"k1", "k2", "k3", "k4", "k5"},
				KeysBase64: []string{"b1", "b2"},
				RootToken:  "s.roottoken",
			},
			expectErr: true,
			errSubstr: "keys_base64 length (2) does not match keys length (5)",
		},
		{
			name: "empty root token",
			secret: &baoConfig.GenerationSecret{
				Keys:       []string{"k1", "k2", "k3", "k4", "k5"},
				KeysBase64: []string{"b1", "b2", "b3", "b4", "b5"},
				RootToken:  "",
			},
			expectErr: true,
			errSubstr: "root_token is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := baoConfig.ValidateGenerationSecret(tt.secret)
			if tt.expectErr && err == nil {
				t.Errorf("expected error containing %q, got nil", tt.errSubstr)
			}
			if !tt.expectErr && err != nil {
				t.Errorf("expected no error, got %v", err)
			}
			if tt.expectErr && err != nil && tt.errSubstr != "" {
				if !contains(err.Error(), tt.errSubstr) {
					t.Errorf("expected error to contain %q, got %q", tt.errSubstr, err.Error())
				}
			}
		})
	}
}

func TestGetGenerationPrefix(t *testing.T) {
	t.Run("empty uses default", func(t *testing.T) {
		cfg := &baoConfig.MonitorConfig{GenerationPrefix: ""}
		if got := cfg.GetGenerationPrefix(); got != baoConfig.DefaultGenerationPrefix {
			t.Errorf("getGenerationPrefix() = %q, want %q", got, baoConfig.DefaultGenerationPrefix)
		}
	})

	t.Run("custom prefix", func(t *testing.T) {
		cfg := &baoConfig.MonitorConfig{GenerationPrefix: "my-custom-gen"}
		if got := cfg.GetGenerationPrefix(); got != "my-custom-gen" {
			t.Errorf("getGenerationPrefix() = %q, want %q", got, "my-custom-gen")
		}
	})
}

func TestListGenerationSecrets_EmptyNamespace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	// Override the kubernetes.NewForConfig by using the cfg.ListGenerationSecretsWithClientset helper
	names, err := cfg.ListGenerationSecrets()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(names) != 0 {
		t.Errorf("expected empty list, got %v", names)
	}
}

func TestListGenerationSecrets_MultipleSecrets(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	// Create secrets out of order to verify sorting
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-003", "003")
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-001", "001")
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-002", "002")

	names, err := cfg.ListGenerationSecrets()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(names) != 3 {
		t.Fatalf("expected 3 secrets, got %d: %v", len(names), names)
	}

	// Verify ascending order
	expected := []string{"openbao-unseal-gen-001", "openbao-unseal-gen-002", "openbao-unseal-gen-003"}
	for i, name := range names {
		if name != expected[i] {
			t.Errorf("position %d: got %q, want %q", i, name, expected[i])
		}
	}
}

func TestNextGenerationName_EmptyNamespace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	name, err := cfg.NextGenerationName()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if name != "openbao-unseal-gen-001" {
		t.Errorf("expected openbao-unseal-gen-001, got %q", name)
	}
}

func TestNextGenerationName_ExistingGen002(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-001", "001")
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-002", "002")

	name, err := cfg.NextGenerationName()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if name != "openbao-unseal-gen-003" {
		t.Errorf("expected openbao-unseal-gen-003, got %q", name)
	}
}

func TestNextGenerationName_DefaultPrefix(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "", // should use default
	}

	name, err := cfg.NextGenerationName()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if name != "openbao-unseal-gen-001" {
		t.Errorf("expected openbao-unseal-gen-001, got %q", name)
	}
}

func TestListGenerationSecrets_IgnoresNonMatchingSecrets(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	// Create a gen secret with matching labels
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-001", "001")

	// Create a non-gen secret that has the labels but wrong prefix
	secret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      "some-other-secret",
			Namespace: "openbao",
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": "999",
			},
		},
	}
	_, _ = clientset.CoreV1().Secrets("openbao").Create(
		context.Background(), secret, metaV1.CreateOptions{})

	names, err := cfg.ListGenerationSecrets()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(names) != 1 {
		t.Errorf("expected 1 secret, got %d: %v", len(names), names)
	}
	if names[0] != "openbao-unseal-gen-001" {
		t.Errorf("expected openbao-unseal-gen-001, got %q", names[0])
	}
}

func TestListGenerationSecrets_IgnoresNonNumericSuffix(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset:        clientset,
		Namespace:        "openbao",
		GenerationPrefix: "openbao-unseal-gen",
	}

	// Valid generation secrets
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-001", "001")
	createFakeGenSecret(t, clientset, "openbao", "openbao-unseal-gen-002", "002")

	// Secrets with matching prefix but non-numeric suffix — should be filtered out
	for _, badName := range []string{
		"openbao-unseal-gen-abc",
		"openbao-unseal-gen-",
		"openbao-unseal-gen-01x",
	} {
		secret := &v1.Secret{
			ObjectMeta: metaV1.ObjectMeta{
				Name:      badName,
				Namespace: "openbao",
				Labels: map[string]string{
					"app":       "openbao",
					"component": "unseal-keys",
				},
			},
		}
		_, _ = clientset.CoreV1().Secrets("openbao").Create(
			context.Background(), secret, metaV1.CreateOptions{})
	}

	names, err := cfg.ListGenerationSecrets()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(names) != 2 {
		t.Errorf("expected 2 secrets (only numeric suffixes), got %d: %v", len(names), names)
	}
}

// Helper: contains checks if s contains substr
func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsSubstring(s, substr))
}

func containsSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
