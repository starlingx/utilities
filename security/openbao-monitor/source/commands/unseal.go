package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"strings"
	"time"

	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/pingcap/failpoint"
	"github.com/spf13/cobra"
)

var printResponse bool
var waitTime int

// tryUnseal submits a single unseal key to the server.
func tryUnseal(key string, client *clientapi.Client) (*clientapi.SealStatusResponse, error) {
	slog.Debug("Attempting unseal...")
	UnsealResult, err := client.Sys().Unseal(key)
	if err != nil {
		return UnsealResult, fmt.Errorf("unseal call: %w", err)
	}
	slog.Debug("Unseal attempt successful")
	return UnsealResult, nil
}

// run unseal on all keys associated with dnshost until unsealed.
func runUnseal(dnshost string, client *clientapi.Client) (*clientapi.SealStatusResponse, error) {
	slog.Debug("Attempting to run unseal on host", "host", dnshost)

	slog.Debug("Checking if the server is already unsealed")
	healthResult, err := checkHealth(dnshost, client)
	if err != nil {
		return nil, err
	}
	if !healthResult.Sealed {
		return nil, fmt.Errorf("the server on host %v is already unsealed", dnshost)
	}

	// Use generation keys if CurrentKeySecret is set
	if globalConfig.CurrentKeySecret != "" && useK8sConfig {
		return runUnsealFromGeneration(dnshost, client)
	}

	tryCount := 1
	for keyName, keyShard := range globalConfig.UnsealKeyShards {
		// Don't use recovery keys
		if !strings.Contains(keyName, "recovery") {
			slog.Debug("Unseal attempt", "count", tryCount)
			UnsealResult, err := tryUnseal(keyShard.Key, client)
			if printResponse {
				responsePrint, err := json.MarshalIndent(UnsealResult, "", "  ")
				if err != nil {
					slog.Debug("Failed to marshal unseal response", "err", err)
				}
				slog.Debug("Unseal response", "result", string(responsePrint))
			}
			if err != nil {
				return UnsealResult, err
			}
			if !UnsealResult.Sealed {
				slog.Debug("Unseal complete.")
				return UnsealResult, nil
			}
			if tryCount == UnsealResult.T {
				slog.Debug("Threshold reached, waiting before checking", "waitSeconds", waitTime)
				time.Sleep(time.Second * time.Duration(waitTime))
				healthResult, err := checkHealth(dnshost, client)
				if err != nil {
					return UnsealResult, fmt.Errorf("health check error after reaching unseal threshold: %w", err)
				}
				if !healthResult.Sealed {
					slog.Debug("Unseal complete.")
					return UnsealResult, nil
				} else {
					return UnsealResult, fmt.Errorf("server %v still sealed after reaching threshold", dnshost)
				}
			}
			slog.Debug("Server still sealed", "threshold", UnsealResult.T, "progress", UnsealResult.Progress)
			tryCount++
		}
	}

	return nil, fmt.Errorf("exhausted all non-recovery keys associated with %v", dnshost)
}

// runUnsealFromGeneration loads the current generation secret and uses those
// keys to unseal the server.
func runUnsealFromGeneration(dnshost string, client *clientapi.Client) (*clientapi.SealStatusResponse, error) {
	slog.Debug("Using generation-based keys for unseal")

	_, err := getK8sConfig()
	if err != nil {
		return nil, fmt.Errorf("failed to get k8s config for generation load: %w", err)
	}

	genSecret, err := globalConfig.LoadGenerationSecret(globalConfig.CurrentKeySecret)
	if err != nil {
		return nil, fmt.Errorf("failed to load generation secret: %w", err)
	}

	// Failpoint 4: After Reading Generation Secret, Before Unseal Loop
	// Simulates: crash after retrieving keys from K8s, before unsealing server
	failpoint.Inject("fp_unseal_after_read_before_submit", func() {
		slog.Warn("Failpoint triggered: fp_unseal_after_read_before_submit")
		failpoint.Return(nil, fmt.Errorf("failpoint: After Reading Generation Secret, Before Unseal Loop"))
	})

	// Delegate to shared unseal implementation
	if err := UnsealWithGenKeys(client, genSecret); err != nil {
		return nil, err
	}
	return &clientapi.SealStatusResponse{Sealed: false}, nil
}

var unsealCmd = &cobra.Command{
	Use:   "unseal DNSHost",
	Short: "Unseal a server",
	Long: `Unseal the server hosted on DNSHost. It will use all
non-recovery keys with its name on it to unseal.`,
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	SilenceUsage:       true,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Action: unseal", "host", args[0])

		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("unseal failed with error: %w", err)
		}
		UnsealResult, err := runUnseal(args[0], newClient)
		UnsealPrint, marshalErr := json.MarshalIndent(UnsealResult, "", "  ")
		if marshalErr != nil {
			slog.Debug("Failed to marshal unseal result", "err", marshalErr)
		}
		if printResponse {
			slog.Debug("Final unseal result", "result", string(UnsealPrint))
		}
		if err != nil {
			return fmt.Errorf("unseal failed with error: %w", err)
		}

		slog.Debug("Unseal successful", "result", string(UnsealPrint))
		slog.Info("Unseal successful", "host", args[0])

		return nil
	},
}

func init() {
	unsealCmd.PersistentFlags().BoolVarP(&printResponse, "verbose", "v", false,
		"Log extra DEBUG level logs")
	unsealCmd.PersistentFlags().IntVarP(&waitTime, "wait-converge", "w", 3,
		"The number of seconds to wait after reaching threshold to check unseal status. Default is 3 seconds.")
	RootCmd.AddCommand(unsealCmd)
}
