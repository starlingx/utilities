package baoConfig

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/pingcap/failpoint"
	v1 "k8s.io/api/core/v1"
	k8sErrors "k8s.io/apimachinery/pkg/api/errors"
	metaV1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/util/validation/field"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
)

// Default values in case the values are not included in the config
var k8sNamespace string = "openbao"
var podPort int = 8200
var podPrefix string = "stx-openbao"
var podAddressSuffix string = "pod.cluster.local"
var secretPrefix string = "cluster-key"

// KeySecret represents the JSON payload stored in a legacy per-shard secret's
// "strdata" field, e.g. {"keys":["hexkey"],"keys_base64":["base64key"]}.
// It is shared by the legacy secret read/write paths and the one-time
// legacy-to-generation migration.
type KeySecret struct {
	Key        []string `json:"keys"`
	KeyEncoded []string `json:"keys_base64"`
}

// Filters errors that can be solved on retry
func IsTransientK8sError(err error) bool {
	if err == nil {
		return false
	}
	if k8sErrors.IsTimeout(err) || k8sErrors.IsServerTimeout(err) ||
		k8sErrors.IsTooManyRequests(err) || k8sErrors.IsServiceUnavailable(err) ||
		k8sErrors.IsInternalError(err) || errors.Is(err, context.DeadlineExceeded) {
		return true
	}

	if strings.Contains(strings.ToLower(err.Error()), "request timed out") {
		return true
	}

	var networkErr net.Error
	if errors.As(err, &networkErr) && (networkErr.Timeout() || networkErr.Temporary()) {
		return true
	}

	return errors.Is(err, syscall.ECONNREFUSED) || errors.Is(err, syscall.ECONNRESET)
}

func getK8sContextWithTimeout(restConfig *rest.Config) (context.Context, context.CancelFunc) {
	timeout := 30 * time.Second // Default

	if restConfig != nil && restConfig.Timeout != 0 {
		timeout = restConfig.Timeout
	}

	return context.WithTimeout(context.Background(), timeout)
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
	ctx, cancel := getK8sContextWithTimeout(config)
	defer cancel()

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
			podURL, err := PodDNSName(podIP, k8sNamespace, podAddressSuffix)
			if err != nil {
				slog.Warn("Skipping pod with unparseable IP", "pod", podName, "ip", podIP, "err", err)
				continue
			}
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
				var newKey KeySecret
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
		var newSecret KeySecret
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
// data field contains the JSON-marshaled GenerationSecret.
func (c *MonitorConfig) StoreGenerationSecret(genName string, secret *GenerationSecret) error {
	if c.Clientset == nil {
		return fmt.Errorf("clientset is nil: K8s client not initialized")
	}
	namespace := c.GetNamespace()

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
	ctx, cancel := getK8sContextWithTimeout(nil)
	defer cancel()

	created, err := secretClient.Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		if k8sErrors.IsAlreadyExists(err) {
			slog.Info("Generation secret already exists, checking data consistency", "name", genName)
			existing, getErr := secretClient.Get(ctx, genName, metaV1.GetOptions{})
			if getErr != nil {
				return getErr
			}
			existingData, ok := existing.Data["data"]
			if !ok {
				return fmt.Errorf("existing generation secret %s has no 'data' field", genName)
			}
			if bytes.Equal(existingData, data) {
				slog.Info("Existing generation secret has identical data, treating as success", "name", genName)
				return nil
			}
			return fmt.Errorf("generation secret %s already exists with different data: corruption or conflict", genName)
		}
		return err
	}

	// Failpoint 2: Rekey: After K8s Secret Created, Before Pointer Update
	// Simulates: crash after creating immutable secret, before updating the pointer
	failpoint.Inject("fp_rekey_after_store_before_pointer", func() {
		slog.Warn("Failpoint triggered: fp_rekey_after_store_before_pointer")
		failpoint.Return(fmt.Errorf("failpoint: rekey after shards before store"))
	})

	slog.Info("Generation secret stored successfully", "name", genName,
		"uid", created.UID, "createdAt", created.CreationTimestamp)
	return nil
}

// LoadGenerationSecret reads the current generation secret from Kubernetes,
// deserializes and validates it. The secret to read is determined by secretName.
func (c *MonitorConfig) LoadGenerationSecret(secretName string) (*GenerationSecret, error) {
	if secretName == "" {
		return nil, fmt.Errorf("generation secret name is empty")
	}
	if c.Clientset == nil {
		return nil, fmt.Errorf("clientset is nil: K8s client not initialized")
	}

	namespace := c.GetNamespace()

	slog.Debug("Loading generation secret", "namespace", namespace, "name", secretName)

	secretClient := c.Clientset.CoreV1().Secrets(namespace)
	ctx, cancel := getK8sContextWithTimeout(nil)
	defer cancel()

	k8sSecret, err := secretClient.Get(ctx, secretName, metaV1.GetOptions{})
	if err != nil {
		return nil, err
	}

	var genSecret GenerationSecret
	if rawData, ok := k8sSecret.Data["data"]; !ok {
		err = fmt.Errorf("no \"data\" field")
	} else if err = json.Unmarshal(rawData, &genSecret); err == nil {
		err = ValidateGenerationSecret(&genSecret)
	}
	if err != nil {
		// Using k8sErrors to notify runIteration that this error should be
		// discarded, and recovery attempted.
		return nil, k8sErrors.NewInvalid(schema.GroupKind{Kind: "secret"}, secretName,
			field.ErrorList{field.Invalid(field.NewPath("data"), nil, err.Error())})
	}

	slog.Info("Generation secret loaded successfully", "name", secretName)
	return &genSecret, nil
}

