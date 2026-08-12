//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
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
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// Command-wide objects
var globalConfig baoConfig.MonitorConfig
var logWriter *os.File
var baoLogger *slog.Logger = nil

// root options
var configFile string
var useK8sConfig bool
var useInClusterConfig bool
var kubeConfigPath string
var flagTimeout int
var flagLogLevel string

// root option names
var configFileName string = "config"
var useK8sConfigName string = "k8s"
var useInClusterConfigName string = "in-cluster"
var kubeConfigPathName string = "kubeconfig"
var flagTimeoutName string = "timeout"
var flagLogLevelName string = "log-level"

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
		slog.Debug("Running outside cluster, using kubeconfig", "path", kubeConfigPath)
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

	// Pass values from flags
	if !cmd.Flags().Changed(useK8sConfigName) {
		useK8sConfig = globalConfig.UseK8sConfig
	}
	if !cmd.Flags().Changed(useInClusterConfigName) {
		useInClusterConfig = globalConfig.UseInClusterConfig
	}
	if cmd.Flags().Changed(flagTimeoutName) {
		globalConfig.Timeout = flagTimeout
	}
	if cmd.Flags().Changed(flagLogLevelName) {
		globalConfig.LogLevel = flagLogLevel
	}

	// Set default configuration for logs if no custum configs are given
	logFile := globalConfig.LogPath
	logLevel := globalConfig.InterpretLogLevel()
	// Switch "FATAL" to "ERROR+4" so that it can be marshalled to the correct
	// slog.Level value
	if logLevel == "FATAL" {
		logLevel = "ERROR+4"
	}

	// Set default to stderr if no log file was specified.
	logWriter = os.Stderr
	if logFile != "" {
		// Setup Logs
		logWriter, err = os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
		if err != nil {
			return fmt.Errorf("error in opening the log file to write: %w", err)
		}
	}

	var LogLevel slog.Level
	LogLevel.UnmarshalText([]byte(logLevel))
	baoLogger = slog.New(baoConfig.NewBaoHandler(logWriter, &slog.HandlerOptions{
		Level: LogLevel,
	}))
	slog.SetDefault(baoLogger)
	slog.Debug("Log level set", "level", logLevel)

	// If useK8sConfig is set to true, then it will override the following configs:
	// ServerAddresses, Tokens, UnsealKeyShards
	if useK8sConfig {
		// create client config
		config, err := getK8sConfig()
		if err != nil {
			return err
		}

		// Initialize the Kubernetes clientset for generation secret operations
		clientset, err := kubernetes.NewForConfig(config)
		if err != nil {
			return fmt.Errorf("failed to create kubernetes clientset: %w", err)
		}
		globalConfig.Clientset = clientset

		// Get the necessary configs from kubernetes
		err = globalConfig.MigrateK8sConfig(config)
		if err != nil {
			return err
		}

		// Discover current generation secret so that standalone commands
		// (e.g. "baomon unseal") can locate the active unseal keys without
		// requiring a persisted config file.
		if err := DiscoverCurrentGeneration(&globalConfig, config); err != nil {
			slog.Debug("Generation discovery during setup (non-fatal)", "err", err)
		}

		// Load the generation secret into memory so that GetCurrentRootToken()
		// returns the real token for authenticated API calls (e.g. snapshot).
		if globalConfig.CurrentKeySecret != "" {
			if _, err := globalConfig.LoadGenerationSecret(globalConfig.CurrentKeySecret); err != nil {
				slog.Debug("Failed to load generation secret (non-fatal)", "err", err)
			}
		}
	}

	return nil
}

func cleanCmd(cmd *cobra.Command, args []string) error {
	slog.Debug("Running cleanup...")
	configWriter, err := os.OpenFile(configFile, os.O_WRONLY|os.O_TRUNC, 0600)
	if err != nil {
		slog.Warn("Unable to write config file", "err", err)
	} else {
		err = globalConfig.WriteYAMLMonitorConfig(configWriter)
		if err != nil {
			slog.Warn("Failed writing config", "err", err)
		}
		configWriter.Close()
	}

	// Close the log file
	if logWriter != os.Stderr {
		err := logWriter.Close()
		if err != nil {
			return fmt.Errorf("error with closing the log file: %w", err)
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
		slog.Error("Monitor failed", "err", err)
		if baoLogger != nil && logWriter != os.Stderr {
			// If logging was setup on a file, print error separately to stderr as well.
			fmt.Fprintln(os.Stderr, err)
		}
		os.Exit(1)
	}
}

func init() {
	// Declarations for global flags
	RootCmd.PersistentFlags().StringVar(&configFile, configFileName,
		"/workdir/testConfig.yaml", "file path to the monitor config file")
	RootCmd.PersistentFlags().BoolVar(&useK8sConfig, useK8sConfigName, false, "use configs from kubernetes instead")
	RootCmd.PersistentFlags().BoolVar(&useInClusterConfig, useInClusterConfigName, true,
		"Set this to true if the monitor is run in a kubernetes pod")
	RootCmd.PersistentFlags().StringVar(&kubeConfigPath, kubeConfigPathName, "/etc/kubernetes/admin.conf",
		"The path for kubernetes config file (KUBECONFIG)")
	RootCmd.PersistentFlags().IntVar(&flagTimeout, flagTimeoutName, 60,
		"Time, in seconds, the client will wait for each request before returning timeout exceeded error")
	RootCmd.PersistentFlags().StringVar(&flagLogLevel, flagLogLevelName, "INFO",
		"Minimum log level printed in the logs")
}
