package com.plantops.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.plantops.backend.config.PlantStorageProperties;
import com.plantops.backend.model.ApiPayloads;
import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.web.PlantApiException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

@Service
public class CatalogService {

    private static final Pattern RELEASE_BEST_PATTERN = Pattern.compile("best(?:\\(\\d+\\))?\\.onnx", Pattern.CASE_INSENSITIVE);
    private static final Pattern DOUBLE_DOCSTRING_PATTERN = Pattern.compile(
        "(?s)^\\s*(?:#.*\\R\\s*)*(?:[rRuUbBfF]{0,2})?\"\"\"(.*?)\"\"\""
    );
    private static final Pattern SINGLE_DOCSTRING_PATTERN = Pattern.compile(
        "(?s)^\\s*(?:#.*\\R\\s*)*(?:[rRuUbBfF]{0,2})?'''(.*?)'''"
    );

    private final PlantStorageProperties properties;
    private final AuthStorageService authStorageService;
    private final LegacyBackendClient legacyBackendClient;
    private final ObjectMapper objectMapper;

    public CatalogService(
        PlantStorageProperties properties,
        AuthStorageService authStorageService,
        LegacyBackendClient legacyBackendClient,
        ObjectMapper objectMapper
    ) {
        this.properties = properties;
        this.authStorageService = authStorageService;
        this.legacyBackendClient = legacyBackendClient;
        this.objectMapper = objectMapper;
    }

    public ApiPayloads.UserProfile buildUserProfile(DomainTypes.AppUser user) {
        if (user == null) {
            return null;
        }
        int datasetCount = authStorageService.countDatasetsForUser(user);
        int modelCount = authStorageService.countModelsForUser(user);
        return new ApiPayloads.UserProfile(
            user.id(),
            user.username(),
            user.displayName(),
            user.role(),
            datasetCount,
            modelCount,
            user.disabled(),
            user.flagged()
        );
    }

    public ApiPayloads.ApiResponse<ApiPayloads.UsersData> buildUsersResponse(DomainTypes.AppUser currentUser, String message) {
        List<ApiPayloads.UserProfile> users = authStorageService.listUsers().stream().map(this::buildStoredUserProfile).toList();
        return new ApiPayloads.ApiResponse<>(
            true,
            message,
            new ApiPayloads.UsersData(buildUserProfile(currentUser), users)
        );
    }

    public ApiPayloads.ApiResponse<ApiPayloads.HealthData> buildHealthResponse(DomainTypes.AppUser currentUser, String token) {
        syncModelRegistry();
        DomainTypes.LegacyHealthSnapshot legacy = legacyBackendClient.fetchHealthSnapshot(token);
        List<String> releaseVisibleModels = listReleaseVisibleModelNames(listAvailableModelFiles());
        List<String> availableModels = currentUser == null ? releaseVisibleModels : listAccessibleModelNames(currentUser);
        String currentModel = preferredModelFor(availableModels, legacy);
        boolean modelLoaded = currentModel != null && Objects.equals(currentModel, legacy.currentModel()) && legacy.modelLoaded();
        String modelError = currentUser == null ? legacy.modelError() : resolveUserModelError(currentUser, availableModels, currentModel, legacy);
        return new ApiPayloads.ApiResponse<>(
            true,
            "服务可用",
            new ApiPayloads.HealthData(
                legacy.reachable() ? legacy.status() : "异常",
                modelLoaded,
                modelError,
                currentModel,
                availableModels
            )
        );
    }

    public ApiPayloads.ApiResponse<ApiPayloads.ModelsData> buildModelsResponse(
        DomainTypes.AppUser currentUser,
        String message,
        String token
    ) {
        List<String> accessibleModels = listAccessibleModelNames(currentUser);
        DomainTypes.LegacyHealthSnapshot legacy = legacyBackendClient.fetchHealthSnapshot(token);
        String currentModel = preferredModelFor(accessibleModels, legacy);
        List<ApiPayloads.ModelAccessItem> items = accessibleModels.stream()
            .map(modelName -> buildModelAccessItem(modelName, currentUser, currentModel))
            .toList();
        return new ApiPayloads.ApiResponse<>(
            true,
            message,
            new ApiPayloads.ModelsData(currentModel, accessibleModels, items)
        );
    }

