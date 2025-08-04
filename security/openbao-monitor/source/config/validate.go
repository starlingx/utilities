package baoConfig

import (
	"encoding/base64"
	"fmt"
	"os"
	"path"
	"regexp"
	"slices"
)

func (configInstance MonitorConfig) validateDNS() error {
	for domain_name, url := range configInstance.ServerAddresses {
		// If Host is empty, then the domain entry is invalid
		// The ports will always at least have the default value of 8200
		if url.Host == "" {
			return fmt.Errorf(
				"the domain entry %v in ServerAddresses is invalid", domain_name)
		}
	}

	return nil
}

func (configInstance MonitorConfig) validateTokens() error {
	rootExists := false
	r, _ := regexp.Compile("[sbr][.][a-zA-Z0-9]{24,}")
	for releaseID, token := range configInstance.Tokens {
		if token.Duration == 0 {
			// There can only be one root token
			if rootExists {
				return fmt.Errorf("there are two or more root tokens listed")
			} else {
				rootExists = true
			}
		}
		// Token key should have s, b, or r as the first character, and . as the second.
		// The body of the token (key[2:]) should be 24 characters or more
		if !r.MatchString(token.Key) {
			return fmt.Errorf(
				"the token with release id %v has wrong key format", releaseID)
		}
	}

	return nil
}

func (configInstance MonitorConfig) validateKeyShards() error {
	for shardName, shard := range configInstance.UnsealKeyShards {
		// A shard should have both its key and base64 key non-empty
		if shard.Key == "" || shard.KeyBase64 == "" {
			return fmt.Errorf("shard %v has missing keys", shardName)
		}
		// Base64 encoded keys must be able to be decoded with no errors
		_, err := base64.StdEncoding.DecodeString(shard.KeyBase64)
		if err != nil {
			return fmt.Errorf(
				"error with validating if %v has a correct base64 encoded key: %v", shardName, err)
		}
	}

	return nil
}

func (configInstance MonitorConfig) validateLogConfig() error {
	if configInstance.LogPath != "" {
		_, err := os.Stat(path.Dir(configInstance.LogPath))
		if err != nil {
			return fmt.Errorf(
				"error in checking the parent directory of LogPath. Error message: %v", err)
		}
	}
	if configInstance.LogLevel != "" {
		availableLogLevels := []string{"DEBUG", "INFO", "WARN", "ERROR"}
		if !slices.Contains(availableLogLevels, configInstance.LogLevel) {
			return fmt.Errorf(
				"the listed LogLevel %v is not a valid log level", configInstance.LogLevel)
		}
	}

	return nil
}

func (configInstance MonitorConfig) validateCACert() error {
	if configInstance.CACert != "" {
		_, err := os.Stat(configInstance.CACert)
		if err != nil {
			return fmt.Errorf(
				"error in checking the path of CACert. Error message: %v", err)
		}
	}

	return nil
}
