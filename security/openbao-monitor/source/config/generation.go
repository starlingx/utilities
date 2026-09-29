//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"log/slog"
	"reflect"
	"sort"
	"strconv"
	"strings"
	"time"

	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// DefaultGenerationPrefix is the default naming prefix for generation secrets.
const DefaultGenerationPrefix = "openbao-unseal-gen"

// DefaultCurrentKeyPointerName is the default name of the mutable Kubernetes
// secret that records which generation secret is currently active. Its payload
// holds the name of the active generation secret (e.g. "openbao-unseal-gen-001").
const DefaultCurrentKeyPointerName = "openbao-unseal-current"

// pointerUpdateMaxAttempts bounds retries when updating the current-key pointer.
const pointerUpdateMaxAttempts = 3

// DefaultStoreMaxAttempts bounds retries when storing + verifying a generation secret.
const DefaultStoreMaxAttempts = 3

// GenerationSecret represents the single-document secret format containing
// all Shamir unseal key shards and root token for one key generation event.
type GenerationSecret struct {
	Keys       []string `json:"keys"`
	KeysBase64 []string `json:"keys_base64"`
	RootToken  string   `json:"root_token"`
}

// ValidateGenerationSecret checks the structural integrity of a GenerationSecret.
func ValidateGenerationSecret(secret *GenerationSecret) error {
	if secret == nil {
		return fmt.Errorf("generation secret is nil")
	}
	if len(secret.Keys) == 0 {
		return fmt.Errorf("keys array is empty")
	}
	if len(secret.KeysBase64) != len(secret.Keys) {
		return fmt.Errorf("keys_base64 length (%d) does not match keys length (%d)",
			len(secret.KeysBase64), len(secret.Keys))
	}

	seen := make(map[string]struct{}, len(secret.Keys))
	for i := range secret.Keys {
		if secret.Keys[i] == "" || secret.KeysBase64[i] == "" {
			return fmt.Errorf("key pair %d is empty", i)
		}

		raw, err := hex.DecodeString(secret.Keys[i])
		if err != nil {
			return fmt.Errorf("key # %d is not a valid hexadecimal: %w", i, err)
		}

		encoded, err := base64.StdEncoding.DecodeString(secret.KeysBase64[i])
		if err != nil {
			return fmt.Errorf("base64 key # %d is not a valid base64 encoded key: %w", i, err)
		}

		if !bytes.Equal(raw, encoded) {
			return fmt.Errorf("key pair %d does not match", i)
		}

		fingerprint := string(raw)
		if _, exists := seen[fingerprint]; exists {
			return fmt.Errorf("key pair %d is a duplicate", i)
		}
		seen[fingerprint] = struct{}{}
	}

	if secret.RootToken == "" {
		return fmt.Errorf("root_token is empty")
	}
	return nil
}

// ExtractSeqNum parses the sequence number suffix from a generation secret name.
// For example, "openbao-unseal-gen-003" returns "003".
func ExtractSeqNum(genName string) string {
	lastDash := strings.LastIndex(genName, "-")
	if lastDash == -1 || lastDash == len(genName)-1 {
		return ""
	}
	return genName[lastDash+1:]
}

// ListGenerationSecrets returns all generation secret names in the namespace
// that match the configured generation prefix, sorted by sequence number.
// Uses c.Clientset which must be set before calling.
func (c *MonitorConfig) ListGenerationSecrets() ([]string, error) {
	if c.Clientset == nil {
		return nil, fmt.Errorf("clientset is nil: K8s client not initialized")
	}

	namespace := c.GetNamespace()

	prefix := c.GetGenerationPrefix()
	slog.Debug("Listing generation secrets", "namespace", namespace, "prefix", prefix)

	ctx, cancel := getK8sContextWithTimeout(nil)
	defer cancel()
	secrets, err := c.Clientset.CoreV1().Secrets(namespace).List(
		ctx, metaV1.ListOptions{
			LabelSelector: "app=openbao,component=unseal-keys",
		})
	if err != nil {
		return nil, fmt.Errorf("failed to list generation secrets: %w", err)
	}

	var genNames []string
	for _, secret := range secrets.Items {
		name := secret.ObjectMeta.Name
		if strings.HasPrefix(name, prefix+"-") {
			// Only include secrets whose suffix after the last dash is numeric.
			// This filters out secrets that share the prefix but have non-numeric
			// suffixes (e.g. manually created or unrelated secrets).
			seq := ExtractSeqNum(name)
			if _, err := strconv.Atoi(seq); err != nil {
				slog.Debug("Skipping secret with non-numeric suffix", "name", name, "suffix", seq)
				continue
			}
			genNames = append(genNames, name)
		}
	}

	sort.Slice(genNames, func(i, j int) bool {
		seqI, _ := strconv.Atoi(ExtractSeqNum(genNames[i]))
		seqJ, _ := strconv.Atoi(ExtractSeqNum(genNames[j]))
		return seqI < seqJ
	})

	return genNames, nil
}

