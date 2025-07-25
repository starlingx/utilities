//
// Copyright (c) 2025 Wind River Systems, Inc.
//
// SPDX-License-Identifier: Apache-2.0
//

package baoConfig

import (
	"fmt"
	"io"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/go-yaml/yaml"
	openbao "github.com/openbao/openbao/api/v2"
)

type OpenbaoAddress struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
}

type Token struct {
	Duration int    `yaml:"duration"`
	Key      string `yaml:"key"`
}

type KeyShards struct {
	Key       string `yaml:"key"`
	KeyBase64 string `yaml:"key_base64"`
}

type MonitorConfig struct {
	// A map value listing all DNS names
	// Key: Domain name
	// Value: OpenbaoAddress. consisting of host address and port number
	OpenbaoAddresses map[string]OpenbaoAddress `yaml:"OpenbaoAddresses"`

	// A map value listing all authentication tokens
	// Key: release id
	// Value: Token. consisting of lease duration and the token key
	Tokens map[string]Token `yaml:"Tokens"`

	// A map value listing all key shards for unseal
	// Key: shard name
	// Value: The shard key and the base64 encoded version of that key
	UnsealKeyShards map[string]KeyShards `yaml:"UnsealKeyShards"`

	// A string of path to the PEM-encoded CA cert file to use to verify
	// Openbao's server SSL certificate
	// Leave this empty if using the default CA cert file location
	CACert string `yaml:"CACert"`

	// ClientCert is the path to the certificate for Vault communication
	ClientCert string `yaml:"ClientCert"`

	// ClientKey is the path to the private key for Vault communication
	ClientKey string `yaml:"ClientKey"`

	// The path of the log file
	LogPath string `yaml:"logPath"`

	// The default log level
	// Available log levels: DEBUG, INFO, WARN and ERROR
	LogLevel string `yaml:"logLevel"`

	// The time in seconds waited between each unseal check in the run command.
	// If this is unset or set to 0, the command option can be used to supply the time.
	// If neither is supplied, then default time of 5 seconds will be used.
	WaitInterval int `yaml:"WaitInterval"`

	// Time, in seconds, the openbao client will wait for each request before
	// returning timeout exceeded error.
	// Set this value in negative to use the default value of 60 seconds.
	Timeout int `yaml:"Timeout"`

	// Namespace used for openbao.
	// Default is "openbao"
	Namespace string `yaml:"Namespace"`

	// Default port for all addresses.
	// If the port number was not specified in the config file, it will use this port number.
	// This port number will also be used for all generated addresses from Kubernetes pods
	// Default value is always 8200
	DefaultPort int `yaml:"DefaultPort"`

	// Prefix string used to find all openbao server pods
	// Default is "stx-openbao"
	PodPrefix string `yaml:"PodPrefix"`

	// Suffix string for all generated pod addresses
	// Default is "pod.cluster.local"
	PodAddressSuffix string `yaml:"PodAddressSuffix"`

	// Prefix string used to find root token and unseal key shards
	// Default is "cluster-key"
	SecretPrefix string `yaml:"SecretPrefix"`
}

func (configInstance *MonitorConfig) ReadYAMLMonitorConfig(in io.Reader) error {
	data, err := io.ReadAll(in)
	if err != nil {
		return fmt.Errorf(
			"unable to read Host DNS config data from input. Error message: %v", err)
	}

	err = yaml.Unmarshal(data, configInstance)
	if err != nil {
		return fmt.Errorf(
			"unable to unmarshal Host DNS config YAML data. Error message: %v", err)
	}

	// Use default port value of 8200, if no default port was specified.
	if configInstance.DefaultPort == 0 {
		configInstance.DefaultPort = 8200
	}

	// Fill in empty ports
	for dnsname, addr := range configInstance.OpenbaoAddresses {
		if addr.Port == 0 {
			addr.Port = configInstance.DefaultPort
			configInstance.OpenbaoAddresses[dnsname] = addr
		}
	}

	// Validate YAML input for OpenbaoAddresses
	err = configInstance.validateDNS()
	if err != nil {
		return err
	}

	// Validate YAML input for Tokens
	err = configInstance.validateTokens()
	if err != nil {
		return err
	}

	// Validate YAML input for unseal key shards
	err = configInstance.validateKeyShards()
	if err != nil {
		return err
	}

	// Validate YAML input for CACert
	err = configInstance.validateCACert()
	if err != nil {
		return err
	}

	// Validate YAML input for log configs
	err = configInstance.validateLogConfig()
	if err != nil {
		return err
	}

	return nil
}

func (configInstance MonitorConfig) WriteYAMLMonitorConfig(out io.Writer) error {
	data, err := yaml.Marshal(configInstance)
	if err != nil {
		return fmt.Errorf(
			"unable to marshal Host DNS config data to YAML. Error message: %v", err)
	}

	_, err = out.Write(data)
	if err != nil {
		return fmt.Errorf(
			"unable to write marshaled Host DNS config YAML data. Error message: %v", err)
	}

	return nil
}

