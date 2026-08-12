# Commands Test Suite

Unit and integration tests for the `commands` package (run loop, legacy migration, snapshot, integration).

## Tests

### run_test.go
- TestDiscoverCurrentGeneration_EmptyNamespace — empty when no secrets
- TestDiscoverCurrentGeneration_AlreadySet — skips when already configured
- TestDiscoverCurrentGeneration_WithExistingGens — picks latest
- TestUnsealWithGenKeys_NilSecret — error on nil secret
- TestUnsealWithGenKeys_InsufficientKeys — error with fewer than threshold
- TestUnsealWithGenKeys_EmptyKeys — error with empty keys
- TestStartupLegacyMigration_NoLegacySecrets — no-op when none found
- TestStartupLegacyMigration_WithLegacySecrets_Integration — full migration
- TestRunInitAndStore_ValidatesGenSecret — validates before storing
- TestInitConstants — 5 shares, 3 threshold
- TestJoinRaft_NoOtherServers — error when no peers
- TestJoinRaft_MultipleServers — picks leader from available
- TestDriveRekey_WithVerification_Integration — end-to-end rekey with verify

### conversion_test.go
- TestDetectLegacySecrets_AllPresent — finds all 5 shards + root
- TestDetectLegacySecrets_NonePresent — returns false when empty
- TestDetectLegacySecrets_MissingRoot — false when root missing
- TestDetectLegacySecrets_MissingShard — false when shard missing
- TestDetectLegacySecrets_DefaultNamespace — uses "openbao" default
- TestMigrateLegacySecrets_FullMigration — creates gen-001 from legacy
- TestMigrateLegacySecrets_PartialSecrets_Error — error on incomplete
- TestMigrateLegacySecrets_MissingRootToken_Error — error without root
- TestMigrateLegacySecrets_IdempotentRerun — succeeds on re-run
- TestMigrateLegacySecrets_DefaultPrefix — uses cluster-key prefix

### snapshot_test.go
- TestCreateSnapshotMetadata_ValidGeneration — captures gen name + hash
- TestCreateSnapshotMetadata_RekeyInProgress — refuses during rekey
- TestCreateSnapshotMetadata_NoCurrentKeySecret — error when not set
- TestValidateSnapshotMetadata_SecretExists — passes when secret found
- TestValidateSnapshotMetadata_SecretMissing — fails when gone
- TestComputeKeyDataHash — deterministic SHA-256
- TestValidateSnapshotMetadata_NilMetadata — error on nil
- TestValidateSnapshotMetadata_EmptyGenerationName — error on empty

### integration_test.go
- TestIntegration_FreshInstall_StoreGen001Immutable — init creates immutable gen-001
- TestIntegration_LegacyMigration_CreatesGen001 — legacy secrets migrated
- TestIntegration_Rekey_CreatesGen002_RetainsGen001 — rekey preserves old
- TestIntegration_PodRestart_RecoverStateFromK8s — discovers latest gen
- TestIntegration_PodRestart_NoGenerationSecrets_WaitsForInit — waits when empty
- TestIntegration_PodRestart_RekeyInProgress_Detected — drives rekey to completion
- TestIntegration_FiveThreeThreshold_InitConstants — 5/3 params
- TestIntegration_FiveThreeThreshold_GenerationSecretAlways5Keys — validates
- TestIntegration_FiveThreeThreshold_UnsealNeedsThreeKeys — threshold check
- TestIntegration_NoSecretsDeleted_AfterMigration — retention verified
- TestIntegration_NoSecretsDeleted_AfterRekey — retention verified
- TestIntegration_ThinShell_ExecsBaomonRun — run loop invoked
- TestIntegration_ThinShell_NoLegacyFunctionsInRunPath — no bash legacy
- TestIntegration_ImmutableSecrets_RejectUpdate — K8s rejects mutation
- TestIntegration_ImmutableSecrets_IdempotentSameData — idempotent store
- TestIntegration_ImmutableSecrets_AllGenerationsImmutable — all immutable
- TestIntegration_FullLifecycle_EndToEnd — init → unseal → rekey → verify
