package com.plantops.backend.legacy;

import java.util.List;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;

@Component
public class LegacyCapabilityRegistry {

    private static final List<String> LEGACY_PATTERNS = List.of(
        "/predict",
        "/ai/recommendation",
        "/annotation/**",
        "/models/upload",
        "/models/delete",
        "/models/select",
        "/models/train",
        "/models/train/**",
        "/admin/models/upload",
        "/admin/datasets/upload",
        "/admin/augmentations/**",
        "/admin/users/*"
    );

    private final AntPathMatcher pathMatcher = new AntPathMatcher();

    public boolean isLegacyPath(String requestPath) {
        return LEGACY_PATTERNS.stream().anyMatch(pattern -> pathMatcher.match(pattern, requestPath));
    }
}