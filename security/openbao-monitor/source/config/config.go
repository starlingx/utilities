//
// Copyright (c) 2025-2026 Wind River Systems, Inc.
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

	clientapi "github.com/openbao/openbao/api/v2"
	"gopkg.in/yaml.v3"
	"k8s.io/client-go/kubernetes"
)

type ServerAddress struct {
	Host string `yaml:"host"`
	Port int    `yaml:"port"`
}

type Token struct {
	Duration int    `yaml:"duration"`
	Key      string `yaml:"key"`
}

type KeyShards struct {
	Key       string `yaml:"key" json:"key"`
	KeyBase64 string `yaml:"key_base64" json:"key_base64"`
}

type MonitorConfig struct {
	// A map value listing all DNS names
	// Key: Domain name
	// Value: ServerAddress. consisting of host address and port number
	ServerAddresses map[string]ServerAddress `yaml:"ServerAddresses"`

	// A map value listing all authentication tokens
	// Key: release id
	// Value: Token. consisting of lease duration and the token key
	Tokens map[string]Token `yaml:"Tokens"`

	// A map value listing all key shards for unseal
	// Key: shard name
	// Value: The shard key and the base64 encoded version of that key
	UnsealKeyShards map[string]KeyShards `yaml:"UnsealKeyShards"`

	// A string of path to the PEM-encoded CA cert file to use to verify
	// The server's SSL certificate
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
	// Accepts numeric values matching helm chart log levels (4-5 are interpreted as ERROR)
	LogLevel string `yaml:"logLevel"`

	// The time in seconds waited between each unseal check in the run command.
	// If this is unset or set to 0, the command option can be used to supply the time.
	// If neither is supplied, then default time of 5 seconds will be used.
	WaitInterval int `yaml:"WaitInterval"`

	// Time, in seconds, the client will wait for each request before
	// returning timeout exceeded error.
	// Set this value in negative to use the default value of 60 seconds.
	Timeout int `yaml:"Timeout"`

	// Namespace used for the k8s application.
	Namespace string `yaml:"Namespace"`

	// Default port for all addresses.
	// If the port number was not specified in the config file, it will use this port number.
	// This port number will also be used for all generated addresses from Kubernetes pods
	// Default value is always 8200
	DefaultPort int `yaml:"DefaultPort"`

	// Prefix string used to find all server pods
	PodPrefix string `yaml:"PodPrefix"`

	// Suffix string for all generated pod addresses
	// Default is "pod.cluster.local"
	PodAddressSuffix string `yaml:"PodAddressSuffix"`

	// Prefix string used to find root token and unseal key shards
	// Default is "cluster-key"
	// DEPRECATED: kept for migration compatibility
	SecretPrefix string `yaml:"SecretPrefix"`

	// GenerationPrefix is the naming prefix for generation secrets.
	// Default: "openbao-unseal-gen"
	GenerationPrefix string `yaml:"GenerationPrefix"`

	// CurrentKeySecret names the k8s secret holding the active generation's keys.
	// Example: "openbao-unseal-gen-001"
	CurrentKeySecret string `yaml:"CurrentKeySecret"`

	// loadedGenerationSecret caches the active generation secret data in memory
	// after it has been loaded from Kubernetes. This is not serialized to YAML.
	loadedGenerationSecret *GenerationSecret `yaml:"-"`

	// Clientset is the Kubernetes client used for all K8s operations.
	// Set programmatically at startup; not serialized to YAML.
	// Tests can set this to a fake clientset.
	Clientset kubernetes.Interface `yaml:"-"`

	// Indicates if openbao is run in a kubernetes environment
	// Default is false
	UseK8sConfig bool `yaml:"k8s"`

	// Indicates if baomon is run in a kubernetes pod
	// Default is false
	UseInClusterConfig bool `yaml:"in-cluster"`
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
	for dnsname, addr := range configInstance.ServerAddresses {
		if addr.Port == 0 {
			addr.Port = configInstance.DefaultPort
			configInstance.ServerAddresses[dnsname] = addr
		}
	}

	// Validate YAML input for ServerAddresses
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

func (configInstance *MonitorConfig) GetRootTokenName() string {
	prefix := "cluster-key"
	if configInstance.SecretPrefix != "" {
		prefix = configInstance.SecretPrefix
	}
	return prefix + "-root"
}

// GetCurrentRootToken extracts the root token from the active generation secret.
// If a generation secret is loaded in memory, it returns that root token.
// Otherwise it falls back to the legacy Tokens map lookup.
func (configInstance *MonitorConfig) GetCurrentRootToken() string {
	if configInstance.loadedGenerationSecret != nil {
		return configInstance.loadedGenerationSecret.RootToken
	}

	// Fallback to legacy token lookup
	rootTokenName := configInstance.GetRootTokenName()
	if token, ok := configInstance.Tokens[rootTokenName]; ok {
		return token.Key
	}

	return ""
}

// GetUnsealKeys returns the unseal key list from the active generation secret.
// GetCurrentKeySecret returns the name of the currently active generation secret.
func (configInstance *MonitorConfig) GetCurrentKeySecret() string {
	return configInstance.CurrentKeySecret
}

// If a generation secret is loaded in memory, it returns those keys.
// Otherwise it falls back to the legacy UnsealKeyShards map.
func (configInstance *MonitorConfig) GetUnsealKeys() []string {
	if configInstance.loadedGenerationSecret != nil {
		return configInstance.loadedGenerationSecret.Keys
	}

	// Fallback to legacy unseal key shards
	var keys []string
	for _, shard := range configInstance.UnsealKeyShards {
		keys = append(keys, shard.Key)
	}
	return keys
}

// SetLoadedGenerationSecret sets the in-memory cached generation secret.
// This is called after loading a generation secret from Kubernetes.
func (configInstance *MonitorConfig) SetLoadedGenerationSecret(secret *GenerationSecret) {
	configInstance.loadedGenerationSecret = secret
}

// GetLoadedGenerationSecret returns the in-memory cached generation secret.
func (configInstance *MonitorConfig) GetLoadedGenerationSecret() *GenerationSecret {
	return configInstance.loadedGenerationSecret
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

// Create a new config based on the monitor config
func (configInstance MonitorConfig) NewConfig(dnshost string) (*clientapi.Config, error) {
	slog.Debug("Setting up API access config", "host", dnshost)
	defConfig := clientapi.DefaultConfig()

	// Check if DefaultConfig has issues
	if defConfig.Error != nil {
		return defConfig, fmt.Errorf("issue found in default config: %v", defConfig.Error)
	}
	slog.Debug("No issues found in retrieving default config.")

	// Check if there is a domain name listed under ServerAddresses
	dnsAddr, ok := configInstance.ServerAddresses[dnshost]
	if !ok {
		return defConfig, fmt.Errorf("unable to find %v under the list of available DNS names", dnshost)
	}

	// Set the DNS address as the configured address for the server
	defConfig.Address = strings.Join([]string{"https://", dnsAddr.Host, ":", strconv.Itoa(dnsAddr.Port)}, "")

	slog.Debug("Server address set", "address", defConfig.Address)

	// Apply CACert entry to the config
	var newTLSconfig clientapi.TLSConfig
	slog.Debug("Applying the following cert configs:")
	slog.Debug("CACert configured", "path", configInstance.CACert)
	slog.Debug("ClientCert configured", "path", configInstance.ClientCert)
	slog.Debug("ClientKey configured", "path", configInstance.ClientKey)

	newTLSconfig.CACert = configInstance.CACert
	newTLSconfig.ClientCert = configInstance.ClientCert
	newTLSconfig.ClientKey = configInstance.ClientKey

	// This does nothing if newTLSconfig is empty
	err := defConfig.ConfigureTLS(&newTLSconfig)
	if err != nil {
		return defConfig, fmt.Errorf("configuring TLS: %w", err)
	}

	slog.Debug("Configuring TLS successful")

	// Set the timeout value. Do not set the value if it is negative.
	if configInstance.Timeout >= 0 {
		defConfig.Timeout = time.Duration(configInstance.Timeout) * time.Second
	}

	slog.Debug("API access config setup complete.")
	// Config creation complete.
	return defConfig, nil
}

func (configInstance *MonitorConfig) SetupClient(dnshost string) (*clientapi.Client, error) {
	slog.Debug("Setting up client", "host", dnshost)
	newConfig, err := configInstance.NewConfig(dnshost)
	if err != nil {
		return nil, fmt.Errorf("creating new config: %w", err)
	}

	slog.Debug("Creating client for API access...")
	newClient, err := clientapi.NewClient(newConfig)
	if err != nil {
		return nil, fmt.Errorf("creating new client: %w", err)
	}

	// GetCurrentRootToken handles both generation-based and legacy token lookup.
	rootToken := configInstance.GetCurrentRootToken()
	if rootToken != "" {
		newClient.SetToken(rootToken)
	}

	slog.Debug("Client setup complete.")
	return newClient, nil
}

// ParseInitResponseToGeneration converts an InitResponse directly into a GenerationSecret.
// This is the preferred method for new code paths (generation-based storage).
func ParseInitResponseToGeneration(response *clientapi.InitResponse) (*GenerationSecret, error) {
	secret := &GenerationSecret{
		Keys:       response.Keys,
		KeysBase64: response.KeysB64,
		RootToken:  response.RootToken,
	}
	if err := ValidateGenerationSecret(secret); err != nil {
		return nil, fmt.Errorf("init response produced invalid generation secret: %w", err)
	}
	return secret, nil
}

// ParseInitResponse parses the new keys from the init response into the monitor config.
// Deprecated: Use ParseInitResponseToGeneration for new code paths that use generation-based
// secret storage. This method is retained for backward compatibility with legacy per-shard storage.
func (configInstance *MonitorConfig) ParseInitResponse(dnshost string, response *clientapi.InitResponse) error {
	slog.Debug("Parsing response from /sys/init to monitor configs")

	slog.Debug("Parsing the root token...")
	// Parse in the root token
	rootTokenName := configInstance.GetRootTokenName()
	if _, ok := configInstance.Tokens[rootTokenName]; ok {
		return fmt.Errorf("an entry of the root token was already found")
	}
	if configInstance.Tokens == nil {
		configInstance.Tokens = make(map[string]Token)
	}
	configInstance.Tokens[rootTokenName] = Token{
		Duration: 0,
		Key:      response.RootToken,
	}

	slog.Debug("Parsing the unseal key shards...")
	// Parse in the key shards for unseal
	for i := range len(response.Keys) {
		keyShardName := strings.Join([]string{secretPrefix, strconv.Itoa(i)}, "-")
		if _, ok := configInstance.UnsealKeyShards[keyShardName]; ok {
			return fmt.Errorf("an entry of %v was already found under UnsealKeyShards", keyShardName)
		}
		if configInstance.UnsealKeyShards == nil {
			configInstance.UnsealKeyShards = make(map[string]KeyShards)
		}
		configInstance.UnsealKeyShards[keyShardName] = KeyShards{
			Key:       response.Keys[i],
			KeyBase64: response.KeysB64[i],
		}
	}

	slog.Debug("Parsing the recovery key shards...")
	// Parse in the recovery key shards
	for i := range len(response.RecoveryKeys) {
		keyShardName := strings.Join([]string{secretPrefix, "recovery", strconv.Itoa(i)}, "-")
		if _, ok := configInstance.UnsealKeyShards[keyShardName]; ok {
			return fmt.Errorf("an entry of %v was already found under UnsealKeyShards", keyShardName)
		}
		if configInstance.UnsealKeyShards == nil {
			configInstance.UnsealKeyShards = make(map[string]KeyShards)
		}
		configInstance.UnsealKeyShards[keyShardName] = KeyShards{
			Key:       response.RecoveryKeys[i],
			KeyBase64: response.RecoveryKeysB64[i],
		}
	}

	slog.Debug("Parsing init response complete")
	return nil
}

// Interpret numeric or text log level
// Always returns a log level in string format
func (configInstance *MonitorConfig) InterpretLogLevel() string {
	// Check if the log level is a number
	if converted, err := strconv.Atoi(configInstance.LogLevel); err == nil {
		if level, exists := availableLogLevels[converted]; exists {
			return level
		}

		// error, but this code should not be reached if validateLogConfig works
		slog.Error("Invalid numeric log level", "level", configInstance.LogLevel)
		return "INFO" // Default to INFO if the numeric level is invalid
	}

	// Default to INFO if no log level was set
	if configInstance.LogLevel == "" {
		return "INFO"
	}

	// validateLogConfig already validated the LogLevel
	return configInstance.LogLevel
}
