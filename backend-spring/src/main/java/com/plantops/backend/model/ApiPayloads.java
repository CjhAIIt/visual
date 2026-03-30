package com.plantops.backend.model;

import jakarta.validation.constraints.NotBlank;
import java.util.List;

public final class ApiPayloads {

    private ApiPayloads() {
    }

    public record ApiResponse<T>(boolean success, String message, T data) {
    }

    public record UserProfile(
        int id,
        String username,
        String displayName,
        String role,
        int datasetCount,
        int modelCount,
        boolean isDisabled,
        boolean isFlagged
    ) {
    }

    public record AuthSessionData(String token, UserProfile user) {
    }

    public record UsersData(UserProfile currentUser, List<UserProfile> users) {
    }

    public record HealthData(
        String status,
        boolean modelLoaded,
        String modelError,
        String currentModel,
        List<String> availableModels
    ) {
    }

    public record ModelAccessItem(
        String name,
        boolean isActive,
        boolean isPublic,
        boolean isOfficial,
        boolean canManage,
        String ownerUsername,
        String ownerDisplayName
    ) {
    }

    public record ModelsData(
        String currentModel,
        List<String> availableModels,
        List<ModelAccessItem> availableModelItems
    ) {
    }

    public record ManagedModelItem(
        String name,
        long sizeBytes,
        String uploadedAt,
        boolean hasLabels,
        boolean hasMetadata,
        boolean isActive,
        boolean isPublic,
        boolean isOfficial,
        boolean canManage,
        String ownerUsername,
        String ownerDisplayName
    ) {
    }

    public record ManagedDatasetItem(
        String name,
        String uploadedAt,
        boolean isPublic,
        boolean isOfficial,
        boolean canManage,
        String ownerUsername,
        String ownerDisplayName
    ) {
    }

    public record ManagedAugmentationItem(
        String name,
        long sizeBytes,
        String uploadedAt,
        boolean isActive,
        boolean isBuiltin,
        String displayName,
        String version,
        String description,
        List<String> datasetTypes,
        String author
    ) {
    }

    public record AdminConsoleData(
        UserProfile currentUser,
        String currentModel,
        List<String> availableModels,
        List<ManagedModelItem> managedModels,
        List<ManagedDatasetItem> managedDatasets,
        String builtinAugmentationScript,
        String activeAugmentationScript,
        ManagedAugmentationItem builtinAugmentationItem,
        List<ManagedAugmentationItem> managedAugmentationScripts
    ) {
    }

    public record AuthLoginRequest(@NotBlank String username, @NotBlank String password) {
    }

    public record AuthRegisterRequest(@NotBlank String username, @NotBlank String password, String displayName) {
    }

    public record ToggleValueRequest(boolean value) {
    }
}