// NextGenerationName computes the next generation secret name by finding the
// highest existing sequence number and incrementing it.
// Note: %03d zero-padding is cosmetic for human readability. If the sequence
// exceeds 999, names like "gen-1000" are produced — this is fine because
// ListGenerationSecrets sorts by integer value (strconv.Atoi), not
// lexicographically. Non-padded names also sort correctly.
func (c *MonitorConfig) NextGenerationName() (string, error) {
	existing, err := c.ListGenerationSecrets()
	if err != nil {
		return "", fmt.Errorf("failed to list generation secrets: %w", err)
	}

	prefix := c.GetGenerationPrefix()
	if len(existing) == 0 {
		return fmt.Sprintf("%s-%03d", prefix, 1), nil
	}

	lastGen := existing[len(existing)-1]
	seqStr := ExtractSeqNum(lastGen)
	seq, err := strconv.Atoi(seqStr)
	if err != nil {
		return "", fmt.Errorf("failed to parse sequence number from %q: %w", lastGen, err)
	}

	return fmt.Sprintf("%s-%03d", prefix, seq+1), nil
}

// GetGenerationPrefix returns the configured GenerationPrefix, falling back
// to the DefaultGenerationPrefix when the config value is empty.
func (c *MonitorConfig) GetGenerationPrefix() string {
	if c.GenerationPrefix == "" {
		return DefaultGenerationPrefix
	}
	return c.GenerationPrefix
}

func (c *MonitorConfig) ActivateGeneration(name string, loadSecret *GenerationSecret) error {
	if name == "" {
		return fmt.Errorf("cannot activate an empty generation name")
	}
	if loadSecret == nil {
		var err error
		loadSecret, err = c.LoadGenerationSecret(name)
		if err != nil {
			return fmt.Errorf("cannot activate generation %q: %w", name, err)
		}
	} else if err := ValidateGenerationSecret(loadSecret); err != nil {
		return fmt.Errorf("cannot activate invalid generation %q: %w", name, err)
	}

	var lastErr error
	for attempt := 1; attempt <= pointerUpdateMaxAttempts; attempt++ {
		lastErr = c.StoreCurrentKeyPointer(name)
		if lastErr == nil {
			break
		}

		// A timeout may be returned after Kubernetes commited the write. Read the pointer
		// before repeating the idempotent update
		if current, err := c.LoadCurrentKeyPointer(); err == nil && current == name {
			lastErr = nil
			break
		}
		if !IsTransientK8sError(lastErr) {
			break
		}
		if attempt < pointerUpdateMaxAttempts {
			time.Sleep(time.Duration(attempt) * time.Second)
		}
	}
	if lastErr != nil {
		return fmt.Errorf("failed to update current key pointer to %q after %d attempts: %w",
			name, pointerUpdateMaxAttempts, lastErr)
	}
	c.CurrentKeySecret = name
	c.SetLoadedGenerationSecret(loadSecret)
	return nil
}

// StoreAndVerifyGeneration stores a generation secret with retry on transient
// K8s failures and performs a read-back verification to confirm persistence.
// Returns the generation name on success. This is the single implementation
// used by both the init CLI command and the run-loop startup path.
func (c *MonitorConfig) StoreAndVerifyGeneration(genSecret *GenerationSecret, minShares int) (string, error) {
	genName, err := c.NextGenerationName()
	if err != nil {
		return "", fmt.Errorf("computing next generation name: %w", err)
	}

	if err := c.StoreAndVerifyGenerationAtName(genName, genSecret, minShares, DefaultStoreMaxAttempts); err != nil {
		return "", err
	}

	return genName, nil
}

func (c *MonitorConfig) StoreAndVerifyGenerationAtName(genName string, genSecret *GenerationSecret, minShares, maxAttempts int) error {
	if genName == "" {
		return fmt.Errorf("cannot store a generation with an empty name")
	}
	if maxAttempts < 1 {
		return fmt.Errorf("store attempts must be at least 1")
	}
	if err := ValidateGenerationSecret(genSecret); err != nil {
		return fmt.Errorf("invalid generation secret %s: %w", genName, err)
	}
	if len(genSecret.Keys) < minShares {
		return fmt.Errorf("generation %s has %d keys, below minimum %d", genName, len(genSecret.Keys), minShares)
	}

	var storeErr error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		storeErr = c.StoreGenerationSecret(genName, genSecret)
		if storeErr == nil || !IsTransientK8sError(storeErr) {
			break
		}
		if attempt < maxAttempts {
			time.Sleep(time.Duration(attempt) * 2 * time.Second)
		}
	}
	if storeErr != nil {
		return fmt.Errorf("storing generation secret %s after %d attempts: %w",
			genName, maxAttempts, storeErr)
	}

	var stored *GenerationSecret
	var err error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		stored, err = c.LoadGenerationSecret(genName)
		if err == nil || !IsTransientK8sError(err) {
			break
		}
		if attempt < maxAttempts {
			time.Sleep(time.Duration(attempt) * 2 * time.Second)
		}
	}
	if err != nil {
		return fmt.Errorf("verification read for %s: stored but cannot retrieve: %w", genName, err)
	}
	if err := ValidateGenerationSecret(stored); err != nil {
		return fmt.Errorf("verification read for %s is invalid: %w", genName, err)
	}
	if !reflect.DeepEqual(stored, genSecret) {
		return fmt.Errorf("stored generation differs from requested generation %s", genName)
	}

	return nil
}
