// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
package baoCommands

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/michel-thebeau-WR/openbao-manager-go/baomon/rekey"
	"github.com/spf13/cobra"
	corev1 "k8s.io/api/core/v1"
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

	// Validate CurrentKeySecret is set
	if cfg.CurrentKeySecret == "" {
		return nil, fmt.Errorf("cannot create snapshot metadata: no current generation secret configured (CurrentKeySecret is empty)")
	}

	// Load the generation secret to compute the hash
	genSecret, err := cfg.LoadGenerationSecret(cfg.CurrentKeySecret)
	if err != nil {
		return nil, fmt.Errorf("failed to load generation secret for snapshot metadata: %w", err)
	}

	// Compute SHA-256 hash of the marshaled generation secret data
	hash, err := ComputeKeyDataHash(genSecret)
	if err != nil {
		return nil, fmt.Errorf("failed to compute key data hash: %w", err)
	}

	metadata := &SnapshotMetadata{
		GenerationName: cfg.CurrentKeySecret,
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

// computeKeyDataHash computes the SHA-256 hex digest of the marshaled GenerationSecret.
func ComputeKeyDataHash(secret *baoConfig.GenerationSecret) (string, error) {
	data, err := json.Marshal(secret)
	if err != nil {
		return "", fmt.Errorf("failed to marshal generation secret for hashing: %w", err)
	}

	hash := sha256.Sum256(data)
	return fmt.Sprintf("%x", hash), nil
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
		snapFile, err := os.Create(args[1])
		if err != nil {
			return fmt.Errorf("unable to create file %v: %v", args[1], err)
		}
		defer snapFile.Close()
		err = newClient.Sys().RaftSnapshot(snapFile)
		if err != nil {
			return fmt.Errorf("snapshot create failed with error: %v", err)
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
		if metadataJSON != "" {
			var metadata SnapshotMetadata
			if err := json.Unmarshal([]byte(metadataJSON), &metadata); err != nil {
				return fmt.Errorf("failed to parse snapshot metadata: %w", err)
			}
			if err := ValidateSnapshotMetadata(&metadata, &globalConfig); err != nil {
				return fmt.Errorf("snapshot metadata validation failed: %w", err)
			}
			slog.Info("Snapshot metadata validated, proceeding with restore")
		}

		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao client setup failed with error: %v", err)
		}
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

		// Create generation-aware metadata (captures current generation + hash)
		genMetadata, err := CreateSnapshotMetadata(&globalConfig, checker)
		if err != nil {
			return fmt.Errorf("failed to create snapshot metadata: %w", err)
		}

		// Marshal generation metadata
		genMetadataBytes, err := json.Marshal(genMetadata)
		if err != nil {
			return fmt.Errorf("failed to marshal generation metadata: %w", err)
		}

		// Store as K8s secret with both caller metadata and generation metadata
		namespace := globalConfig.Namespace
		if namespace == "" {
			namespace = "openbao"
		}

		secretClient := globalConfig.Clientset.CoreV1().Secrets(namespace)
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
				"generation": genMetadataBytes,
			},
		}

		ctx := cmd.Context()
		_, err = secretClient.Create(ctx, k8sSecret, metav1.CreateOptions{})
		if err != nil {
			return fmt.Errorf("failed to create snapshot metadata secret %q: %w", secretName, err)
		}

		slog.Info("Snapshot metadata secret created",
			"secret", secretName,
			"generation", genMetadata.GenerationName,
			"hash", genMetadata.KeyDataHash)
		return nil
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