// currentKeyPointer is the JSON payload of the mutable pointer secret. It holds
// the name of the generation secret that is currently active.
type currentKeyPointer struct {
	Current string `json:"current"`
}

// LoadCurrentKeyPointer reads the mutable pointer secret from Kubernetes and
// returns the name of the generation secret it references.
//
// The pointer secret is the authoritative source of truth for which generation
// is active. If the pointer secret does not exist yet (first boot before init,
// or a system predating the pointer), this returns ("", nil) so callers can
// distinguish "no pointer yet" from a real API error. All other failures
// (API errors, missing/malformed data) return a wrapped error.
func (c *MonitorConfig) LoadCurrentKeyPointer() (string, error) {
	if c.Clientset == nil {
		return "", fmt.Errorf("clientset is nil: K8s client not initialized")
	}

	namespace := c.GetNamespace()

	pointerName := c.GetCurrentKeyPointerName()
	slog.Debug("Loading current key pointer", "namespace", namespace, "name", pointerName)

	secretClient := c.Clientset.CoreV1().Secrets(namespace)
	ctx, cancel := getK8sContextWithTimeout(nil)
	defer cancel()

	k8sSecret, err := secretClient.Get(ctx, pointerName, metaV1.GetOptions{})
	if err != nil {
		if k8sErrors.IsNotFound(err) {
			// Not an error: the pointer has not been created yet.
			slog.Debug("Current key pointer not found", "name", pointerName)
			return "", nil
		}
		return "", fmt.Errorf("failed to read current key pointer %q: %w", pointerName, err)
	}

	rawData, ok := k8sSecret.Data["data"]
	if !ok {
		return "", fmt.Errorf("current key pointer %q has no 'data' field", pointerName)
	}

	var pointer currentKeyPointer
	if err := json.Unmarshal(rawData, &pointer); err != nil {
		return "", fmt.Errorf("failed to unmarshal current key pointer %q: %w", pointerName, err)
	}

	if pointer.Current == "" {
		return "", fmt.Errorf("current key pointer %q references an empty generation name", pointerName)
	}

	slog.Debug("Current key pointer loaded", "name", pointerName, "current", pointer.Current)
	return pointer.Current, nil
}

// StoreCurrentKeyPointer creates or updates the mutable pointer secret so that
// it references genName as the active generation secret. Unlike generation
// secrets, the pointer secret is mutable and is overwritten in place when the
// active generation advances (after init, and after a verified rekey).
func (c *MonitorConfig) StoreCurrentKeyPointer(genName string) error {
	if genName == "" {
		return fmt.Errorf("cannot store current key pointer: generation name is empty")
	}
	if c.Clientset == nil {
		return fmt.Errorf("clientset is nil: K8s client not initialized")
	}

	namespace := c.GetNamespace()

	pointerName := c.GetCurrentKeyPointerName()
	slog.Debug("Storing current key pointer", "namespace", namespace, "name", pointerName, "current", genName)

	data, err := json.Marshal(currentKeyPointer{Current: genName})
	if err != nil {
		return fmt.Errorf("failed to marshal current key pointer: %w", err)
	}

	k8sSecret := &v1.Secret{
		ObjectMeta: metaV1.ObjectMeta{
			Name:      pointerName,
			Namespace: namespace,
			Labels: map[string]string{
				"app":       "openbao",
				"component": "unseal-keys-pointer",
			},
		},
		Data: map[string][]byte{
			"data": data,
		},
	}

	secretClient := c.Clientset.CoreV1().Secrets(namespace)
	ctx, cancel := getK8sContextWithTimeout(nil)
	defer cancel()

	// Upsert: create if absent, update in place if it already exists.
	_, err = secretClient.Create(ctx, k8sSecret, metaV1.CreateOptions{})
	if err != nil {
		if k8sErrors.IsAlreadyExists(err) {
			existing, getErr := secretClient.Get(ctx, pointerName, metaV1.GetOptions{})
			if getErr != nil {
				return getErr
			}
			existing.Data = k8sSecret.Data
			existing.Labels = k8sSecret.Labels
			if _, updErr := secretClient.Update(ctx, existing, metaV1.UpdateOptions{}); updErr != nil {
				return updErr
			}
			slog.Info("Current key pointer updated", "name", pointerName, "current", genName)
			return nil
		}
		return fmt.Errorf("failed to create current key pointer %q: %w", pointerName, err)
	}

	slog.Info("Current key pointer created", "name", pointerName, "current", genName)
	return nil
}
