// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
package baoCommands

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"reflect"
	"time"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	"github.com/spf13/cobra"
	corev1 "k8s.io/api/core/v1"
	k8sErrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// SnapshotMetadata records which generation secret was active when a snapshot
// was taken. On restore, this is used to validate that the required generation
// secret still exists in Kubernetes (needed for unseal after restore).
type SnapshotMetadata struct {
	// GenerationName is the name of the k8s secret that was active at snapshot time.
	// Example: "openbao-unseal-gen-001"
	GenerationName string `json:"generation_name"`

	// KeyDataHash is the SHA-256 hex digest of the marshaled GenerationSecret data.
	// This allows verifying that the generation secret hasn't been tampered with.
	KeyDataHash string `json:"key_data_hash"`
}

// RekeyChecker abstracts the ability to check if a rekey is in progress.
// This enables unit testing without a real OpenBao connection.
type RekeyChecker interface {
	CheckRekeyInProgress() (bool, error)
}

// openbaoRekeyChecker implements RekeyChecker using the rekey package's
// CheckInProgress method, which queries the OpenBao /sys/rekey/init endpoint.
// This mirrors the legacy vault-manager's snapshotPreCheck behavior.
type openbaoRekeyChecker struct {
	sys rekey.SysAPI
}

func (c *openbaoRekeyChecker) CheckRekeyInProgress() (bool, error) {
	proc := &rekey.RekeyProcess{}
	return proc.CheckInProgress(c.sys)
}

// CreateSnapshotMetadata creates snapshot metadata from the current generation state.
// It identifies the active generation secret via cfg.CurrentKeySecret and computes a
// SHA-256 hash of the marshaled key data. Returns an error if:
//   - No current key secret is configured
//   - A rekey is in progress (snapshot would reference transitional state)
//   - The generation secret cannot be loaded from Kubernetes
func CreateSnapshotMetadata(cfg *baoConfig.MonitorConfig, rekeyChecker RekeyChecker) (*SnapshotMetadata, error) {
	// Refuse if rekey is in progress
	if rekeyChecker != nil {
		inProgress, err := rekeyChecker.CheckRekeyInProgress()
		if err != nil {
			return nil, fmt.Errorf("failed to check rekey status: %w", err)
		}
		if inProgress {
			return nil, fmt.Errorf("cannot create snapshot metadata: rekey is in progress")
		}
	}

	genName, err := cfg.LoadCurrentKeyPointer()
	if err != nil {
		return nil, fmt.Errorf("failed to load current pointer: %v", err)
	}
	if genName == "" {
		// Pointer not created yet. use the in-cache data
		genName = cfg.CurrentKeySecret
	}
	if genName == "" {
		return nil, fmt.Errorf("no active generation")
	}

	// Load the generation secret to compute the hash
	genSecret, err := cfg.LoadGenerationSecret(genName)
	if err != nil {
		return nil, fmt.Errorf("failed to load generation secret for snapshot metadata: %w", err)
	}

	// Compute SHA-256 hash of the marshaled generation secret data
	hash, err := ComputeKeyDataHash(genSecret)
	if err != nil {
		return nil, fmt.Errorf("failed to compute key data hash: %w", err)
	}

	metadata := &SnapshotMetadata{
		GenerationName: genName,
		KeyDataHash:    hash,
	}

	slog.Info("Snapshot metadata created", "generation", metadata.GenerationName, "hash", metadata.KeyDataHash)
	return metadata, nil
}

// ValidateSnapshotMetadata validates that the generation secret referenced in the
// metadata still exists in Kubernetes. This is needed for restore operations to
// ensure the unseal keys are available after restore.
func ValidateSnapshotMetadata(metadata *SnapshotMetadata, cfg *baoConfig.MonitorConfig) error {
	if metadata == nil {
		return fmt.Errorf("snapshot metadata is nil")
	}

	if metadata.GenerationName == "" {
		return fmt.Errorf("snapshot metadata has empty generation name")
	}

	// Load the specific generation secret by name
	genSecret, err := cfg.LoadGenerationSecret(metadata.GenerationName)
	if err != nil {
		return fmt.Errorf("snapshot references generation secret %q which no longer exists or is invalid: %w", metadata.GenerationName, err)
	}

	// Verify the hash matches (tamper detection — mandatory)
	currentHash, hashErr := ComputeKeyDataHash(genSecret)
	if hashErr != nil {
		return fmt.Errorf("computing key data hash: %w", hashErr)
	}
	if currentHash != metadata.KeyDataHash {
		return fmt.Errorf("hash mismatch for %q: expected %s, got %s",
			metadata.GenerationName, metadata.KeyDataHash, currentHash)
	}

	slog.Info("Snapshot metadata validated successfully", "generation", metadata.GenerationName)
	return nil
}