    public ApiPayloads.ApiResponse<ApiPayloads.AdminConsoleData> buildAdminConsoleResponse(
        DomainTypes.AppUser currentUser,
        String message,
        String token
    ) {
        syncAnnotationDatasetRegistry();
        syncModelRegistry();
        DomainTypes.LegacyHealthSnapshot legacy = legacyBackendClient.fetchHealthSnapshot(token);
        List<String> availableModels = listReleaseVisibleModelNames(listAvailableModelFiles());
        String currentModel = preferredModelFor(availableModels, legacy);
        Map<String, DomainTypes.ModelOwnership> modelOwnershipByName = new HashMap<>();
        for (DomainTypes.ModelOwnership item : authStorageService.listAllModels()) {
            modelOwnershipByName.put(item.modelName(), item);
        }

        List<ApiPayloads.ManagedModelItem> managedModels = new ArrayList<>();
        for (String modelName : availableModels) {
            ApiPayloads.ManagedModelItem item = buildManagedModelItem(modelName, currentModel, modelOwnershipByName.get(modelName), currentUser);
            if (item != null) {
                managedModels.add(item);
            }
        }

        List<ApiPayloads.ManagedDatasetItem> managedDatasets = authStorageService.listAllDatasets().stream()
            .map(item -> buildManagedDatasetItem(item, currentUser))
            .toList();

        Path builtinAugmentationPath = properties.resolveAugmentScriptPath();
        Path activeAugmentationPath = resolveActiveAugmentationScriptPath();
        ApiPayloads.ManagedAugmentationItem builtinItem = buildBuiltinAugmentationItem(builtinAugmentationPath, activeAugmentationPath);
        List<ApiPayloads.ManagedAugmentationItem> augmentationItems = listManagedAugmentationPaths().stream()
            .map(path -> buildManagedAugmentationItem(path, activeAugmentationPath))
            .toList();

        return new ApiPayloads.ApiResponse<>(
            true,
            message,
            new ApiPayloads.AdminConsoleData(
                buildUserProfile(currentUser),
                currentModel,
                availableModels,
                managedModels,
                managedDatasets,
                builtinAugmentationPath.getFileName() != null ? builtinAugmentationPath.getFileName().toString() : builtinAugmentationPath.toString(),
                activeAugmentationPath != null && activeAugmentationPath.getFileName() != null ? activeAugmentationPath.getFileName().toString() : null,
                builtinItem,
                augmentationItems
            )
        );
    }

    public List<String> listAccessibleModelNames(DomainTypes.AppUser currentUser) {
        syncModelRegistry();
        List<String> availableModels = listReleaseVisibleModelNames(listAvailableModelFiles());
        if (isAdmin(currentUser)) {
            return availableModels;
        }
        Set<String> accessible = new HashSet<>(authStorageService.listAccessibleModelNamesForUser(currentUser.id()));
        return availableModels.stream().filter(accessible::contains).toList();
    }

    public String ensureModelAccess(String modelName, DomainTypes.AppUser currentUser) {
        String normalizedName = normalizeFileName(modelName);
        if (normalizedName.isBlank()) {
            throw new PlantApiException(HttpStatus.NOT_FOUND, "模型不存在");
        }
        List<String> availableModels = listAvailableModelFiles();
        if (!availableModels.contains(normalizedName)) {
            throw new PlantApiException(HttpStatus.NOT_FOUND, "模型不存在：" + normalizedName);
        }
        DomainTypes.ModelOwnership owner = authStorageService.getModelOwner(normalizedName);
        if (!canReadModel(owner, currentUser)) {
            throw new PlantApiException(HttpStatus.FORBIDDEN, "你没有权限访问模型：" + normalizedName);
        }
        return normalizedName;
    }

