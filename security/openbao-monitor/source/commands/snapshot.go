package baoCommands

import (
	"fmt"
	"log/slog"
	"os"

	"github.com/spf13/cobra"
)

var forceCmd bool

var snapshotCmd = &cobra.Command{
	Use:   "snapshot",
	Short: "All snapshot related commands",
	Long:  "Suite of all snapshot related commands.",
}

var precheckCmd = &cobra.Command{
	Use:   "precheck",
	Short: "Ready check for snapshot",
	Long: `A list of checks to be done before snapshot creation:
- All server pods must be unsealed

Please make sure all conditions are fulfilled before attempting
to create a snapshot.
`,
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot precheck...")
		for host, _ := range globalConfig.ServerAddresses {
			newClient, err := globalConfig.SetupClient(host)
			if err != nil {
				return fmt.Errorf("openbao client setup failed with error: %v", err)
			}
			healthResult, err := checkHealth(host, newClient)
			if err != nil {
				return fmt.Errorf("server health failed with error: %v", err)
			}
			if healthResult.Sealed {
				return fmt.Errorf("openbao host %v is currently sealed", host)
			}
		}
		slog.Info("Snapshot precheck successful.")
		return nil
	},
}

var snapshotCreateCmd = &cobra.Command{
	Use:   "create DNShost filename",
	Short: "Create a snapshot for openbao",
	Long: `Create a snapshot tarball for the openbao server.
The result is stored as a tarball to the specified filename.
`,
	Args:               cobra.ExactArgs(2),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot create...")
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao client setup failed with error: %v", err)
		}
		snapFile, err := os.Create(args[1])
		if err != nil {
			return fmt.Errorf("unable to create file %v: %v", args[1], err)
		}
		defer snapFile.Close()
		err = newClient.Sys().RaftSnapshot(snapFile)
		if err != nil {
			return fmt.Errorf("snapshot create failed with error: %v", err)
		}
		slog.Info("Snapshot create successful.")

		return nil
	},
}

var snapshotRestoreCmd = &cobra.Command{
	Use:                "restore DNShost filename",
	Short:              "Restore openbao from a snapshot",
	Long:               "Restore the openbao server from a generated snapshot tarball",
	Args:               cobra.ExactArgs(2),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug("Running snapshot restore...")
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("openbao client setup failed with error: %v", err)
		}
		snapFile, err := os.Open(args[1])
		if err != nil {
			return fmt.Errorf("unable to open file %v: %v", args[1], err)
		}
		defer snapFile.Close()
		err = newClient.Sys().RaftSnapshotRestore(snapFile, forceCmd)
		if err != nil {
			return fmt.Errorf("snapshot restore failed with error: %v", err)
		}
		slog.Info("Snapshot restore successful.")

		return nil
	},
}

func init() {
	snapshotRestoreCmd.PersistentFlags().BoolVar(&forceCmd, "force", false, "force restore command")
	snapshotCmd.AddCommand(precheckCmd)
	snapshotCmd.AddCommand(snapshotCreateCmd)
	snapshotCmd.AddCommand(snapshotRestoreCmd)
	RootCmd.AddCommand(snapshotCmd)
}
