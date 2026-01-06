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

// Command-wide objects
var globalConfig baoConfig.MonitorConfig
var logWriter *os.File
var baoLogger *slog.Logger = nil

// root options
var configFile string
var useK8sConfig bool
var useInClusterConfig bool
var kubeConfigPath string
var flgTimeout int
var flgLogLevel string

// root option names
var configFileName string = "config"
var useK8sConfigName string = "k8s"
var useInClusterConfigName string = "in-cluster"
var kubeConfigPathName string = "kubeconfig"
var flgTimeoutName string = "timeout"
var flgLogLevelName string = "log-level"

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

	// Pass values from flags
	if !cmd.Flags().Changed(useK8sConfigName) {
		useK8sConfig = globalConfig.UseK8sConfig
	}
	if !cmd.Flags().Changed(useInClusterConfigName) {
		useInClusterConfig = globalConfig.UseInClusterConfig
	}
	if cmd.Flags().Changed(flgTimeoutName) {
		globalConfig.Timeout = flgTimeout
	}
	if cmd.Flags().Changed(flgLogLevelName) {
		globalConfig.LogLevel = flgLogLevel
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
			return fmt.Errorf("error in opening the log file to write: %v", err)
		}
	}

	var LogLevel slog.Level
	LogLevel.UnmarshalText([]byte(logLevel))
	baoLogger = slog.New(baoConfig.NewBaoHandler(logWriter, &slog.HandlerOptions{
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
	if logWriter != os.Stderr {
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
	RootCmd.PersistentFlags().IntVar(&flgTimeout, flgTimeoutName, 60,
		"Time, in seconds, the client will wait for each request before returning timeout exceeded error")
	RootCmd.PersistentFlags().StringVar(&flgLogLevel, flgLogLevelName, "INFO",
		"Minimum log level printed in the logs")
}
