# Rekey Test Suite

Unit tests for the `rekey` package (state machine, verification, error handling).

## Tests

### rekey_test.go
- TestRekeyHappyPath — full flow: Start → SubmitShards → StoreResult
- TestRekeyHappyPath_WithVerification — full flow including Verify step
- TestRekey_CancelOnSubmitError — cancels server-side on submission failure
- TestRekey_CancelOnLoadError — cancels when generation secret can't load
- TestRekeyCheckInProgress — detects in-progress rekey
- TestRekeyCancel — cancels and resets state to Idle
- TestRekeyCancel_ServerError — handles cancel API failure gracefully
- TestRekeyStart_ServerError — handles init API failure
- TestRekeyStart_NotStarted — handles server not-started response
- TestRekeyStoreResult_NilResponse — error on nil response
- TestRekeyStoreResult_EmptyRootToken — error when root token missing
- TestRekey_ServerSealedMidRekey — handles server going sealed during rekey
- TestRekey_InterruptedResume — detects and drives interrupted rekey
- TestRekeyVerify_HappyPath — verification completes after threshold submissions
- TestRekeyVerify_NilResponse — error on nil response
- TestRekeyVerify_NoVerificationNonce — error when nonce empty
- TestRekeyVerify_InsufficientKeys — error when not enough keys
- TestRekeyVerify_APIError_CancelsVerification — cancels on API failure
- TestRekeyVerify_DoesNotComplete — cancels when verification doesn't complete
- TestStateString — state enum string representation
- TestStateString_Verified — StateVerified string
