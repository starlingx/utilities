package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"

	openbao "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
)

func checkHealth(dnshost string, client *openbao.Client) (*openbao.HealthResponse, error) {
	slog.Debug(fmt.Sprintf("Attempting to check openbao health on host %v", dnshost))
	healthResult, err := client.Sys().Health()
	if err != nil {
		return nil, fmt.Errorf("error during call to openbao check health: %v", err)
	}

	slog.Debug("health check complete")
	return healthResult, nil
}

var healthCmd = &cobra.Command{
	Use:                "health DNSHost",
	Short:              "Check openbao health",
	Long:               "Check the health status of the openbao server on the specified host",
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug(fmt.Sprintf("Action: Health %v", args[0]))

		cmd.SilenceUsage = true
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao health failed with error: %v", err)
		}
		healthResult, err := checkHealth(args[0], newClient)
		if err != nil {
			return fmt.Errorf("openbao health failed with error: %v", err)
		}
		healthPrint, err := json.MarshalIndent(healthResult, "", "  ")
		if err != nil {
			return fmt.Errorf("unable to marshal health check result: %v", err)
		}
		slog.Info(fmt.Sprintf("Health check command successful for host %v", args[0]))
		fmt.Print("Health check successful. Result:\n")
		fmt.Print(string(healthPrint))

		return nil
	},
}

func init() {
	RootCmd.AddCommand(healthCmd)
}
