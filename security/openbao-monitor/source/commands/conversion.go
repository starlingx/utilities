//
// Copyright (c) 2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/spf13/cobra"
	v1 "k8s.io/api/core/v1"
	k8sErrors "k8s.io/apimachinery/pkg/api/errors"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	coreV1Client "k8s.io/client-go/kubernetes/typed/core/v1"
)

// expectedLegacyShardCount is the number of unseal key shards expected
// in the legacy per-shard secret format.
const expectedLegacyShardCount = 5

// k8sCallTimeout bounds each Kubernetes API call made by the conversion
// command so a hung or unreachable API server cannot block the operator
// indefinitely.
const k8sCallTimeout = 5 * time.Second

// getSecretWithTimeout fetches a single secret with a bounded, per-call
// timeout. Every Kubernetes Get in the conversion command routes through
// here so a hung or unreachable API server cannot block indefinitely, and
// each call gets its own fresh deadline (loops do not share one budget).
func getSecretWithTimeout(secretClient coreV1Client.SecretInterface, name string) (*v1.Secret, error) {
	ctx, cancel := context.WithTimeout(context.Background(), k8sCallTimeout)
	defer cancel()
	return secretClient.Get(ctx, name, metaV1.GetOptions{})
}

// secretExists reports whether a named secret exists in the namespace. It
// distinguishes genuine absence (NotFound -> false, nil) from other API errors
// (which are returned), so callers can tell "does not exist yet" apart from
// "exists but could not be validated".
func secretExists(clientset kubernetes.Interface, namespace, name string) (bool, error) {
	_, err := getSecretWithTimeout(clientset.CoreV1().Secrets(namespace), name)
	if err != nil {
		if k8sErrors.IsNotFound(err) {
			return false, nil
		}
		return false, fmt.Errorf("failed to get secret %q: %w", name, err)
	}
	return true, nil
}

// DetectLegacySecretsWithClientset checks if old-format secrets exist
// (cluster-key-N pattern). It looks for secrets named {prefix}-0 through
// {prefix}-4 and {prefix}-root, and returns true only if ALL expected legacy
// secrets are found. A kubernetes.Interface is accepted so unit tests can pass
// a fake clientset.
func DetectLegacySecretsWithClientset(clientset kubernetes.Interface, namespace, prefix string) (bool, error) {
	if namespace == "" {
		namespace = "openbao"
		slog.Warn("Namespace not provided to legacy secret detection, using default",
			"namespace", namespace)
	}

	secretClient := clientset.CoreV1().Secrets(namespace)

	// Check for shard secrets {prefix}-0 through {prefix}-4
	for i := 0; i < expectedLegacyShardCount; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		if _, err := getSecretWithTimeout(secretClient, name); err != nil {
			slog.Debug("Legacy secret not found", "name", name)
			return false, nil
		}
	}

	// Check for root token secret {prefix}-root
	rootName := fmt.Sprintf("%s-root", prefix)
	if _, err := getSecretWithTimeout(secretClient, rootName); err != nil {
		slog.Debug("Legacy root token secret not found", "name", rootName)
		return false, nil
	}

	slog.Info("All legacy secrets detected", "prefix", prefix)
	return true, nil
}

