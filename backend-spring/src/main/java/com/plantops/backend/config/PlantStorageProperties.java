package com.plantops.backend.config;

import java.nio.file.Path;
import java.nio.file.Paths;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "plant.storage")
public class PlantStorageProperties {

    private String backendRoot = "../plantbackend";
    private String authDbPath = "../plantbackend/plant_auth.db";
    private String modelsDirectory = "../plantbackend/models";
    private String annotationDatasetsRoot = "../plantbackend/annotation_datasets";
    private String augmentScriptPath = "../plantbackend/augment_yolo.py";
    private String augmentationAlgorithmsDirectory = "../plantbackend/augmentation_algorithms";
    private String activeAugmentationScriptRecord = "../plantbackend/active_augmentation_script.txt";
    private String defaultAnnotationDatasetName = "default";
    private int authSessionHours = 168;
    private long maxUploadBytes = 512L * 1024L * 1024L;

    public String getBackendRoot() {
        return backendRoot;
    }

    public void setBackendRoot(String backendRoot) {
        this.backendRoot = backendRoot;
    }

    public String getAuthDbPath() {
        return authDbPath;
    }

    public void setAuthDbPath(String authDbPath) {
        this.authDbPath = authDbPath;
    }

    public String getModelsDirectory() {
        return modelsDirectory;
    }

    public void setModelsDirectory(String modelsDirectory) {
        this.modelsDirectory = modelsDirectory;
    }

    public String getAnnotationDatasetsRoot() {
        return annotationDatasetsRoot;
    }

    public void setAnnotationDatasetsRoot(String annotationDatasetsRoot) {
        this.annotationDatasetsRoot = annotationDatasetsRoot;
    }

    public String getAugmentScriptPath() {
        return augmentScriptPath;
    }

    public void setAugmentScriptPath(String augmentScriptPath) {
        this.augmentScriptPath = augmentScriptPath;
    }

    public String getAugmentationAlgorithmsDirectory() {
        return augmentationAlgorithmsDirectory;
    }

    public void setAugmentationAlgorithmsDirectory(String augmentationAlgorithmsDirectory) {
        this.augmentationAlgorithmsDirectory = augmentationAlgorithmsDirectory;
    }

    public String getActiveAugmentationScriptRecord() {
        return activeAugmentationScriptRecord;
    }

    public void setActiveAugmentationScriptRecord(String activeAugmentationScriptRecord) {
        this.activeAugmentationScriptRecord = activeAugmentationScriptRecord;
    }

    public String getDefaultAnnotationDatasetName() {
        return defaultAnnotationDatasetName;
    }

    public void setDefaultAnnotationDatasetName(String defaultAnnotationDatasetName) {
        this.defaultAnnotationDatasetName = defaultAnnotationDatasetName;
    }

    public int getAuthSessionHours() {
        return authSessionHours;
    }

    public void setAuthSessionHours(int authSessionHours) {
        this.authSessionHours = authSessionHours;
    }

    public long getMaxUploadBytes() {
        return maxUploadBytes;
    }

    public void setMaxUploadBytes(long maxUploadBytes) {
        this.maxUploadBytes = maxUploadBytes;
    }

    public Path resolveBackendRoot() {
        return resolvePath(backendRoot);
    }

    public Path resolveAuthDbPath() {
        return resolvePath(authDbPath);
    }

    public Path resolveModelsDirectory() {
        return resolvePath(modelsDirectory);
    }

    public Path resolveAnnotationDatasetsRoot() {
        return resolvePath(annotationDatasetsRoot);
    }

    public Path resolveAugmentScriptPath() {
        return resolvePath(augmentScriptPath);
    }

    public Path resolveAugmentationAlgorithmsDirectory() {
        return resolvePath(augmentationAlgorithmsDirectory);
    }

    public Path resolveActiveAugmentationScriptRecord() {
        return resolvePath(activeAugmentationScriptRecord);
    }

    private Path resolvePath(String rawPath) {
        Path path = Paths.get(rawPath == null ? "" : rawPath).normalize();
        if (!path.isAbsolute()) {
            path = Paths.get("").toAbsolutePath().resolve(path).normalize();
        }
        return path;
    }
}