    public List<ArchiveMember> resolveModelArchiveMembers(String modelName, DomainTypes.AppUser currentUser) {
        String normalizedName = ensureModelAccess(modelName, currentUser);
        Path modelPath = properties.resolveModelsDirectory().resolve(normalizedName);
        if (!Files.exists(modelPath)) {
            throw new PlantApiException(HttpStatus.NOT_FOUND, "模型文件不存在：" + normalizedName);
        }
        String modelStem = stemOf(normalizedName);
        List<ArchiveMember> members = new ArrayList<>();
        members.add(new ArchiveMember(modelPath, modelStem + "/" + modelPath.getFileName()));
        Path labelsPath = replaceModelSidecar(modelPath, ".labels.json");
        Path metadataPath = replaceModelSidecar(modelPath, ".meta.json");
        if (Files.exists(labelsPath)) {
            members.add(new ArchiveMember(labelsPath, modelStem + "/" + labelsPath.getFileName()));
        }
        if (Files.exists(metadataPath)) {
            members.add(new ArchiveMember(metadataPath, modelStem + "/" + metadataPath.getFileName()));
        }
        return members;
    }

    public String buildModelArchiveDownloadName(String modelName) {
        return stemOf(normalizeFileName(modelName)) + "_model.zip";
    }
    private ApiPayloads.UserProfile buildStoredUserProfile(DomainTypes.AppUser user) {
        return new ApiPayloads.UserProfile(
            user.id(),
            user.username(),
            user.displayName(),
            user.role(),
            user.datasetCount(),
            user.modelCount(),
            user.disabled(),
            user.flagged()
        );
    }

    public void syncAnnotationDatasetRegistry() {
        Path root = properties.resolveAnnotationDatasetsRoot();
        try {
            Files.createDirectories(root);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to initialize annotation dataset root", exception);
        }
        DomainTypes.AppUser adminUser = authStorageService.getPrimaryAdminUser();
        if (adminUser == null) {
            return;
        }
        try (Stream<Path> stream = Files.list(root)) {
            stream.filter(Files::isDirectory).forEach(path ->
                authStorageService.ensureDatasetAccessEntry(path.getFileName().toString(), adminUser.id(), false, false)
            );
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to scan annotation dataset root", exception);
        }
    }

    public void syncModelRegistry() {
        Path modelsDirectory = properties.resolveModelsDirectory();
        try {
            Files.createDirectories(modelsDirectory);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to initialize models directory", exception);
        }
        DomainTypes.AppUser adminUser = authStorageService.getPrimaryAdminUser();
        if (adminUser == null) {
            return;
        }
        for (String modelName : listAvailableModelFiles()) {
            authStorageService.ensureModelOwner(modelName, adminUser.id(), true, false);
        }
    }

    public List<String> listReleaseVisibleModelNames(List<String> modelNames) {
        List<String> normalizedNames = modelNames.stream().filter(name -> !name.isBlank()).distinct().sorted().toList();
        List<String> prioritized = new ArrayList<>();
        if (normalizedNames.contains("best.onnx")) {
            prioritized.add("best.onnx");
        }
        for (String modelName : normalizedNames) {
            if (!"best.onnx".equals(modelName) && RELEASE_BEST_PATTERN.matcher(modelName).matches()) {
                prioritized.add(modelName);
            }
        }
        if (!prioritized.isEmpty()) {
            return prioritized.stream().distinct().limit(2).toList();
        }
        return normalizedNames.stream().limit(2).toList();
    }

    private String preferredModelFor(List<String> accessibleModels, DomainTypes.LegacyHealthSnapshot legacy) {
        if (accessibleModels.isEmpty()) {
            return null;
        }
        if (legacy.currentModel() != null && accessibleModels.contains(legacy.currentModel())) {
            return legacy.currentModel();
        }
        return accessibleModels.getFirst();
    }

