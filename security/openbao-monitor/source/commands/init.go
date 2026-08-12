//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/pingcap/failpoint"
	"github.com/spf13/cobra"
)

var optFileStr string
var secretShares int
var secretThreshold int

func initializeServer(dnshost string, opts *clientapi.InitRequest) (*clientapi.InitResponse, error) {
	slog.Debug("Attempting to initialize server", "host", dnshost)
	newClient, err := globalConfig.SetupClient(dnshost)
	if err != nil {
		return nil, err
	}

	slog.Debug("Checking current server status")
	healthResult, err := checkHealth(dnshost, newClient)
	if err != nil {
		return nil, err
	}
	if healthResult.Initialized {
		return nil, fmt.Errorf("the server on host %v is already initialized", dnshost)
	}

	slog.Debug("Running /sys/init")
	response, err := newClient.Sys().Init(opts)
	if err != nil {
		return nil, fmt.Errorf("call to init: %w", err)
	}

	// Failpoint 5: After Init Response, Before Generation Secret Creation
	// Simulates: crash after server init returns keys, before K8s secret created
	failpoint.Inject("fp_init_after_init_before_store", func() {
		slog.Warn("Failpoint triggered: fp_init_after_init_before_store")
		failpoint.Return(fmt.Errorf("failpoint: After Init Response, Before Generation Secret Creation"))
	})

	slog.Debug("/sys/init complete")

	// Legacy: parse into MonitorConfig for backward compatibility
	err = globalConfig.ParseInitResponse(dnshost, response)
	if err != nil {
		return nil, fmt.Errorf("parsing init response: %w", err)
	}

	return response, nil
}

var initCmd = &cobra.Command{
	Use:   "init DNSHost",
	Short: "Initialize the server",
	Long: `Initialize the server using the monitor configurations.
The key shards returned from the initResponse will be stored in the monitor
configurations. When --k8s is set, keys are stored as an immutable generation
secret in Kubernetes.`,
	Args:              cobra.ExactArgs(1),
	PersistentPreRunE: setupCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Action: init", "host", args[0])
		fileGiven := cmd.Flags().Lookup("file").Changed
		secretSharesFlag := cmd.Flags().Lookup("secret-shares").Changed
		secretThresholdFlag := cmd.Flags().Lookup("secret-threshold").Changed

		if (fileGiven && (secretSharesFlag || secretThresholdFlag)) ||
			(!fileGiven && !(secretSharesFlag && secretThresholdFlag)) {
			fmt.Fprintf(os.Stderr, "The options for init must be set by one of:\n")
			fmt.Fprintf(os.Stderr, "utilizing an option file using --file, or\n")
			fmt.Fprintf(os.Stderr, "--secret-shares and -- secret-threshold\n")
			return fmt.Errorf("failed due to invalid or missing options")
		}

		var opts clientapi.InitRequest
		if fileGiven {
			optFileReader, err := os.ReadFile(optFileStr)
			if err != nil {
				return fmt.Errorf("unable to open init option file %v: %v", optFileStr, err)
			}
			err = json.Unmarshal(optFileReader, &opts)
			if err != nil {
				return fmt.Errorf("unable to parse JSON file %v: %v", optFileStr, err)
			}
		} else {
			if secretShares == 0 {
				return fmt.Errorf("the field secret-shares cannot be 0")
			}
			if secretThreshold == 0 {
				return fmt.Errorf("the field secret-threshold cannot be 0")
			}
			if secretShares < secretThreshold {
				return fmt.Errorf("the field secret-threshold cannot be greater than secret-shares")
			}
			opts.SecretShares = secretShares
			opts.SecretThreshold = secretThreshold
		}
		slog.Debug("Parsing init options successful, running init", "host", args[0])
		cmd.SilenceUsage = true
		response, err := initializeServer(args[0], &opts)
		if err != nil {
			return err
		}

		// Store generation secret to Kubernetes (if --k8s is set)
		if useK8sConfig {
			genSecret, err := baoConfig.ParseInitResponseToGeneration(response)
			if err != nil {
				return fmt.Errorf("failed to parse init response: %w", err)
			}

			genName, err := globalConfig.StoreAndVerifyGeneration(genSecret, secretThreshold)
			if err != nil {
				return err
			}

			slog.Info("Generation secret stored and verified", "name", genName)
		}

		slog.Info("Init successful", "host", args[0])
		return nil
	},
	PersistentPostRunE: cleanCmd,
}

func init() {
	initCmd.Flags().StringVarP(&optFileStr, "file", "f", "", "A JSON file containing the options for init")
	initCmd.Flags().IntVar(&secretShares, "secret-shares", 0, "The number of shares to split the root key into.")
	initCmd.Flags().IntVar(&secretThreshold, "secret-threshold", 0, "The number of shares required to reconstruct the root key.")
	RootCmd.AddCommand(initCmd)
}
