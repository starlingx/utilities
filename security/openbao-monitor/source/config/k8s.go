package baoConfig

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"strings"

	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

// Default values in case the values are not included in the config
var openbaoNamespace string = "openbao"
var podPort int = 8200
var podPrefix string = "stx-openbao"
var podAddressSuffix string = "pod.cluster.local"
var secretPrefix string = "cluster-key"

type keySecret struct {
	Key        []string `json:"keys"`
	KeyEncoded []string `json:"keys_base64"`
}

// Get list of DNS names fro k8s pods
func (configInstance *MonitorConfig) MigratePodConfig(config *rest.Config) error {
	slog.Debug("Migrating openbao addresses from kubernetes openbao server pods")
	// Use the settings from config if they aren't empty
	if configInstance.Namespace != "" {
		openbaoNamespace = configInstance.Namespace
	}
	if configInstance.DefaultPort != 0 {
		podPort = configInstance.DefaultPort
	}
	if configInstance.PodPrefix != "" {
		podPrefix = configInstance.PodPrefix
	}
	if configInstance.PodAddressSuffix != "" {
		podAddressSuffix = configInstance.PodAddressSuffix
	}

	slog.Debug("Setting up kubernetes client...")
	// create clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return err
	}
	slog.Debug("Setting up kubernetes client complete")

	// client for core
	coreClient := clientset.CoreV1()
	ctx := context.Background()

	slog.Debug("Accessing openbao server pods for the addresses...")
	// get pod list
	pods, err := coreClient.Pods(openbaoNamespace).List(ctx, metaV1.ListOptions{})
	if err != nil {
		return err
	}

	// clear existing DNS names
	configInstance.OpenbaoAddresses = make(map[string]OpenbaoAddress)

	// Use pod and its ip to fill in the "OpenbaoAddresses" section
	r, _ := regexp.Compile(fmt.Sprintf("%v-\\d$", podPrefix))
	for _, pod := range pods.Items {
		podName := pod.ObjectMeta.Name
		if r.Match([]byte(podName)) {
			podIP := pod.Status.PodIP
			podURL := fmt.Sprintf("%v.%v.%v", strings.ReplaceAll(podIP, ".", "-"), openbaoNamespace, podAddressSuffix)
			configInstance.OpenbaoAddresses[podName] = OpenbaoAddress{podURL, podPort}
		}
	}
	slog.Debug("All addresses obtained.")

	// Validate input for OpenbaoAddresses
	err = configInstance.validateDNS()
	if err != nil {
		return err
	}

	slog.Debug("Openbao address migration complete.")
	return nil
}

// Get root token and unseal key shards from k8s secrets
func (configInstance *MonitorConfig) MigrateSecretConfig(config *rest.Config) error {
	slog.Debug("Migrating root-token and unseal key shards from openbao kubernetes secrets")
	// Use the settings from config if they aren't empty
	if configInstance.Namespace != "" {
		openbaoNamespace = configInstance.Namespace
	}
	if configInstance.SecretPrefix != "" {
		secretPrefix = configInstance.SecretPrefix
	}

	slog.Debug("Setting up kubernetes client...")
	// create clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return err
	}
	slog.Debug("Setting up kubernetes client complete")

	// client for secret
	secretClient := clientset.CoreV1().Secrets(openbaoNamespace)

	ctx := context.Background()

	slog.Debug("Accessing openbao secrets for the info...")
	// get secrets list
	secrets, err := secretClient.List(ctx, metaV1.ListOptions{})
	if err != nil {
		return err
	}

	// Clear existing configs
	configInstance.Tokens = make(map[string]Token)
	configInstance.UnsealKeyShards = make(map[string]KeyShards)

	// Use secrets to fill in the "Tokens" and "UnsealKeyShards" section
	for _, secret := range secrets.Items {
		secretName := secret.ObjectMeta.Name
		if strings.HasPrefix(secretName, secretPrefix) {
			secretData := secret.Data["strdata"]
			if strings.HasSuffix(secretName, "root") {
				// secretData should be the root token
				configInstance.Tokens[secretName] = Token{Duration: 0, Key: string(secretData)}
			} else {
				// secretData should be an unseal key shard and its base 64 encoded version
				var newKey keySecret
				err := json.Unmarshal(secretData, &newKey)
				if err != nil {
					return err
				}
				configInstance.UnsealKeyShards[secretName] = KeyShards{
					Key:       newKey.Key[0],
					KeyBase64: newKey.KeyEncoded[0],
				}
			}
		}
	}
	slog.Debug("Root token and unseal key shards obtained.")

	// Validate input for Tokens
	err = configInstance.validateTokens()
	if err != nil {
		return err
	}

	// Validate input for unseal key shards
	err = configInstance.validateKeyShards()
	if err != nil {
		return err
	}

	slog.Debug("Migrating root token and unseal key shards complete.")
	return nil
}

// Get both configs
func (configInstance *MonitorConfig) MigrateK8sConfig(config *rest.Config) error {

	err := configInstance.MigratePodConfig(config)
	if err != nil {
		return err
	}

	err = configInstance.MigrateSecretConfig(config)
	if err != nil {
		return err
	}

	return nil
}
