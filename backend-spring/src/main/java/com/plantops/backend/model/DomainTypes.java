package com.plantops.backend.model;

import java.util.List;

public final class DomainTypes {

    private DomainTypes() {
    }

    public record AppUser(
        int id,
        String username,
        String displayName,
        String role,
        boolean disabled,
        boolean flagged,
        String createdAt,
        int datasetCount,
        int modelCount
    ) {
    }

    public record DatasetOwnership(
        String datasetName,
        int ownerUserId,
        boolean isPublic,
        String createdAt,
        String ownerUsername,
        String ownerDisplayName,
        String ownerRole
    ) {
    }

    public record ModelOwnership(
        String modelName,
        int ownerUserId,
        boolean isPublic,
        String createdAt,
        String ownerUsername,
        String ownerDisplayName,
        String ownerRole
    ) {
    }

    public record ClassAdvice(
        String datasetName,
        String className,
        String summary,
        List<String> advice,
        String source,
        String detail,
        Integer generatedByUserId,
        String createdAt,
        String updatedAt
    ) {
    }

    public record ManagedAugmentationMetadata(
        String displayName,
        String version,
        String description,
        List<String> datasetTypes,
        String author
    ) {
    }

    public record LegacyHealthSnapshot(
        boolean reachable,
        String status,
        boolean modelLoaded,
        String modelError,
        String currentModel,
        List<String> availableModels
    ) {
    }
}