// ComputeKeyDataHash computes the SHA-256 hex digest of the marshaled GenerationSecret.
func ComputeKeyDataHash(secret *baoConfig.GenerationSecret) (string, error) {
	data, err := json.Marshal(secret)
	if err != nil {
		return "", fmt.Errorf("failed to marshal generation secret for hashing: %w", err)
	}

	hash := sha256.Sum256(data)
	return fmt.Sprintf("%x", hash), nil
}

func snapshotMetadataSecret(rawMetadata string) (string, error) {
	var metadata struct {
		Secret string `json:"secret"`
	}
	if err := json.Unmarshal([]byte(rawMetadata), &metadata); err != nil {
		return "", fmt.Errorf("failed to parse snapshot metadata: %v", err)
	}
	if metadata.Secret == "" {
		return "", fmt.Errorf("snapshot metadata omits the Kubernetes secret")
	}
	return metadata.Secret, nil
}

// Loads the generation record associated with the backup metadata
// and validates that its generation still exists
func ResolveSnapshotMetadata(ctx context.Context, rawMetadata string, cfg *baoConfig.MonitorConfig) (*SnapshotMetadata, error) {
	secretName, err := snapshotMetadataSecret(rawMetadata)
	if err != nil {
		return nil, err
	}
	if cfg.Clientset == nil {
		return nil, fmt.Errorf("kubernetes client not initialized")
	}

	k8sCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()

	// Load in the snapshot metadata from its secret
	secret, err := cfg.Clientset.CoreV1().Secrets(cfg.GetNamespace()).Get(k8sCtx, secretName, metav1.GetOptions{})
	if err != nil {
		return nil, fmt.Errorf("failed to load snapshot metadata secret %s: %w", secretName, err)
	}
	storedCallerMetadata, ok := secret.Data["metadata"]
	if !ok {
		return nil, fmt.Errorf("snapshot metadata secret %v has no metadata field", secretName)
	}

	// compare the loaded metadata from the secret to rawMetadata
	var incomingValue, storedValue any
	if err := json.Unmarshal([]byte(rawMetadata), &incomingValue); err != nil {
		return nil, fmt.Errorf("failed to parse snapshot metadata: %v", err)
	}
	if err := json.Unmarshal(storedCallerMetadata, &storedValue); err != nil {
		return nil, fmt.Errorf("failed to parse secret data")
	}
	if !reflect.DeepEqual(incomingValue, storedValue) {
		return nil, fmt.Errorf("snapshot metadata does not match Kubernetes secret %v", secretName)
	}

	// Prepare snapshot metadate from the secret for validation
	generationData, ok := secret.Data["generation"]
	if !ok {
		return nil, fmt.Errorf("snapshot metadata secret %v has no generation info", secretName)
	}
	var generation SnapshotMetadata
	if err := json.Unmarshal(generationData, &generation); err != nil {
		return nil, fmt.Errorf("snapshot metadata secret %v has invalid generation data: %v", secretName, err)
	}
	if err := ValidateSnapshotMetadata(&generation, cfg); err != nil {
		return nil, err
	}

	return &generation, nil
}

