//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"strings"

	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// DefaultGenerationPrefix is the default naming prefix for generation secrets.
const DefaultGenerationPrefix = "openbao-unseal-gen"

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

	namespace := c.Namespace
	if namespace == "" {
		namespace = k8sNamespace
	}

	prefix := c.GetGenerationPrefix()
	slog.Debug("Listing generation secrets", "namespace", namespace, "prefix", prefix)

	secrets, err := c.Clientset.CoreV1().Secrets(namespace).List(
		context.Background(), metaV1.ListOptions{
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
