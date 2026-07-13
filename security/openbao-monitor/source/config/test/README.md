# Config Test Suite

Unit tests for the `config` package (generation secret storage, K8s operations, config accessors).

## Tests

### config_test.go
- TestYAMLRoundTrip_NewFields — YAML marshal/unmarshal with generation fields
- TestYAMLRoundTrip_EmptyNewFields — backward compatibility with empty fields
- TestGetCurrentRootToken_FromGenerationSecret — token from loaded generation
- TestGetCurrentRootToken_FallbackToLegacy — token from legacy Tokens map
- TestGetCurrentRootToken_NoTokenAvailable — nil when no token exists
- TestGetUnsealKeys_FromGenerationSecret — keys from loaded generation
- TestGetUnsealKeys_FallbackToLegacy — keys from legacy UnsealKeyShards map
- TestGetUnsealKeys_EmptyWhenNoData — nil when no keys
- TestSetLoadedGenerationSecret — set/get/clear lifecycle
- TestGetRootTokenName_DefaultPrefix — cluster-key-root default
- TestGetRootTokenName_CustomPrefix — custom prefix

### generation_test.go
- TestExtractSeqNum — sequence number parsing from generation names
- TestValidateGenerationSecret — key count, base64 count, root token checks
- TestGetGenerationPrefix — default and custom prefix
- TestListGenerationSecrets_EmptyNamespace — empty result
- TestListGenerationSecrets_MultipleSecrets — sorted by sequence
- TestListGenerationSecrets_IgnoresNonMatchingSecrets — label filtering
- TestNextGenerationName_EmptyNamespace — returns gen-001
- TestNextGenerationName_ExistingGen002 — increments to gen-003
- TestNextGenerationName_DefaultPrefix — uses DefaultGenerationPrefix

### init_generation_test.go
- TestParseInitResponseToGeneration — correct field mapping
- TestParseInitResponseToGeneration_Validates — validation is called
- TestParseInitResponseToGeneration_RoundTrip — init → store → load

### k8s_load_test.go
- TestLoadGenerationSecret_NormalLoad — deserialize and validate
- TestLoadGenerationSecret_SecretNotFound — error on missing secret
- TestLoadGenerationSecret_EmptyCurrentKeySecret — error when not configured
- TestLoadGenerationSecret_MalformedJSON — error on bad data
- TestLoadGenerationSecret_WrongKeyCount — validation failure
- TestLoadGenerationSecret_EmptyRootToken — validation failure
- TestLoadGenerationSecret_NoDataField — error on missing field
- TestLoadGenerationSecret_DefaultNamespace — uses "openbao" default

### k8s_store_test.go
- TestStoreGenerationSecret_NormalCreation — creates immutable secret
- TestStoreGenerationSecret_AlreadyExistsSameData — idempotent success
- TestStoreGenerationSecret_AlreadyExistsDifferentData — conflict error
- TestStoreGenerationSecret_DefaultNamespace — uses "openbao" default
- TestStoreGenerationSecret_SeqNumLabel — labels include generation number