    private String resolveUserModelError(
        DomainTypes.AppUser currentUser,
        List<String> accessibleModels,
        String currentModel,
        DomainTypes.LegacyHealthSnapshot legacy
    ) {
        if (accessibleModels.isEmpty()) {
            return "当前没有你可访问的模型，请联系管理员上传公开模型或使用你自己的模型";
        }
        if (!legacy.reachable()) {
            return legacy.modelError();
        }
        if (currentModel != null && Objects.equals(currentModel, legacy.currentModel())) {
            return legacy.modelError();
        }
        return null;
    }

    private ApiPayloads.ModelAccessItem buildModelAccessItem(
        String modelName,
        DomainTypes.AppUser currentUser,
        String currentModel
    ) {
        DomainTypes.ModelOwnership owner = authStorageService.getModelOwner(modelName);
        return new ApiPayloads.ModelAccessItem(
            modelName,
            Objects.equals(currentModel, modelName),
            owner != null && owner.isPublic(),
            owner != null && "admin".equals(owner.ownerRole()),
            canManageModel(owner, currentUser),
            owner == null ? null : owner.ownerUsername(),
            owner == null ? null : owner.ownerDisplayName()
        );
    }

    private ApiPayloads.ManagedModelItem buildManagedModelItem(
        String modelName,
        String currentModel,
        DomainTypes.ModelOwnership owner,
        DomainTypes.AppUser currentUser
    ) {
        Path modelPath = properties.resolveModelsDirectory().resolve(modelName);
        if (!Files.exists(modelPath)) {
            return null;
        }
        return new ApiPayloads.ManagedModelItem(
            modelName,
            fileSize(modelPath),
            formatFileTimestamp(modelPath),
            Files.exists(replaceModelSidecar(modelPath, ".labels.json")),
            Files.exists(replaceModelSidecar(modelPath, ".meta.json")),
            Objects.equals(currentModel, modelName),
            owner != null && owner.isPublic(),
            owner != null && "admin".equals(owner.ownerRole()),
            canManageModel(owner, currentUser),
            owner == null ? null : owner.ownerUsername(),
            owner == null ? null : owner.ownerDisplayName()
        );
    }

    private ApiPayloads.ManagedDatasetItem buildManagedDatasetItem(
        DomainTypes.DatasetOwnership item,
        DomainTypes.AppUser currentUser
    ) {
        return new ApiPayloads.ManagedDatasetItem(
            item.datasetName(),
            item.createdAt(),
            item.isPublic(),
            "admin".equals(item.ownerRole()),
            canManageDataset(item, currentUser),
            item.ownerUsername(),
            item.ownerDisplayName()
        );
    }

    private Path resolveActiveAugmentationScriptPath() {
        Path recordPath = properties.resolveActiveAugmentationScriptRecord();
        if (Files.exists(recordPath)) {
            try {
                String override = Files.readString(recordPath).trim();
                if (!override.isBlank()) {
                    Path candidate = properties.resolveAugmentationAlgorithmsDirectory().resolve(Path.of(override).getFileName().toString());
                    if (Files.exists(candidate)) {
                        return candidate;
                    }
                }
            } catch (IOException ignored) {
            }
        }
        return properties.resolveAugmentScriptPath();
    }

    private List<Path> listManagedAugmentationPaths() {
        Path directory = properties.resolveAugmentationAlgorithmsDirectory();
        try {
            Files.createDirectories(directory);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to initialize augmentation algorithms directory", exception);
        }
        try (Stream<Path> stream = Files.list(directory)) {
            return stream
                .filter(path -> Files.isRegularFile(path) && path.getFileName().toString().toLowerCase().endsWith(".py"))
                .filter(path -> fileSize(path) > 0)
                .sorted(Comparator.comparing(path -> path.getFileName().toString().toLowerCase()))
                .toList();
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to list augmentation scripts", exception);
        }
    }

