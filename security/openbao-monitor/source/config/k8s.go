package baoConfig

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"strings"

	v1 "k8s.io/api/core/v1"
	k8sErrors "k8s.io/apimachinery/pkg/api/errors"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

// Default values in case the values are not included in the config
var k8sNamespace string = "openbao"
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
	slog.Debug("Migrating server addresses from kubernetes server pods")
	// Use the settings from config if they aren't empty
	if configInstance.Namespace != "" {
		k8sNamespace = configInstance.Namespace
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

	slog.Debug("Accessing the server pods for the addresses...")
	// get pod list
	pods, err := coreClient.Pods(k8sNamespace).List(ctx, metaV1.ListOptions{})
	if err != nil {
		return err
	}

	// Build new address map from the pod list before replacing the old one.
	// This ensures that a partial failure (e.g., list succeeded but no pods
	// have IPs yet) does not destroy the previous valid addresses.
	newAddresses := make(map[string]ServerAddress)

	// Use pod and its ip to fill in the "ServerAddresses" section.
	// Bug fix: pods in ContainerCreating or early startup have empty PodIP.
	// Without this check, we'd store an invalid address like
	// ".openbao.pod.cluster.local" which causes health checks to fail with
	// connection errors, preventing the unseal logic from ever being reached.
	// Discovered via robustness test T7 (block apiserver during unseal).
	r := regexp.MustCompile(fmt.Sprintf("%v-\\d$", podPrefix))
	for _, pod := range pods.Items {
		podName := pod.ObjectMeta.Name
		if r.Match([]byte(podName)) {
			podIP := pod.Status.PodIP
			if podIP == "" {
				slog.Debug("Skipping pod with no IP (not yet scheduled or starting)", "pod", podName)
				continue
			}
			podURL := fmt.Sprintf("%v.%v.%v", strings.ReplaceAll(podIP, ".", "-"), k8sNamespace, podAddressSuffix)
			newAddresses[podName] = ServerAddress{podURL, podPort}
		}
	}

	// Only replace addresses if we got at least one valid address,
	// or if no server pods exist at all (legitimate scale-to-zero).
	if len(newAddresses) > 0 || len(pods.Items) == 0 {
		configInstance.ServerAddresses = newAddresses
	} else {
		slog.Warn("No server pods with IP found, retaining previous addresses")
	}
	slog.Debug("All addresses obtained.")

	// Validate input for ServerAddresses
	err = configInstance.validateDNS()
	if err != nil {
		return err
	}

	slog.Debug("Server address migration complete.")
	return nil
}