// Create a new openbao config based on the monitor config
func (configInstance MonitorConfig) NewOpenbaoConfig(dnshost string) (*openbao.Config, error) {
	slog.Debug(fmt.Sprintf("Setting up api access config for host %v", dnshost))
	defConfig := openbao.DefaultConfig()

	// Check if DefaultConfig has issues
	if defConfig.Error != nil {
		return defConfig, fmt.Errorf("issue found in openbao default config: %v", defConfig.Error)
	}
	slog.Debug("No issues found in retrieving openbao default config.")

	// Check if there is a domain name listed under OpenbaoAddresses
	dnsAddr, ok := configInstance.OpenbaoAddresses[dnshost]
	if !ok {
		return defConfig, fmt.Errorf("unable to find %v under the list of available DNS names", dnshost)
	}

	// Set the DNS address as the address to openbao
	defConfig.Address = strings.Join([]string{"https://", dnsAddr.Host, ":", strconv.Itoa(dnsAddr.Port)}, "")

	slog.Debug(fmt.Sprintf("Openbao address set to %v", defConfig.Address))

	// Apply CACert entry to openbao config
	var newTLSconfig openbao.TLSConfig
	slog.Debug("Applying the following cert configs:")
	slog.Debug(fmt.Sprintf("CACert: %v", configInstance.CACert))
	slog.Debug(fmt.Sprintf("ClientCert: %v", configInstance.ClientCert))
	slog.Debug(fmt.Sprintf("ClientKey: %v", configInstance.ClientKey))

	newTLSconfig.CACert = configInstance.CACert
	newTLSconfig.ClientCert = configInstance.ClientCert
	newTLSconfig.ClientKey = configInstance.ClientKey

	// This does nothing if newTLSconfig is empty
	err := defConfig.ConfigureTLS(&newTLSconfig)
	if err != nil {
		return defConfig, fmt.Errorf("error with configuring TLS for openbao: %v", err)
	}

	slog.Debug("Configuring TLS successful")

	// Set the timeout value. Do not set the value if it is negative.
	if configInstance.Timeout >= 0 {
		defConfig.Timeout = time.Duration(configInstance.Timeout) * time.Second
	}

	slog.Debug("Openbao api access config setup complete.")
	// Config creation complete.
	return defConfig, nil
}

func (configInstance MonitorConfig) SetupClient(dnshost string) (*openbao.Client, error) {
	slog.Debug(fmt.Sprintf("Setting up client for host %v", dnshost))
	newConfig, err := configInstance.NewOpenbaoConfig(dnshost)
	if err != nil {
		return nil, fmt.Errorf("error in creating new config for openbao: %v", err)
	}

	slog.Debug("Creating Openbao client for API access...")
	newClient, err := openbao.NewClient(newConfig)
	if err != nil {
		return nil, fmt.Errorf("error in creating new client for openbao: %v", err)
	}

	slog.Debug("Client setup complete.")
	return newClient, nil
}

// Parse the new keys from the init responce into the monitor config
func (configInstance *MonitorConfig) ParseInitResponse(dnshost string, responce *openbao.InitResponse) error {
	slog.Debug("Parsing response from /sys/init to monitor configs")

	keyShardheader := strings.Join([]string{"key", "shard", dnshost}, "-")

	slog.Debug("Parsing the root token...")
	// Parse in the root token
	if _, ok := configInstance.Tokens["root_token"]; ok {
		return fmt.Errorf("an entry of the root token was already found")
	}
	if configInstance.Tokens == nil {
		configInstance.Tokens = make(map[string]Token)
	}
	configInstance.Tokens["root_token"] = Token{
		Duration: 0,
		Key:      responce.RootToken,
	}

	slog.Debug("Parsing the unseal key shards...")
	// Parse in the key shards for unseal
	for i := range len(responce.Keys) {
		keyShardName := strings.Join([]string{keyShardheader, strconv.Itoa(i)}, "-")
		if _, ok := configInstance.UnsealKeyShards[keyShardName]; ok {
			return fmt.Errorf("an entry of %v was already found under UnsealKeyShards", keyShardName)
		}
		if configInstance.UnsealKeyShards == nil {
			configInstance.UnsealKeyShards = make(map[string]KeyShards)
		}
		configInstance.UnsealKeyShards[keyShardName] = KeyShards{
			Key:       responce.Keys[i],
			KeyBase64: responce.KeysB64[i],
		}
	}

	slog.Debug("Parsing the recovery key shards...")
	// Parse in the recovery key shards
	for i := range len(responce.RecoveryKeys) {
		keyShardName := strings.Join([]string{keyShardheader, "recovery", strconv.Itoa(i)}, "-")
		if _, ok := configInstance.UnsealKeyShards[keyShardName]; ok {
			return fmt.Errorf("an entry of %v was already found under UnsealKeyShards", keyShardName)
		}
		if configInstance.UnsealKeyShards == nil {
			configInstance.UnsealKeyShards = make(map[string]KeyShards)
		}
		configInstance.UnsealKeyShards[keyShardName] = KeyShards{
			Key:       responce.RecoveryKeys[i],
			KeyBase64: responce.RecoveryKeysB64[i],
		}
	}

	slog.Debug("Parsing init response complete")
	return nil
}