// MigrateLegacySecretsWithClientset reads legacy per-shard secrets and creates a
// gen-001 generation secret using the shared config storage path. Legacy secrets
// are NOT deleted after migration.
//
// The provided clientset is used for all Kubernetes operations; it is assigned
// to cfg.Clientset so the migration can reuse cfg.StoreGenerationSecret (which
// performs the immutable-create plus idempotent AlreadyExists handling). A
// kubernetes.Interface is accepted so unit tests can pass a fake clientset.
//
// If any legacy secret is missing, an error listing the missing secrets is
// returned. If gen-001 already exists with identical data, the operation
// succeeds (idempotent).
func MigrateLegacySecretsWithClientset(cfg *baoConfig.MonitorConfig, clientset kubernetes.Interface) error {
	// Reuse the shared generation-storage path by wiring the clientset onto cfg.
	cfg.Clientset = clientset

	namespace := cfg.GetNamespace()

	prefix := cfg.SecretPrefix
	if prefix == "" {
		prefix = "cluster-key"
	}

	secretClient := clientset.CoreV1().Secrets(namespace)

	var genSecret baoConfig.GenerationSecret
	var missingSecrets []string

	// Read each shard secret {prefix}-0 through {prefix}-4
	for i := 0; i < expectedLegacyShardCount; i++ {
		name := fmt.Sprintf("%s-%d", prefix, i)
		secret, err := getSecretWithTimeout(secretClient, name)
		if err != nil {
			missingSecrets = append(missingSecrets, name)
			continue
		}

		secretData, ok := secret.Data["strdata"]
		if !ok {
			return fmt.Errorf("legacy secret %q has no 'strdata' field", name)
		}

		var ks baoConfig.KeySecret
		if err := json.Unmarshal(secretData, &ks); err != nil {
			return fmt.Errorf("failed to unmarshal legacy secret %q: %w", name, err)
		}

		if len(ks.Key) == 0 {
			return fmt.Errorf("legacy secret %q has empty keys array", name)
		}
		if len(ks.KeyEncoded) == 0 {
			return fmt.Errorf("legacy secret %q has empty keys_base64 array", name)
		}

		genSecret.Keys = append(genSecret.Keys, ks.Key[0])
		genSecret.KeysBase64 = append(genSecret.KeysBase64, ks.KeyEncoded[0])
	}

	// Read root token secret {prefix}-root
	rootName := fmt.Sprintf("%s-root", prefix)
	rootSecret, err := getSecretWithTimeout(secretClient, rootName)
	if err != nil {
		missingSecrets = append(missingSecrets, rootName)
	} else {
		rootData, ok := rootSecret.Data["strdata"]
		if !ok {
			return fmt.Errorf("legacy root token secret %q has no 'strdata' field", rootName)
		}
		genSecret.RootToken = strings.TrimSpace(string(rootData))
	}

	// If any legacy secrets are missing, return error
	if len(missingSecrets) > 0 {
		return fmt.Errorf("legacy migration failed: missing secrets: %s",
			strings.Join(missingSecrets, ", "))
	}

	genName := fmt.Sprintf("%s-%03d", cfg.GetGenerationPrefix(), 1)

	// FORM CHECKS BEFORE FREEZE.
	// The generation secret is created immutable, so a malformed value becomes an
	// unrepairable stuck state. Validate everything checkable offline BEFORE the
	// store so we fail loudly instead of freezing garbage; a clean retry then
	// remains possible.
	if err := validateAssembledGeneration(&genSecret, genName); err != nil {
		return err
	}

	// Store as gen-001 via the shared, immutable, idempotent storage path.
	slog.Info("Migrating legacy secrets to generation secret", "name", genName)

	if err := cfg.StoreGenerationSecret(genName, &genSecret); err != nil {
		return fmt.Errorf("failed to store generation secret during migration: %w", err)
	}

	// READ-BACK VERIFICATION. Mirrors the init path's StoreAndVerifyGeneration:
	// confirm K8s persisted a usable secret (loads cleanly + threshold keys).
	// Catches a persistence anomaly at mint time, while the operator is still
	// watching.
	if _, err := loadAndValidateGeneration(cfg, genName, InitSecretThreshold); err != nil {
		return fmt.Errorf("read-back verification failed for %s: %w", genName, err)
	}

	slog.Info("Legacy secret migration complete", "generation", genName)
	return nil
}

// loadAndValidateGeneration loads a stored generation secret and validates it
// is usable: it must reload cleanly (LoadGenerationSecret re-runs structural
// validation) AND carry at least `threshold` keys. This is the single
// post-store validation — "is this stored generation good enough to unseal
// with?" — shared by the read-back verification and the detect-on-invoke path.
// It is the counterpart to validateAssembledGeneration, which is the stricter
// PRE-store assembly check (exact legacy shard count, base64 decode) on a
// not-yet-frozen secret. Callers wrap the returned error with their own context.
func loadAndValidateGeneration(cfg *baoConfig.MonitorConfig, genName string, threshold int) (*baoConfig.GenerationSecret, error) {
	gen, err := cfg.LoadGenerationSecret(genName)
	if err != nil {
		return nil, fmt.Errorf("failed validation on load: %w", err)
	}
	if len(gen.Keys) < threshold {
		return nil, fmt.Errorf("has only %d keys, need at least %d", len(gen.Keys), threshold)
	}
	return gen, nil
}

// validateAssembledGeneration performs the offline "well-formed" checks on the
// generation secret assembled from legacy shards, BEFORE it is frozen immutable.
// It asserts the full expected shard count was collected, runs the shared
// structural validation, and confirms every base64 key actually decodes.
func validateAssembledGeneration(genSecret *baoConfig.GenerationSecret, genName string) error {
	// Complete key set: every legacy shard must have contributed a key. The
	// missing-secrets guard only catches failed Gets; this catches shards that
	// existed but yielded no usable key, which would otherwise freeze a short
	// (below-threshold) generation secret.
	if len(genSecret.Keys) != expectedLegacyShardCount {
		return fmt.Errorf("refusing to store %s: assembled %d keys, expected %d legacy shards",
			genName, len(genSecret.Keys), expectedLegacyShardCount)
	}
	if len(genSecret.KeysBase64) != expectedLegacyShardCount {
		return fmt.Errorf("refusing to store %s: assembled %d base64 keys, expected %d legacy shards",
			genName, len(genSecret.KeysBase64), expectedLegacyShardCount)
	}

	// Structural validation (non-empty keys, keys_base64 length matches keys,
	// non-empty root token). This is a FORM check on the root token, not a
	// functional one — a server is required to prove the token authenticates.
	if err := baoConfig.ValidateGenerationSecret(genSecret); err != nil {
		return fmt.Errorf("refusing to store %s: %w", genName, err)
	}

	// base64 sanity: a payload that unmarshaled as a string but is not valid
	// base64 indicates corruption. Fail before freezing.
	for i, b64 := range genSecret.KeysBase64 {
		if _, err := base64.StdEncoding.DecodeString(b64); err != nil {
			return fmt.Errorf("refusing to store %s: keys_base64[%d] is not valid base64: %w",
				genName, i, err)
		}
	}

	return nil
}

