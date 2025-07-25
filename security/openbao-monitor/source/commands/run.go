package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"maps"
	"time"

	openbao "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
	"k8s.io/client-go/rest"
)

var waitInterval int

var runCmd = &cobra.Command{
	Use:   "run",
	Short: "keep unsealing openbao",
	Long: `Run a loop which detects if the openbao server is sealed, then if it is
attempt to unseal.`,
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Action: run")
		if globalConfig.WaitInterval != 0 {
			waitInterval = globalConfig.WaitInterval
		}

		var k8sconfig *rest.Config = nil
		var err error = nil

		if useK8sConfig {
			k8sconfig, err = getK8sConfig()
			if err != nil {
				return err
			}
		}

		for {
			// If config was pulled from k8s, repull each time to reset the list of adresses,
			// in case any of them changed
			if useK8sConfig {
				err := globalConfig.MigratePodConfig(k8sconfig)
				if err != nil {
					return err
				}
			}

			slog.Debug("Creating api clients for each openbao addresses..")
			clientMap := make(map[string]*openbao.Client, len(globalConfig.OpenbaoAddresses))
			for host := range maps.Keys(globalConfig.OpenbaoAddresses) {
				slog.Debug(fmt.Sprintf("Creating client for host %v", host))
				newClient, err := globalConfig.SetupClient(host)
				if err != nil {
					return fmt.Errorf("error occured during creating client for host %v: %v", host, err)
				}
				clientMap[host] = newClient
			}

			for host, client := range clientMap {
				slog.Debug(fmt.Sprintf("Checking current health status for host %v", host))
				healthStatus, err := checkHealth(host, client)
				if err != nil {
					slog.Error(fmt.Sprintf("error occured during check health for host %v: %v", host, err))
					// skip to next host if an error occured
					continue
				}
				healthPrint, err := json.Marshal(healthStatus)
				if err != nil {
					slog.Error(fmt.Sprintf("error occured parsing check health result for host %v: %v", host, err))
					continue
				}
				slog.Debug(fmt.Sprintf("health check result: %v", string(healthPrint)))
				if healthStatus.Sealed {
					slog.Info(fmt.Sprintf("Openbao is sealed on host %v. Attempting to unseal.", host))
					_, err := runUnseal(host, client)
					if err != nil {
						slog.Error(fmt.Sprintf("error occured during unseal on host %v: %v", host, err))
						continue
					}
				}
				slog.Debug(fmt.Sprintf("Openbao on host %v is unsealed", host))
			}
			slog.Debug(fmt.Sprintf("Unseal check complete. Waiting %v seconds until the next check...", waitInterval))
			time.Sleep(time.Duration(waitInterval) * time.Second)
		}
	},
}

func init() {
	runCmd.Flags().IntVar(&waitInterval, "waitInterval", 5, "wait time between each check")
	RootCmd.AddCommand(runCmd)
}
