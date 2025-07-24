package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	openbao "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
)

// A single instance of unseal.
func tryUnseal(keyShard baoConfig.KeyShards, client *openbao.Client) (*openbao.SealStatusResponse, error) {
	slog.Debug("Attempting unseal...")
	key := keyShard.Key
	UnsealResult, err := client.Sys().Unseal(key)
	if err != nil {
		return nil, fmt.Errorf("error with unseal call: %v", err)
	}
	slog.Debug("Unseal attempt successful")
	return UnsealResult, nil
}

// run unseal on all keys associated with dnshost until unsealed.
func runUnseal(dnshost string, client *openbao.Client) (*openbao.SealStatusResponse, error) {
	slog.Debug(fmt.Sprintf("Attempting to run unseal on host %v", dnshost))

	slog.Debug("Checking if openbao is already unsealed")
	healthResult, err := checkHealth(dnshost, client)
	if err != nil {
		return nil, err
	}
	if !healthResult.Sealed {
		return nil, fmt.Errorf("openbao server on host %v is already unsealed", dnshost)
	}

	tryCount := 1
	for keyName, keyShard := range globalConfig.UnsealKeyShards {
		// Don't use recovery keys
		if !strings.Contains(keyName, "recovery") {
			slog.Debug(fmt.Sprintf("Unseal attempt %v", tryCount))
			UnsealResult, err := tryUnseal(keyShard, client)
			if err != nil {
				return nil, err
			}
			if !UnsealResult.Sealed {
				slog.Debug("Unseal complete.")
				return UnsealResult, nil
			}
			slog.Debug(fmt.Sprintf("Openbao still sealed: threshold %v, progress %v", UnsealResult.T, UnsealResult.Progress))
			tryCount++
		}
	}

	return nil, fmt.Errorf("exhausted all non-recovery keys associated with %v", dnshost)
}

var unsealCmd = &cobra.Command{
	Use:   "unseal DNSHost",
	Short: "Unseal openbao",
	Long: `Unseal openbao server hosted on DNSHost. It will use all
non-recovery keys with its name on it to unseal.`,
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug(fmt.Sprintf("Action: unseal %v", args[0]))

		cmd.SilenceUsage = true
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao unseal failed with error: %v", err)
		}
		UnsealResult, err := runUnseal(args[0], newClient)
		if err != nil {
			return fmt.Errorf("openbao unseal failed with error: %v", err)
		}

		UnsealPrint, err := json.MarshalIndent(UnsealResult, "", "  ")
		if err != nil {
			return fmt.Errorf("unable to marshal unseal result: %v", err)
		}
		slog.Debug(fmt.Sprintf("Unseal successful. Result: %v", string(UnsealPrint)))
		slog.Info(fmt.Sprintf("Unseal successful for host %v", args[0]))

		return nil
	},
}

func init() {
	RootCmd.AddCommand(unsealCmd)
}
