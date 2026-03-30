package com.plantops.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.plantops.backend.config.LegacyBackendProperties;
import com.plantops.backend.model.DomainTypes;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Service;

@Service
public class LegacyBackendClient {

    private final LegacyBackendProcessManager processManager;
    private final LegacyBackendProperties properties;
    private final ObjectMapper objectMapper;

    public LegacyBackendClient(
        LegacyBackendProcessManager processManager,
        LegacyBackendProperties properties,
        ObjectMapper objectMapper
    ) {
        this.processManager = processManager;
        this.properties = properties;
        this.objectMapper = objectMapper;
    }

    public DomainTypes.LegacyHealthSnapshot fetchHealthSnapshot(String token) {
        try {
            if (properties.isAutoStart()) {
                processManager.ensureBackendReady();
            }
        } catch (RuntimeException exception) {
            return unavailable(exception.getMessage());
        }

        try {
            URL url = processManager.buildTargetUri("/health").toURL();
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(properties.getConnectTimeoutSeconds() * 1000);
            connection.setReadTimeout(properties.getReadTimeoutSeconds() * 1000);
            connection.setInstanceFollowRedirects(false);
            if (token != null && !token.isBlank()) {
                connection.setRequestProperty("X-Auth-Token", token);
            }

            int statusCode = connection.getResponseCode();
            String payload = new String(
                (statusCode >= 400 ? connection.getErrorStream() : connection.getInputStream()).readAllBytes(),
                StandardCharsets.UTF_8
            );
            connection.disconnect();

            if (statusCode < 200 || statusCode >= 300) {
                return unavailable("Legacy backend responded with status " + statusCode);
            }

            JsonNode root = objectMapper.readTree(payload);
            JsonNode data = root.path("data");
            return new DomainTypes.LegacyHealthSnapshot(
                true,
                textValue(data, "status", "正常"),
                data.path("model_loaded").asBoolean(false),
                nullableTextValue(data, "model_error"),
                nullableTextValue(data, "current_model"),
                readStringList(data.path("available_models"))
            );
        } catch (IOException exception) {
            return unavailable("Legacy backend unavailable: " + exception.getMessage());
        }
    }

    private DomainTypes.LegacyHealthSnapshot unavailable(String reason) {
        return new DomainTypes.LegacyHealthSnapshot(false, "异常", false, reason, null, List.of());
    }

    private String textValue(JsonNode node, String fieldName, String fallback) {
        JsonNode field = node.path(fieldName);
        if (field.isMissingNode() || field.isNull()) {
            return fallback;
        }
        String value = field.asText("").trim();
        return value.isEmpty() ? fallback : value;
    }

    private String nullableTextValue(JsonNode node, String fieldName) {
        JsonNode field = node.path(fieldName);
        if (field.isMissingNode() || field.isNull()) {
            return null;
        }
        String value = field.asText("").trim();
        return value.isEmpty() ? null : value;
    }

    private List<String> readStringList(JsonNode node) {
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
}