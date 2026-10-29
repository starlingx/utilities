// Copyright (c) 2025-2026 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
package baoCommands

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
)

// healthProbeTimeout bounds a single health probe so a not-yet-ready server
// fails fast and the monitor loop (WaitInterval) drives the retry, rather than
// the probe blocking inside the client's default retry/timeout behavior.
const healthProbeTimeout = 5 * time.Second

func checkHealth(dnshost string, client *clientapi.Client) (*clientapi.HealthResponse, error) {
	slog.Debug("Checking health", "host", dnshost)

	ctx, cancel := context.WithTimeout(context.Background(), healthProbeTimeout)
	defer cancel()

	healthResult, err := client.Sys().HealthWithContext(ctx)
	if err != nil {
		return nil, fmt.Errorf("error during call to check health: %w", err)
	}

	slog.Debug("health check complete")
	return healthResult, nil
}

var healthCmd = &cobra.Command{
	Use:                "health DNSHost",
	Short:              "Check server health",
	Long:               "Check the health status of the server on the specified host",
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	SilenceUsage:       true,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Action: health", "host", args[0])

		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("server health failed with error: %w", err)
		}
		healthResult, err := checkHealth(args[0], newClient)
		if err != nil {
			return fmt.Errorf("server health failed with error: %w", err)
		}
		healthPrint, err := json.MarshalIndent(healthResult, "", "  ")
		if err != nil {
			return fmt.Errorf("unable to marshal health check result: %w", err)
		}
		slog.Debug("Health check successful", "host", args[0])
		fmt.Print(string(healthPrint))

		return nil
	},
}

func init() {
	RootCmd.AddCommand(healthCmd)
}
