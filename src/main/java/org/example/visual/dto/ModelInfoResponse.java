package org.example.visual.dto;

import java.util.List;

public record ModelInfoResponse(
        String modelResource,
        String inputName,
        String outputName,
        int inputWidth,
        int inputHeight,
        int classCount,
        List<String> labels,
        boolean generatedLabels,
        float defaultConfidenceThreshold,
        float defaultNmsThreshold
) {
}
