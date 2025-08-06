//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"fmt"
	"log/slog"
	"os"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/spf13/cobra"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

var configFile string
var globalConfig baoConfig.MonitorConfig
var logWriter *os.File
var baoLogger *slog.Logger = nil
var useK8sConfig bool
var useInClusterConfig bool
var kubeConfigPath string

func getK8sConfig() (*rest.Config, error) {
	var config *rest.Config
	var err error = nil
	slog.Debug("Setting up kubernetes config...")
	if useInClusterConfig {
		slog.Debug("The monitor is running inside the kubernetes cluster. Using in-cluster configs.")
		config, err = rest.InClusterConfig()
		if err != nil {
			return nil, err
		}
	} else {
		slog.Debug(fmt.Sprintf("The monitor is running outside the kubernetes cluster. Using configs from %v", kubeConfigPath))
		config, err = clientcmd.BuildConfigFromFlags("", kubeConfigPath)
		if err != nil {
			return nil, err
		}
	}
	slog.Debug("Setting up kubernetes config successful.")
	return config, nil
}

func setupCmd(cmd *cobra.Command, args []string) error {
	// Open config from file
	configReader, err := os.Open(configFile)
	if err != nil {
		return fmt.Errorf("error in opening config file: %v, message: %v", configFile, err)
	}
	defer configReader.Close()
	err = globalConfig.ReadYAMLMonitorConfig(configReader)
	if err != nil {
		return fmt.Errorf("error in parsing config file: %v, message: %v", configFile, err)
	}

	// Set default configuration for logs if no custum configs are given
	logFile := globalConfig.LogPath
	logLevel := globalConfig.LogLevel
	if logLevel == "" {
		// Default log level if no log level was set
		logLevel = "INFO"
	}

	// Set default to stdout if no log file was specified.
	logWriter = os.Stdout
	if logFile != "" {
		// Setup Logs
		logWriter, err = os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			return fmt.Errorf("error in opening the log file to write: %v", err)
		}
	}

	var LogLevel slog.Level
	LogLevel.UnmarshalText([]byte(logLevel))
	baoLogger = slog.New(slog.NewTextHandler(logWriter, &slog.HandlerOptions{
		Level: LogLevel,
	}))
	slog.SetDefault(baoLogger)
	slog.Debug(fmt.Sprintf("Set log level: %v", logLevel))

	// If useK8sConfig is set to true, then it will override the following configs:
	// ServerAddresses, Tokens, UnsealKeyShards
	if useK8sConfig {
		// create client config
		config, err := getK8sConfig()
		if err != nil {
			return err
		}

		// Get the necessary configs from kubernetes
		err = globalConfig.MigrateK8sConfig(config)
		if err != nil {
			return err
		}
	}

	return nil
}

func cleanCmd(cmd *cobra.Command, args []string) error {
	slog.Debug("Running cleanup...")
	// Write back to configs from file only
	if !useK8sConfig {
		configWriter, err := os.OpenFile(configFile, os.O_WRONLY|os.O_TRUNC, 0644)
		if err != nil {
			return fmt.Errorf("error with opening config file to write in the changed configs: %v", err)
		}
		err = globalConfig.WriteYAMLMonitorConfig(configWriter)
		if err != nil {
			return fmt.Errorf("error with writing the changed configs: %v", err)
		}
		err = configWriter.Close()
		if err != nil {
			return fmt.Errorf("error with closing the changed config file: %v", err)
		}
	}

	// Close the log file
	if logWriter != os.Stdout {
		err := logWriter.Close()
		if err != nil {
			return fmt.Errorf("error with closing the log file: %v", err)
		}
	}

	return nil
}

var RootCmd = &cobra.Command{
	Use:   "baomon",
	Short: "A monitor service for managing the secret servers",
	Long:  `A monitor service for managing the secret servers`,
}

func Execute() {
	if err := RootCmd.Execute(); err != nil {
		slog.Error(fmt.Sprintf("The monitor failed with error: %v", err))
		if baoLogger != nil && logWriter != os.Stdout {
			// If logging was setup on a file, print error separately to stderr as well.
			fmt.Fprintln(os.Stderr, err)
		}
		os.Exit(1)
	}
}

func init() {
	// Declarations for global flags
	RootCmd.PersistentFlags().StringVar(&configFile, "config",
		"/workdir/testConfig.yaml", "file path to the monitor config file")
	RootCmd.PersistentFlags().BoolVar(&useK8sConfig, "k8s", false, "use configs from kubernetes instead")
	RootCmd.PersistentFlags().BoolVar(&useInClusterConfig, "in-cluster", true,
		"Set this to true if the monitor is run in a kubernetes pod")
	RootCmd.PersistentFlags().StringVar(&kubeConfigPath, "kubeconfig", "/etc/kubernetes/admin.conf",
		"The path for kubernetes config file (KUBECONFIG)")
}
