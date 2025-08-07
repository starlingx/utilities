package baoConfig

import (
	"encoding/base64"
	"fmt"
	"os"
	"path"
	"regexp"
	"strconv"
)

// Available log levels; these should match the levels available in helm chart
var availableLogLevels = map[int]string{
		1: "DEBUG",
		2: "INFO",
		3: "WARN",
		4: "ERROR",
		5: "ERROR",
}

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
	var found bool = false

	if configInstance.LogPath != "" {
		_, err := os.Stat(path.Dir(configInstance.LogPath))
		if err != nil {
			return fmt.Errorf(
				"error in checking the parent directory of LogPath. Error message: %v", err)
		}
	}
	if configInstance.LogLevel != "" {
		if converted, err := strconv.Atoi(configInstance.LogLevel); err == nil {
			// convert the numeric log level to string
			if _, exists := availableLogLevels[converted]; exists {
				// pass, Accept the numeric LogLevel
			} else {
				return fmt.Errorf(
					"the numeric LogLevel %v is not a valid log level", configInstance.LogLevel)
			}
		} else {
			// Check if the LogLevel is one of the available log levels
			for _, value := range availableLogLevels {
				if value == configInstance.LogLevel {
					// Accept LogLevel
					found = true
					break
				}
			}
			if !found {
				return fmt.Errorf(
					"the listed LogLevel %v is not a valid log level", configInstance.LogLevel)
			}
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
