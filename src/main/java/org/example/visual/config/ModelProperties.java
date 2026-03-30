package org.example.visual.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

@ConfigurationProperties(prefix = "visual.model")
public class ModelProperties {

    private String resourceLocation = "classpath:models/best.onnx";
    private float confidenceThreshold = 0.35f;
    private float nmsThreshold = 0.45f;
    private List<String> labels = new ArrayList<>();

    public String getResourceLocation() {
        return resourceLocation;
    }

    public void setResourceLocation(String resourceLocation) {
        this.resourceLocation = resourceLocation;
    }

    public float getConfidenceThreshold() {
        return confidenceThreshold;
    }

    public void setConfidenceThreshold(float confidenceThreshold) {
        this.confidenceThreshold = confidenceThreshold;
    }

    public float getNmsThreshold() {
        return nmsThreshold;
    }

    public void setNmsThreshold(float nmsThreshold) {
        this.nmsThreshold = nmsThreshold;
    }

    public List<String> getLabels() {
        return labels;
    }

    public void setLabels(List<String> labels) {
        this.labels = labels;
    }
}
