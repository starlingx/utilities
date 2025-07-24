//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoCommands

import (
	"fmt"
	"os"

	baoConfig "github.com/michel-thebeau-WR/openbao-manager-go/baomon/config"
	"github.com/spf13/cobra"
	yaml "sigs.k8s.io/yaml/goyaml.v3"
)

var dumpConfigReadCmd = &cobra.Command{
	Use:   "read readFile",
	Short: "Read config from a YAML file",
	Long:  "Read baomon configuration from a specified YAML file, and prints to stdout",
	Args:  cobra.ExactArgs(1),
	RunE: func(cmd *cobra.Command, args []string) error {
		var S baoConfig.MonitorConfig
		openedFile, err := os.Open(args[0])
		if err != nil {
			return err
		}
		defer openedFile.Close()

		err = S.ReadYAMLMonitorConfig(openedFile)
		if err != nil {
			return err
		}
		fmt.Printf("Result: \n%#v\n", S)

		return nil
	},
}

var dumpConfigWriteCmd = &cobra.Command{
	Use:   "write readFile readWrite",
	Short: "Write config to another YAML file",
	Long:  "Copy a config file from the first file to the second file, using baoConfig's write method",
	Args:  cobra.ExactArgs(2),
	RunE: func(cmd *cobra.Command, args []string) error {
		var S baoConfig.MonitorConfig
		openedFile, err := os.Open(args[0])
		if err != nil {
			return err
		}
		defer openedFile.Close()

		err = S.ReadYAMLMonitorConfig(openedFile)
		if err != nil {
			return err
		}

		writeFile, err := os.Create(args[1])
		if err != nil {
			return err
		}
		defer writeFile.Close()

		err = S.WriteYAMLMonitorConfig(writeFile)
		if err != nil {
			return err
		}

		fmt.Print("Write Complete\n")
		return nil
	},
}

var dumpConfigPrintGlobal = &cobra.Command{
	Use:                "global",
	Short:              "Dev command that prints current global config",
	Long:               "Dev command that prints current global config. For testing setup & clean",
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		configBytes, err := yaml.Marshal(globalConfig)
		if err != nil {
			return err
		}
		fmt.Println(string(configBytes))
		return nil
	},
}

var dumpConfigCmd = &cobra.Command{
	Use:   "dumpConfig",
	Short: "Dev command for read/write YAML config files",
	Long:  `A dev command for interacting with the baoConfig package using a YAML file.`,
}

func init() {
	dumpConfigCmd.AddCommand(dumpConfigReadCmd)
	dumpConfigCmd.AddCommand(dumpConfigWriteCmd)
	dumpConfigCmd.AddCommand(dumpConfigPrintGlobal)
	RootCmd.AddCommand(dumpConfigCmd)
}
