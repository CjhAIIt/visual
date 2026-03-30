package com.plantops.backend.web;

import com.plantops.backend.legacy.LegacyCapabilityRegistry;
import com.plantops.backend.service.LegacyProxyService;
import com.plantops.backend.service.LegacyProxyService.LegacyProxyResponse;
import jakarta.servlet.http.HttpServletRequest;
import java.io.InputStream;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
public class LegacyProxyController {

    private final LegacyProxyService proxyService;
    private final LegacyCapabilityRegistry capabilityRegistry;

    public LegacyProxyController(LegacyProxyService proxyService, LegacyCapabilityRegistry capabilityRegistry) {
        this.proxyService = proxyService;
        this.capabilityRegistry = capabilityRegistry;
    }

    @RequestMapping(
        path = {"/**"},
        method = {
            RequestMethod.GET,
            RequestMethod.POST,
            RequestMethod.PUT,
            RequestMethod.PATCH,
            RequestMethod.DELETE,
            RequestMethod.OPTIONS,
            RequestMethod.HEAD
        }
    )
    public ResponseEntity<StreamingResponseBody> proxy(HttpServletRequest request) {
        if (!capabilityRegistry.isLegacyPath(request.getRequestURI())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "No Spring or legacy route matched the request path");
        }

        LegacyProxyResponse proxied = proxyService.forward(request);
        StreamingResponseBody body = outputStream -> {
            try (LegacyProxyResponse ignored = proxied; InputStream inputStream = proxied.getBodyStream()) {
                if (!"HEAD".equalsIgnoreCase(request.getMethod()) && inputStream != null) {
                    inputStream.transferTo(outputStream);
                }
            }
        };

        return ResponseEntity
            .status(proxied.getStatusCode())
            .headers(proxied.getHeaders())
            .body(body);
    }
}