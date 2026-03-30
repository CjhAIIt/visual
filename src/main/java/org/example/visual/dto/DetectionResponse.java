package org.example.visual.dto;

import java.util.List;

public record DetectionResponse(
        String fileName,
        int originalWidth,
        int originalHeight,
        int inputWidth,
        int inputHeight,
        float confidenceThreshold,
        float nmsThreshold,
        long preprocessMs,
        long inferenceMs,
        long postprocessMs,
        long totalMs,
        int totalDetections,
        List<DetectionItem> detections
) {
}