    private ApiPayloads.ManagedAugmentationItem buildManagedAugmentationItem(Path scriptPath, Path activePath) {
        DomainTypes.ManagedAugmentationMetadata metadata = readAugmentationMetadata(scriptPath);
        return new ApiPayloads.ManagedAugmentationItem(
            scriptPath.getFileName().toString(),
            fileSize(scriptPath),
            formatFileTimestamp(scriptPath),
            activePath != null && sameFileName(activePath, scriptPath),
            false,
            metadata.displayName(),
            metadata.version(),
            metadata.description(),
            metadata.datasetTypes(),
            metadata.author()
        );
    }

    private ApiPayloads.ManagedAugmentationItem buildBuiltinAugmentationItem(Path scriptPath, Path activePath) {
        DomainTypes.ManagedAugmentationMetadata metadata = readAugmentationMetadata(scriptPath);
        List<String> datasetTypes = metadata.datasetTypes().isEmpty()
            ? List.of("通用", "叶片病害", "目标检测")
            : metadata.datasetTypes();
        String description = metadata.description() == null || metadata.description().isBlank()
            ? "默认基础增强链路，适合快速完成通用叶片检测数据集的扩增与划分"
            : metadata.description();
        String displayName = metadata.displayName() == null || metadata.displayName().isBlank()
            ? "内置基础增强"
            : metadata.displayName();
        String author = metadata.author() == null || metadata.author().isBlank() ? "系统内置" : metadata.author();
        String version = metadata.version() == null || metadata.version().isBlank() ? "builtin" : metadata.version();
        return new ApiPayloads.ManagedAugmentationItem(
            scriptPath.getFileName() == null ? scriptPath.toString() : scriptPath.getFileName().toString(),
            Files.exists(scriptPath) ? fileSize(scriptPath) : 0L,
            formatFileTimestamp(scriptPath),
            activePath != null && sameFileName(activePath, scriptPath),
            true,
            displayName,
            version,
            description,
            datasetTypes,
            author
        );
    }
    private DomainTypes.ManagedAugmentationMetadata readAugmentationMetadata(Path scriptPath) {
        Path metadataPath = replaceSidecar(scriptPath, ".meta.json");
        JsonNode metadata = objectMapper.createObjectNode();
        if (Files.exists(metadataPath)) {
            try {
                metadata = objectMapper.readTree(Files.readString(metadataPath));
            } catch (IOException ignored) {
                metadata = objectMapper.createObjectNode();
            }
        }
        String description = textOrNull(metadata, "description");
        if (description == null || description.isBlank()) {
            description = extractDocstring(scriptPath);
        }
        return new DomainTypes.ManagedAugmentationMetadata(
            textOrDefault(metadata, "display_name", stemOf(scriptPath.getFileName().toString())),
            textOrNull(metadata, "version"),
            description,
            readStringArray(metadata.path("dataset_types")),
            textOrNull(metadata, "author")
        );
    }

    private String extractDocstring(Path scriptPath) {
        if (!Files.exists(scriptPath)) {
            return null;
        }
        try {
            String source = Files.readString(scriptPath);
            Matcher doubleMatcher = DOUBLE_DOCSTRING_PATTERN.matcher(source);
            if (doubleMatcher.find()) {
                return normalizeDescription(doubleMatcher.group(1));
            }
            Matcher singleMatcher = SINGLE_DOCSTRING_PATTERN.matcher(source);
            if (singleMatcher.find()) {
                return normalizeDescription(singleMatcher.group(1));
            }
            return null;
        } catch (IOException exception) {
            return null;
        }
    }

