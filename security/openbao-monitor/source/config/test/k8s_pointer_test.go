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

// getPointerCurrent reads the pointer secret directly from the fake clientset
// and returns the generation name it references.
func getPointerCurrent(t *testing.T, clientset *fake.Clientset, namespace, pointerName string) string {
	t.Helper()
	ctx := context.Background()
	secret, err := clientset.CoreV1().Secrets(namespace).Get(ctx, pointerName, metaV1.GetOptions{})
	if err != nil {
		t.Fatalf("failed to read pointer secret %q: %v", pointerName, err)
	}
	raw, ok := secret.Data["data"]
	if !ok {
		t.Fatalf("pointer secret %q has no 'data' field", pointerName)
	}
	var payload struct {
		Current string `json:"current"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		t.Fatalf("failed to unmarshal pointer payload: %v", err)
	}
	return payload.Current
}

func TestStoreCurrentKeyPointer_Create(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	if err := cfg.StoreCurrentKeyPointer("openbao-unseal-gen-001"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	pointerName := cfg.GetCurrentKeyPointerName()
	if got := getPointerCurrent(t, clientset, "openbao", pointerName); got != "openbao-unseal-gen-001" {
		t.Errorf("pointer current = %q, want %q", got, "openbao-unseal-gen-001")
	}

	// Verify the pointer secret is mutable (Immutable not set true) and labeled.
	ctx := context.Background()
	secret, err := clientset.CoreV1().Secrets("openbao").Get(ctx, pointerName, metaV1.GetOptions{})
	if err != nil {
		t.Fatalf("failed to get pointer secret: %v", err)
	}
	if secret.Immutable != nil && *secret.Immutable {
		t.Error("pointer secret should be mutable, got Immutable=true")
	}
	if secret.Labels["component"] != "unseal-keys-pointer" {
		t.Errorf("component label = %q, want %q", secret.Labels["component"], "unseal-keys-pointer")
	}
}

func TestStoreCurrentKeyPointer_UpdateInPlace(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	if err := cfg.StoreCurrentKeyPointer("openbao-unseal-gen-001"); err != nil {
		t.Fatalf("unexpected error on create: %v", err)
	}
	// Overwrite in place to a new generation.
	if err := cfg.StoreCurrentKeyPointer("openbao-unseal-gen-002"); err != nil {
		t.Fatalf("unexpected error on update: %v", err)
	}

	pointerName := cfg.GetCurrentKeyPointerName()
	if got := getPointerCurrent(t, clientset, "openbao", pointerName); got != "openbao-unseal-gen-002" {
		t.Errorf("pointer current = %q, want %q", got, "openbao-unseal-gen-002")
	}

	// There should be exactly one pointer secret (updated, not duplicated).
	ctx := context.Background()
	list, err := clientset.CoreV1().Secrets("openbao").List(ctx, metaV1.ListOptions{
		LabelSelector: "component=unseal-keys-pointer",
	})
	if err != nil {
		t.Fatalf("failed to list pointer secrets: %v", err)
	}
	if len(list.Items) != 1 {
		t.Errorf("expected exactly 1 pointer secret, got %d", len(list.Items))
	}
}

func TestStoreCurrentKeyPointer_EmptyGenName(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	err := cfg.StoreCurrentKeyPointer("")
	if err == nil {
		t.Fatal("expected error for empty generation name, got nil")
	}
	if !contains(err.Error(), "generation name is empty") {
		t.Errorf("expected error to mention 'generation name is empty', got: %v", err)
	}
}

func TestLoadCurrentKeyPointer_RoundTrip(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	if err := cfg.StoreCurrentKeyPointer("openbao-unseal-gen-003"); err != nil {
		t.Fatalf("unexpected error storing pointer: %v", err)
	}

	got, err := cfg.LoadCurrentKeyPointer()
	if err != nil {
		t.Fatalf("unexpected error loading pointer: %v", err)
	}
	if got != "openbao-unseal-gen-003" {
		t.Errorf("loaded pointer = %q, want %q", got, "openbao-unseal-gen-003")
	}
}

func TestLoadCurrentKeyPointer_NotFoundReturnsEmpty(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}

	// No pointer secret exists — should return ("", nil), not an error.
	got, err := cfg.LoadCurrentKeyPointer()
	if err != nil {
		t.Fatalf("expected nil error for missing pointer, got: %v", err)
	}
	if got != "" {
		t.Errorf("expected empty string for missing pointer, got %q", got)
	}
}

func TestLoadCurrentKeyPointer_MalformedJSON(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}
	pointerName := cfg.GetCurrentKeyPointerName()

	// Pre-create the pointer secret with invalid JSON in the "data" field.
	ctx := context.Background()
	badSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      pointerName,
			Namespace: "openbao",
		},
		Data: map[string][]byte{
			"data": []byte("{not valid json"),
		},
	}
	if _, err := clientset.CoreV1().Secrets("openbao").Create(ctx, badSecret, metaV1.CreateOptions{}); err != nil {
		t.Fatalf("failed to pre-create malformed pointer: %v", err)
	}

	_, err := cfg.LoadCurrentKeyPointer()
	if err == nil {
		t.Fatal("expected error for malformed pointer JSON, got nil")
	}
	if !contains(err.Error(), "failed to unmarshal") {
		t.Errorf("expected error to mention 'failed to unmarshal', got: %v", err)
	}
}

func TestLoadCurrentKeyPointer_EmptyCurrentIsError(t *testing.T) {
	clientset := fake.NewSimpleClientset()
	cfg := &baoConfig.MonitorConfig{
		Clientset: clientset,
		Namespace: "openbao",
	}
	pointerName := cfg.GetCurrentKeyPointerName()

	// Pointer secret exists but references an empty generation name.
	ctx := context.Background()
	data, _ := json.Marshal(struct {
		Current string `json:"current"`
	}{Current: ""})
	emptySecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      pointerName,
			Namespace: "openbao",
		},
		Data: map[string][]byte{
			"data": data,
		},
	}
	if _, err := clientset.CoreV1().Secrets("openbao").Create(ctx, emptySecret, metaV1.CreateOptions{}); err != nil {
		t.Fatalf("failed to pre-create empty pointer: %v", err)
	}

	_, err := cfg.LoadCurrentKeyPointer()
	if err == nil {
		t.Fatal("expected error for empty current generation name, got nil")
	}
	if !contains(err.Error(), "empty generation name") {
		t.Errorf("expected error to mention 'empty generation name', got: %v", err)
	}
}

func TestGetCurrentKeyPointerName_Default(t *testing.T) {
	cfg := &baoConfig.MonitorConfig{}
	if got := cfg.GetCurrentKeyPointerName(); got != baoConfig.DefaultCurrentKeyPointerName {
		t.Errorf("default pointer name = %q, want %q", got, baoConfig.DefaultCurrentKeyPointerName)
	}

	cfg.CurrentKeyPointerName = "custom-pointer"
	if got := cfg.GetCurrentKeyPointerName(); got != "custom-pointer" {
		t.Errorf("configured pointer name = %q, want %q", got, "custom-pointer")
	}
}
