package baoCommands

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"strings"

	clientapi "github.com/openbao/openbao/api/v2"
	"github.com/spf13/cobra"
)

var customPayload string
var raftAddress string

var joinraftCmd = &cobra.Command{
	Use:   "joinRaft node",
	Short: "Joins the node to the raft cluster",
	Long: `Joins the node to the raft cluster.

The node will join the raft cluster, with the leader node address specified in
the flag raft-address. It will use the CACert file specified in the baomon
configs.

Or, the raft cluster specifications can be contained in a JSON file, which can
be pointed by the flag raft-config. Please consult the /sys/storage/raft page
in the Openbao API documentations for details.

One of the two above flags must be used to specify the raft cluster. Otherwise
the command will not run.
`,
	Args:               cobra.ExactArgs(1),
	PersistentPreRunE:  setupCmd,
	PersistentPostRunE: cleanCmd,
	RunE: func(cmd *cobra.Command, args []string) error {
		slog.Debug(fmt.Sprintf("Starting joinRaft for node %v", args[0]))
		newClient, err := globalConfig.SetupClient(args[0])
		if err != nil {
			return fmt.Errorf("joinRaft failed with error: %v", err)
		}
		var RJReq clientapi.RaftJoinRequest
		if customPayload != "" {
			payloadbuf, err := os.ReadFile(customPayload)
			if err != nil {
				return fmt.Errorf("unable to open file for raft-config %v: %v", customPayload, err)
			}
			err = json.Unmarshal(payloadbuf, &RJReq)
			if err != nil {
				return fmt.Errorf("unable to marshal raft-config %v: %v", customPayload, err)
			}
		} else if raftAddress != "" {
			RJReq.LeaderAPIAddr = raftAddress
			cacertbuf, err := os.ReadFile(globalConfig.CACert)
			if err != nil {
				return fmt.Errorf("error with trying to read the CACert file in the configs: %v", err)
			}
			// Trim the trailing newline if it exists.
			cacert := strings.TrimSuffix(string(cacertbuf), "\n")
			RJReq.LeaderCACert = cacert
		} else {
			return fmt.Errorf("either raft-config or raft-address must be specified")
		}
		slog.Debug("Calling RaftJoin API command...")
		RJRes, err := newClient.Sys().RaftJoin(&RJReq)
		if err != nil {
			return fmt.Errorf("joinRaft failed with error: %v", err)
		}
		if RJRes.Joined {
			slog.Info(fmt.Sprintf("joinRaft successful for node %v.", args[0]))
			return nil
		} else {
			return fmt.Errorf("joinRaft unable to join node %v with no errors from API", args[0])
		}
	},
}

func init() {
	joinraftCmd.PersistentFlags().StringVar(&customPayload, "raft-config", "",
		"A JSON file containing the API parameters for joinRaft")
	joinraftCmd.PersistentFlags().StringVar(&raftAddress, "raft-address", "",
		"Address of the leader node in the raft cluster")
	RootCmd.AddCommand(joinraftCmd)
}