var conversionCmd = &cobra.Command{
	Use:   "conversion",
	Short: "Migrate legacy per-shard secrets to generation format",
	Long: `Detect and migrate legacy per-shard Kubernetes secrets (cluster-key-N pattern)
into a single immutable generation secret (openbao-unseal-gen-001).

This is a standalone, operator-invoked command. It is NOT run automatically by
the "run" loop. Legacy secrets are NOT deleted after migration.

The generation secret is created immutable, so the migration validates the
assembled keys BEFORE storing (full shard count, structure, base64) and verifies
the stored secret by reading it back — it refuses to freeze a malformed or
incomplete secret rather than leave an unrepairable state.

Idempotency: if a valid generation secret already exists, the command is a
no-op success. If one exists but is unusable (fails validation or has too few
keys), the command fails with guidance to tear it down and re-migrate — an
immutable secret cannot be repaired in place.`,
	PersistentPreRunE: setupCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		cmd.SilenceUsage = true

		if !useK8sConfig {
			return fmt.Errorf("conversion requires --k8s flag to be set")
		}

		// setupCmd initializes globalConfig.Clientset when --k8s is set.
		if globalConfig.Clientset == nil {
			return fmt.Errorf("kubernetes clientset not initialized")
		}

		prefix := globalConfig.SecretPrefix
		if prefix == "" {
			prefix = "cluster-key"
		}

		namespace := globalConfig.GetNamespace()

		// DETECT-ON-INVOKE: if gen-001 already exists, judge whether it is usable
		// before doing anything else. A frozen but malformed gen-001 (e.g. from an
		// earlier bungled migration) is an unrepairable stuck state — surface it
		// with an actionable error rather than a cryptic "already exists" or a
		// silent success. A valid existing gen-001 is an idempotent no-op.
		genName := fmt.Sprintf("%s-%03d", globalConfig.GetGenerationPrefix(), 1)
		genExists, err := secretExists(globalConfig.Clientset, namespace, genName)
		if err != nil {
			return fmt.Errorf("error checking for existing generation secret %s: %w", genName, err)
		}
		if genExists {
			// It exists; confirm it is usable (loads cleanly + threshold keys).
			// Any error here means the frozen secret is unusable — this is NOT
			// the normal already-migrated case, and an immutable secret cannot be
			// repaired in place, so surface it with actionable rollback guidance.
			if _, err := loadAndValidateGeneration(&globalConfig, genName, InitSecretThreshold); err != nil {
				return fmt.Errorf(
					"%s exists but is not usable (%w) — this is not the normal "+
						"already-migrated case; the frozen secret is unrepairable and must be "+
						"torn down and re-migrated (delete the openbao namespace via rollback "+
						"and re-run the migration)", genName, err)
			}
			slog.Info("Generation secret already present and valid, nothing to migrate",
				"name", genName)
			fmt.Printf("%s already exists and is valid. Nothing to migrate.\n", genName)
			globalConfig.CurrentKeySecret = genName
			return nil
		}

		// Detect legacy secrets
		found, err := DetectLegacySecretsWithClientset(globalConfig.Clientset, namespace, prefix)
		if err != nil {
			return fmt.Errorf("error detecting legacy secrets: %w", err)
		}

		if !found {
			slog.Info("No legacy secrets detected, nothing to migrate")
			fmt.Println("No legacy secrets detected. Nothing to migrate.")
			return nil
		}

		// Perform migration
		if err := MigrateLegacySecretsWithClientset(&globalConfig, globalConfig.Clientset); err != nil {
			return fmt.Errorf("migration failed: %w", err)
		}

		fmt.Printf("Migration complete. Generation secret: %s\n", globalConfig.CurrentKeySecret)
		return nil
	},
	PersistentPostRunE: cleanCmd,
}

func init() {
	RootCmd.AddCommand(conversionCmd)
}
