//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	openbao "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
)

var optFileStr string
var secretShares int
var secretThreshold int

func initializeOpenbao(dnshost string, opts *openbao.InitRequest) error {
	slog.Debug(fmt.Sprintf("Attempting the initialize openbao on host %v", dnshost))
	newClient, err := globalConfig.SetupClient(dnshost)
	if err != nil {
		return err
	}

	slog.Debug("Checking current openbao status")
	healthResult, err := checkHealth(dnshost, newClient)
	if err != nil {
		return err
	}
	if healthResult.Initialized {
		return fmt.Errorf("openbao server on host %v is already initialized", dnshost)
	}

	slog.Debug("Running /sys/init")
	response, err := newClient.Sys().Init(opts)
	if err != nil {
		return fmt.Errorf("error during call to openbao init: %v", err)
	}

	slog.Debug("/sys/init complete")
	err = globalConfig.ParseInitResponse(dnshost, response)
	if err != nil {
		return fmt.Errorf("error during parsing init response: %v", err)
	}

	return nil
}

var initCmd = &cobra.Command{
	Use:   "init DNSHost",
	Short: "Initialize openbao",
	Long: `Initialize openbao server using the monitor configurations.
The key shards returned from the initResponse will be stored in the monitor
configurations.`,
	Args:              cobra.ExactArgs(1),
	PersistentPreRunE: setupCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug(fmt.Sprintf("Action: init %v", args[0]))
		fileGiven := cmd.Flags().Lookup("file").Changed
		secretSharesFlag := cmd.Flags().Lookup("secret-shares").Changed
		secretThresholdFlag := cmd.Flags().Lookup("secret-threshold").Changed

		if (fileGiven && (secretSharesFlag || secretThresholdFlag)) ||
			(!fileGiven && !(secretSharesFlag && secretThresholdFlag)) {
			fmt.Fprintf(os.Stderr, "The options for openbao init must be set by one of:\n")
			fmt.Fprintf(os.Stderr, "utilizing an option file using --file, or\n")
			fmt.Fprintf(os.Stderr, "--secret-shares and -- secret-threshold\n")
			return fmt.Errorf("failed due to invalid or missing options")
		}

		var opts openbao.InitRequest
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
		slog.Debug(fmt.Sprintf("Parsing init option successful. Attempting to run openbao init on host %v", args[0]))
		cmd.SilenceUsage = true
		err := initializeOpenbao(args[0], &opts)
		if err != nil {
			return fmt.Errorf("openbao init failed with error: %v", err)
		}
		slog.Info(fmt.Sprintf("Openbao init successful for host %v", args[0]))
		fmt.Print("Openbao init complete\n")
		return nil
	},
	PersistentPostRunE: cleanCmd,
}

func init() {
	initCmd.Flags().StringVarP(&optFileStr, "file", "f", "", "A JSON file containing the options for openbao init")
	initCmd.Flags().IntVar(&secretShares, "secret-shares", 0, "The number of shares to split the root key into.")
	initCmd.Flags().IntVar(&secretThreshold, "secret-threshold", 0, "The number of shares required to reconstruct the root key.")
	RootCmd.AddCommand(initCmd)
}