func StoreSnapshotMetadata(ctx context.Context, cfg *baoConfig.MonitorConfig, secretName, callerMetadata string, generation *SnapshotMetadata) error {
	if generation == nil {
		return fmt.Errorf("snapshot metadata is nil")
	}
	if cfg.Clientset == nil {
		return fmt.Errorf("client is not initialized")
	}

	generationData, err := json.Marshal(generation)
	if err != nil {
		return fmt.Errorf("failed to marshal generation metadata: %v", err)
	}

	namespace := cfg.GetNamespace()

	// New k8s secret for snapshot metadata
	k8sSecret := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{
			Name:      secretName,
			Namespace: namespace,
			Labels: map[string]string{
				"app":       "openbao",
				"component": "snapshot-metadata",
			},
		},
		Data: map[string][]byte{
			"metadata":   []byte(callerMetadata),
			"generation": generationData,
		},
	}

	k8sCtx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	secretClient := cfg.Clientset.CoreV1().Secrets(namespace)
	if _, err := secretClient.Create(k8sCtx, k8sSecret, metav1.CreateOptions{}); err != nil {
		if !k8sErrors.IsAlreadyExists(err) {
			return fmt.Errorf("failed to create snapshot metadata secret %v: %v", secretName, err)
		}
		existing, getErr := secretClient.Get(k8sCtx, secretName, metav1.GetOptions{})
		if getErr != nil {
			return fmt.Errorf("failed to verify existing snapshot metadata secret %v: %v", secretName, getErr)
		}
		if bytes.Equal(existing.Data["metadata"], []byte(callerMetadata)) &&
			bytes.Equal(existing.Data["generation"], generationData) {
			slog.Debug("An existing snapshot metadata secret found with identical data",
				"secret", secretName, "generation", generation.GenerationName)
			return nil
		}
		return fmt.Errorf("snapshot metadata secret %v found with conflicting data", secretName)
	}

	slog.Info("Snapshot metadata secret created", "secret", secretName,
		"generation", generation.GenerationName)
	return nil
}

func ActivateRestoredGeneration(cfg *baoConfig.MonitorConfig, metadata *SnapshotMetadata) error {
	if metadata == nil {
		return nil
	}
	return cfg.ActivateGeneration(metadata.GenerationName, nil)
}

var forceCmd bool
var metadataJSON string

var snapshotCmd = &cobra.Command{
	Use:   "snapshot",
	Short: "All snapshot related commands",
	Long:  "Suite of all snapshot related commands.",
}

var precheckCmd = &cobra.Command{
	Use:   "precheck",
	Short: "Ready check for snapshot",
	Long: `A list of checks to be done before snapshot creation:
- All server pods must be unsealed

Please make sure all conditions are fulfilled before attempting
to create a snapshot.
`,
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot precheck...")
		for host := range globalConfig.ServerAddresses {
			newClient, err := globalConfig.SetupClient(host)
			if err != nil {
				return fmt.Errorf("openbao client setup failed with error: %v", err)
			}
			healthResult, err := checkHealth(host, newClient)
			if err != nil {
				return fmt.Errorf("server health failed with error: %v", err)
			}
			if healthResult.Sealed {
				return fmt.Errorf("openbao host %v is currently sealed", host)
			}

			// Check rekey status (mirrors legacy vault-manager snapshotPreCheck)
			checker := &openbaoRekeyChecker{sys: newClient.Sys()}
			inProgress, rekeyErr := checker.CheckRekeyInProgress()
			if rekeyErr != nil {
				return fmt.Errorf("failed to check rekey status on host %v: %w", host, rekeyErr)
			}
			if inProgress {
				return fmt.Errorf("openbao host %v has a rekey in progress", host)
			}
		}
		slog.Info("Snapshot precheck successful.")
		return nil
	},
}

var snapshotCreateCmd = &cobra.Command{
	Use:   "create DNShost filename",
	Short: "Create a snapshot for openbao",
	Long: `Create a snapshot tarball for the openbao server.
The result is stored as a tarball to the specified filename.
`,
	Args:               cobra.ExactArgs(2),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot create...")
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao client setup failed with error: %v", err)
		}
		checker := &openbaoRekeyChecker{sys: newClient.Sys()}
		before, err := CreateSnapshotMetadata(&globalConfig, checker)
		if err != nil {
			return fmt.Errorf("snapshot precheck failed: %v", err)
		}
		snapFile, err := os.OpenFile(args[1], os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0600)
		if err != nil {
			return fmt.Errorf("unable to create file %v: %v", args[1], err)
		}
		defer snapFile.Close()
		err = newClient.Sys().RaftSnapshot(snapFile)
		if err != nil {
			return fmt.Errorf("snapshot create failed with error: %v", err)
		}
		after, err := CreateSnapshotMetadata(&globalConfig, checker)
		if err != nil {
			return fmt.Errorf("snapshot postcheck failed: %v", err)
		}
		if !reflect.DeepEqual(before, after) {
			return fmt.Errorf("active generation changed during capture")
		}
		slog.Info("Snapshot create successful.")

		return nil
	},
}

