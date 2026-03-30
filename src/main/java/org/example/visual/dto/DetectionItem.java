package org.example.visual.dto;

public record DetectionItem(
        String label,
        int classId,
        double confidence,
        BoundingBox box
) {
}