// Get root token and unseal key shards from k8s secrets
func (configInstance *MonitorConfig) MigrateSecretConfig(config *rest.Config) error {
	slog.Debug("Migrating root-token and unseal key shards from kubernetes secrets")
	// Use the settings from config if they aren't empty
	if configInstance.Namespace != "" {
		k8sNamespace = configInstance.Namespace
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
	secretClient := clientset.CoreV1().Secrets(k8sNamespace)

	ctx := context.Background()

	slog.Debug("Accessing k8s secrets for the info...")
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
				configInstance.Tokens[secretName] = Token{Duration: 0, Key: strings.TrimSpace(string(secretData))}
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

// Stores token and key shards from MonitorConfig to k8s secrets.
// Used to store the output from the init command.
// The stored secrets can be pulled using the MigrateSecretConfig function.
// The token and shard names from the Monitor config must follow
// the k8s secret naming convention.
func (configInstance *MonitorConfig) StoreSecretConfig(config *rest.Config) error {
	slog.Debug("Storing root-token and unseal key shards to kubernetes secrets")
	// Use the settings from config if they aren't empty
	if configInstance.Namespace != "" {
		k8sNamespace = configInstance.Namespace
	}

	slog.Debug("Setting up kubernetes client...")
	// create clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return err
	}
	slog.Debug("Setting up kubernetes client complete")

	// client for secret
	secretClient := clientset.CoreV1().Secrets(k8sNamespace)

	ctx := context.Background()

	for tokenName, token := range configInstance.Tokens {
		newToken := new(v1.Secret)
		newToken.SetName(tokenName)
		newToken.SetNamespace(k8sNamespace)
		newToken.StringData = make(map[string]string)
		newToken.StringData["strdata"] = token.Key
		_, err := secretClient.Create(ctx, newToken, metaV1.CreateOptions{})
		if err != nil {
			return err
		}
	}

	for shardName, shard := range configInstance.UnsealKeyShards {
		newShard := new(v1.Secret)
		newShard.SetName(shardName)
		newShard.SetNamespace(k8sNamespace)
		var newSecret keySecret
		newSecret.Key = append(newSecret.Key, shard.Key)
		newSecret.KeyEncoded = append(newSecret.KeyEncoded, shard.KeyBase64)
		marshalData, err := json.Marshal(newSecret)
		if err != nil {
			return err
		}
		newShard.Data = make(map[string][]byte)
		newShard.Data["strdata"] = marshalData
		_, err = secretClient.Create(ctx, newShard, metaV1.CreateOptions{})
		if err != nil {
			return err
		}
	}

	return nil
}

// StoreGenerationSecret creates a new immutable Kubernetes secret for a key
// generation event. The secret is stored with labels for discovery and its
// data field contains the JSON-marshaled GenerationSecret. On success,
// CurrentKeySecret is updated to genName.
//
// If the secret already exists (AlreadyExists error), the function compares
// the existing data with what we intended to store. If they are identical,
// the operation is treated as a success (idempotent retry). If the data
// differs, a fatal error is returned indicating corruption or conflict.
func (c *MonitorConfig) StoreGenerationSecret(genName string, secret *GenerationSecret) error {
	if c.Clientset == nil {
		return fmt.Errorf("clientset is nil: K8s client not initialized")
	}
	namespace := c.Namespace
	if namespace == "" {
		namespace = k8sNamespace
	}

	slog.Debug("Storing generation secret", "namespace", namespace, "name", genName)

	// Marshal the GenerationSecret to JSON
	data, err := json.Marshal(secret)
	if err != nil {
		return fmt.Errorf("failed to marshal generation secret: %w", err)
	}

	immutable := true
	seqNum := ExtractSeqNum(genName)

	k8sSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      genName,
			Namespace: namespace,
			Labels: map[string]string{
				"app":        "openbao",
				"component":  "unseal-keys",
				"generation": seqNum,
			},
		},
		Immutable: &immutable,
		Data: map[string][]byte{
			"data": data,
		},
	}

	secretClient := c.Clientset.CoreV1().Secrets(namespace)
	ctx := context.Background()

	_, err = secretClient.Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		if k8sErrors.IsAlreadyExists(err) {
			slog.Info("Generation secret already exists, checking data consistency", "name", genName)
			existing, getErr := secretClient.Get(ctx, genName, metaV1.GetOptions{})
			if getErr != nil {
				return fmt.Errorf("failed to read existing generation secret %s: %w", genName, getErr)
			}
			existingData, ok := existing.Data["data"]
			if !ok {
				return fmt.Errorf("existing generation secret %s has no 'data' field", genName)
			}
			if bytes.Equal(existingData, data) {
				slog.Info("Existing generation secret has identical data, treating as success", "name", genName)
				c.CurrentKeySecret = genName
				return nil
			}
			return fmt.Errorf("generation secret %s already exists with different data: corruption or conflict", genName)
		}
		return fmt.Errorf("failed to create generation secret %s: %w", genName, err)
	}

	c.CurrentKeySecret = genName
	slog.Info("Generation secret stored successfully", "name", genName)
	return nil
}

// LoadGenerationSecret reads the current generation secret from Kubernetes,
// deserializes and validates it, then caches it in memory via SetLoadedGenerationSecret.
// The secret to read is determined by secretName.
//
// Returns descriptive errors for:
//   - CurrentKeySecret is empty
//   - Secret not found in Kubernetes
//   - No "data" field in the secret
//   - Malformed JSON in the "data" field
//   - Validation failure (wrong key count, empty root token)
func (c *MonitorConfig) LoadGenerationSecret(secretName string) (*GenerationSecret, error) {
	if secretName == "" {
		return nil, fmt.Errorf("generation secret name is empty")
	}
	if c.Clientset == nil {
		return nil, fmt.Errorf("clientset is nil: K8s client not initialized")
	}

	namespace := c.Namespace
	if namespace == "" {
		namespace = k8sNamespace
	}

	slog.Debug("Loading generation secret", "namespace", namespace, "name", secretName)

	secretClient := c.Clientset.CoreV1().Secrets(namespace)
	ctx := context.Background()

	k8sSecret, err := secretClient.Get(ctx, secretName, metaV1.GetOptions{})
	if err != nil {
		if k8sErrors.IsNotFound(err) {
			return nil, fmt.Errorf("generation secret %q not found in namespace %q", secretName, namespace)
		}
		return nil, fmt.Errorf("failed to read generation secret %q: %w", secretName, err)
	}

	// Extract the "data" field from the k8s secret
	rawData, ok := k8sSecret.Data["data"]
	if !ok {
		return nil, fmt.Errorf("generation secret %q has no 'data' field", secretName)
	}

	// Deserialize JSON into GenerationSecret
	var genSecret GenerationSecret
	if err := json.Unmarshal(rawData, &genSecret); err != nil {
		return nil, fmt.Errorf("failed to unmarshal generation secret %q: %w", secretName, err)
	}

	// Validate the loaded secret
	if err := ValidateGenerationSecret(&genSecret); err != nil {
		return nil, fmt.Errorf("generation secret %q failed validation: %w", secretName, err)
	}

	// Cache the loaded secret in memory
	c.SetLoadedGenerationSecret(&genSecret)

	slog.Info("Generation secret loaded successfully", "name", secretName)
	return &genSecret, nil
}