var snapshotRestoreCmd = &cobra.Command{
	Use:                "restore DNShost filename",
	Short:              "Restore openbao from a snapshot",
	Long:               "Restore the openbao server from a generated snapshot tarball",
	Args:               cobra.ExactArgs(2),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot restore...")

		// If metadata is provided, validate generation secret before restoring
		if metadataJSON == "" {
			return fmt.Errorf("snapshot restore requires metadata")
		}
		metadata, err := ResolveSnapshotMetadata(cmd.Context(), metadataJSON, &globalConfig)
		if err != nil {
			return fmt.Errorf("snapshot metadata validation failed: %v", err)
		}
		slog.Debug("Snapshot metadata validated, proceeding with restore")

		// Setup client
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao client setup failed with error: %v", err)
		}

		// Check rekey status
		restoreChecker := &openbaoRekeyChecker{sys: newClient.Sys()}
		inProgress, err := restoreChecker.CheckRekeyInProgress()
		if err != nil {
			return fmt.Errorf("failed to check rekey status before restore: %v", err)
		}
		if inProgress {
			return fmt.Errorf("cannot run snapshot restore while a rekey is in progress")
		}

		// Start snapshot restore
		snapFile, err := os.Open(args[1])
		if err != nil {
			return fmt.Errorf("unable to open file %v: %v", args[1], err)
		}
		defer snapFile.Close()
		err = newClient.Sys().RaftSnapshotRestore(snapFile, forceCmd)
		if err != nil {
			return fmt.Errorf("snapshot restore failed with error: %v", err)
		}
		slog.Info("Snapshot restore successful.")

		// Surface a pointer-update failure as a non-zero exit. The data is
		// restored, but the current-key pointer still names the pre-restore
		// generation. The run loop would eventually trial-unseal and repair
		// the pointer, but that is conditional (only when the restored server
		// is sealed and the stale pointer cannot unseal it), so an
		// operator-driven restore must report that it did not fully complete.
		if err := ActivateRestoredGeneration(&globalConfig, metadata); err != nil {
			return fmt.Errorf("snapshot restore succeeded but current key pointer "+
				"update failed; the restore did not fully complete: %w", err)
		}
		slog.Debug("Snapshot restore succeeded, and the pointer was updated.")

		return nil
	},
}

var snapshotSetMetadataCmd = &cobra.Command{
	Use:   "set-metadata secretName metadataJSON",
	Short: "Store snapshot metadata in a K8s secret",
	Long: `Create a K8s secret that records which generation secret was active
at snapshot time, combined with the caller-provided metadata (date, hash, etc).

This is called by the backup playbook after snapshot creation to tie the
snapshot tarball to the generation secret that can unseal it.`,
	Args:               cobra.ExactArgs(2),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		secretName := args[0]
		callerMetadata := args[1]

		slog.Debug("Running snapshot set-metadata...", "secret", secretName)

		metadataSecret, err := snapshotMetadataSecret(callerMetadata)
		if err != nil {
			return err
		}
		if metadataSecret != secretName {
			return fmt.Errorf("snapshot metadata secret %v does not match supplied name %v", metadataSecret, secretName)
		}

		// Set up a rekey checker using the first available server.
		// This queries /sys/rekey/init to ensure no rekey is in progress,
		// matching the legacy vault-manager snapshotPreCheck behavior.
		var checker RekeyChecker
		for host := range globalConfig.ServerAddresses {
			client, err := globalConfig.SetupClient(host)
			if err != nil {
				slog.Warn("Cannot connect to server for rekey check", "host", host, "err", err)
				continue
			}
			checker = &openbaoRekeyChecker{sys: client.Sys()}
			break
		}

		if checker == nil {
			return fmt.Errorf("no Openbao server was available for rekey status validation")
		}

		// Create generation-aware metadata (captures current generation + hash)
		genMetadata, err := CreateSnapshotMetadata(&globalConfig, checker)
		if err != nil {
			return fmt.Errorf("failed to create snapshot metadata: %w", err)
		}

		return StoreSnapshotMetadata(cmd.Context(), &globalConfig, secretName, callerMetadata, genMetadata)
	},
}

func init() {
	snapshotRestoreCmd.PersistentFlags().BoolVar(&forceCmd, "force", false, "force restore command")
	snapshotRestoreCmd.PersistentFlags().StringVar(&metadataJSON, "metadata", "", "snapshot metadata JSON for validation before restore")
	snapshotCmd.AddCommand(precheckCmd)
	snapshotCmd.AddCommand(snapshotCreateCmd)
	snapshotCmd.AddCommand(snapshotRestoreCmd)
	snapshotCmd.AddCommand(snapshotSetMetadataCmd)
	RootCmd.AddCommand(snapshotCmd)
}