    private List<String> listAvailableModelFiles() {
        Path directory = properties.resolveModelsDirectory();
        try {
            Files.createDirectories(directory);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to initialize models directory", exception);
        }
        try (Stream<Path> stream = Files.list(directory)) {
            return stream
                .filter(Files::isRegularFile)
                .filter(path -> path.getFileName().toString().toLowerCase().endsWith(".onnx"))
                .filter(path -> fileSize(path) > 0)
                .map(path -> path.getFileName().toString())
                .sorted()
                .toList();
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to list model files", exception);
        }
    }

    private boolean isAdmin(DomainTypes.AppUser user) {
        return user != null && "admin".equals(user.role());
    }

    private boolean canReadModel(DomainTypes.ModelOwnership owner, DomainTypes.AppUser currentUser) {
        return isAdmin(currentUser) || userOwns(owner, currentUser) || (owner != null && owner.isPublic());
    }

    private boolean canManageModel(DomainTypes.ModelOwnership owner, DomainTypes.AppUser currentUser) {
        return isAdmin(currentUser) || userOwns(owner, currentUser);
    }

    private boolean canManageDataset(DomainTypes.DatasetOwnership owner, DomainTypes.AppUser currentUser) {
        return isAdmin(currentUser) || (owner != null && currentUser != null && owner.ownerUserId() == currentUser.id());
    }

    private boolean userOwns(DomainTypes.ModelOwnership owner, DomainTypes.AppUser currentUser) {
        return owner != null && currentUser != null && owner.ownerUserId() == currentUser.id();
    }

    private String normalizeFileName(String value) {
        if (value == null || value.isBlank()) {
            return "";
        }
        Path path = Path.of(value).getFileName();
        return path == null ? "" : path.toString();
    }

    private long fileSize(Path path) {
        try {
            return Files.exists(path) ? Files.size(path) : 0L;
        } catch (IOException exception) {
            return 0L;
        }
    }

    private String formatFileTimestamp(Path path) {
        if (!Files.exists(path)) {
            return null;
        }
        try {
            return OffsetDateTime.ofInstant(Files.getLastModifiedTime(path).toInstant(), ZoneId.systemDefault())
                .truncatedTo(ChronoUnit.SECONDS)
                .toString();
        } catch (IOException exception) {
            return null;
        }
    }

    private String stemOf(String fileName) {
        int separator = fileName.lastIndexOf('.');
        return separator > 0 ? fileName.substring(0, separator) : fileName;
    }

    private Path replaceModelSidecar(Path modelPath, String sidecarSuffix) {
        return modelPath.resolveSibling(stemOf(modelPath.getFileName().toString()) + sidecarSuffix);
    }

    private Path replaceSidecar(Path path, String sidecarSuffix) {
        return path.resolveSibling(stemOf(path.getFileName().toString()) + sidecarSuffix);
    }

    private boolean sameFileName(Path left, Path right) {
        return left != null && right != null && Objects.equals(left.getFileName(), right.getFileName());
    }

    private String textOrDefault(JsonNode node, String fieldName, String fallback) {
        String value = textOrNull(node, fieldName);
        return value == null || value.isBlank() ? fallback : value;
    }

    private String textOrNull(JsonNode node, String fieldName) {
        JsonNode field = node.path(fieldName);
        if (field.isMissingNode() || field.isNull()) {
            return null;
        }
        String value = field.asText("").trim();
        return value.isEmpty() ? null : value;
    }

    private List<String> readStringArray(JsonNode node) {
        if (!node.isArray()) {
            return List.of();
        }
        List<String> values = new ArrayList<>();
        for (JsonNode item : node) {
            String value = item.asText("").trim();
            if (!value.isEmpty() && !values.contains(value)) {
                values.add(value);
            }
        }
        return values;
    }

    private String normalizeDescription(String rawDescription) {
        if (rawDescription == null) {
            return null;
        }
        String normalized = rawDescription.replaceAll("\\s+", " ").trim();
        return normalized.isEmpty() ? null : normalized;
    }

    public record ArchiveMember(Path sourcePath, String archivePath) {
    }
}