package com.plantops.backend.service;

import com.plantops.backend.config.LegacyBackendProperties;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.Part;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Enumeration;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

@Service
public class LegacyProxyService {

    private static final Set<String> HOP_BY_HOP_HEADERS = Set.of(
        "connection",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length"
    );

    private final LegacyBackendProcessManager processManager;
    private final LegacyBackendProperties properties;

    public LegacyProxyService(
        LegacyBackendProcessManager processManager,
        LegacyBackendProperties properties
    ) {
        this.processManager = processManager;
        this.properties = properties;
    }

    public LegacyProxyResponse forward(HttpServletRequest request) {
        try {
            processManager.ensureBackendReady();
        } catch (IllegalStateException exception) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Legacy backend is not ready: " + exception.getMessage(),
                exception
            );
        }

        URI targetUri = buildTargetUri(request);
        try {
            HttpURLConnection connection = (HttpURLConnection) targetUri.toURL().openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setRequestMethod(request.getMethod());
            connection.setDoInput(true);
            connection.setConnectTimeout(properties.getConnectTimeoutSeconds() * 1000);
            connection.setReadTimeout(properties.getReadTimeoutSeconds() * 1000);
            copyRequestHeaders(request, connection);
            writeRequestBodyIfPresent(request, connection);

            int status = connection.getResponseCode();
            InputStream bodyStream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
            HttpHeaders responseHeaders = extractResponseHeaders(connection);
            return new LegacyProxyResponse(connection, HttpStatusCode.valueOf(status), responseHeaders, bodyStream);
        } catch (IOException exception) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Spring gateway could not reach the legacy backend: " + exception.getMessage(),
                exception
            );
        }
    }

    private URI buildTargetUri(HttpServletRequest request) {
        String path = request.getRequestURI();
        String query = request.getQueryString();
        String pathWithQuery = (path == null || path.isBlank()) ? "/" : path;
        if (query != null && !query.isBlank()) {
            pathWithQuery += "?" + query;
        }
        return processManager.buildTargetUri(pathWithQuery);
    }

    private void copyRequestHeaders(HttpServletRequest request, HttpURLConnection connection) {
        Enumeration<String> headerNames = request.getHeaderNames();
        if (headerNames == null) {
            return;
        }

        while (headerNames.hasMoreElements()) {
            String headerName = headerNames.nextElement();
            if (HOP_BY_HOP_HEADERS.contains(headerName.toLowerCase())) {
                continue;
            }
            Enumeration<String> values = request.getHeaders(headerName);
            while (values.hasMoreElements()) {
                connection.addRequestProperty(headerName, values.nextElement());
            }
        }
    }

    private void writeRequestBodyIfPresent(HttpServletRequest request, HttpURLConnection connection) throws IOException {
        long contentLength = request.getContentLengthLong();
        boolean hasTransferEncoding = request.getHeader("Transfer-Encoding") != null;
        String contentType = request.getContentType();
        String normalizedContentType = contentType == null ? "" : contentType.split(";", 2)[0].trim().toLowerCase();
        boolean isMultipartForm = "multipart/form-data".equals(normalizedContentType);
        boolean hasContentType = contentType != null && !contentType.isBlank();
        boolean shouldAttemptForward =
            contentLength > 0
                || hasTransferEncoding
                || isMultipartForm
                || (
                    hasContentType
                        && (
                            "POST".equalsIgnoreCase(request.getMethod())
                                || "PUT".equalsIgnoreCase(request.getMethod())
                                || "PATCH".equalsIgnoreCase(request.getMethod())
                        )
                );
        if (!shouldAttemptForward) {
            return;
        }

        connection.setDoOutput(true);
        connection.setChunkedStreamingMode(8192);
        if (isMultipartForm) {
            writeMultipartBody(request, connection);
            return;
        }
        try (InputStream inputStream = request.getInputStream();
             OutputStream outputStream = connection.getOutputStream()) {
            inputStream.transferTo(outputStream);
        }
    }

    private void writeMultipartBody(HttpServletRequest request, HttpURLConnection connection) throws IOException {
        String boundary = "----PlantProxyBoundary" + UUID.randomUUID().toString().replace("-", "");
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);

        try (OutputStream outputStream = connection.getOutputStream()) {
            for (Part part : request.getParts()) {
                writeAscii(outputStream, "--" + boundary + "\r\n");
                String submittedFileName = part.getSubmittedFileName();
                String disposition = submittedFileName == null || submittedFileName.isBlank()
                    ? "Content-Disposition: form-data; name=\"" + part.getName() + "\"\r\n"
                    : "Content-Disposition: form-data; name=\"" + part.getName() + "\"; filename=\"" + submittedFileName + "\"\r\n";
                writeAscii(outputStream, disposition);
                if (part.getContentType() != null && !part.getContentType().isBlank()) {
                    writeAscii(outputStream, "Content-Type: " + part.getContentType() + "\r\n");
                }
                writeAscii(outputStream, "\r\n");
                try (InputStream partInputStream = part.getInputStream()) {
                    partInputStream.transferTo(outputStream);
                }
                writeAscii(outputStream, "\r\n");
            }
            writeAscii(outputStream, "--" + boundary + "--\r\n");
        } catch (ServletException exception) {
            throw new IOException("Failed to read multipart request parts", exception);
        }
    }

    private void writeAscii(OutputStream outputStream, String value) throws IOException {
        outputStream.write(value.getBytes(StandardCharsets.UTF_8));
    }

    private HttpHeaders extractResponseHeaders(HttpURLConnection connection) {
        HttpHeaders headers = new HttpHeaders();
        for (Map.Entry<String, List<String>> entry : connection.getHeaderFields().entrySet()) {
            String name = entry.getKey();
            if (name == null || HOP_BY_HOP_HEADERS.contains(name.toLowerCase())) {
                continue;
            }
            headers.put(name, entry.getValue());
        }
        return headers;
    }

    public static final class LegacyProxyResponse implements AutoCloseable {

        private final HttpURLConnection connection;
        private final HttpStatusCode statusCode;
        private final HttpHeaders headers;
        private final InputStream bodyStream;

        public LegacyProxyResponse(
            HttpURLConnection connection,
            HttpStatusCode statusCode,
            HttpHeaders headers,
            InputStream bodyStream
        ) {
            this.connection = connection;
            this.statusCode = statusCode;
            this.headers = headers;
            this.bodyStream = bodyStream;
        }

        public HttpStatusCode getStatusCode() {
            return statusCode;
        }

        public HttpHeaders getHeaders() {
            return headers;
        }

        public InputStream getBodyStream() {
            return bodyStream;
        }

        @Override
        public void close() throws IOException {
            if (bodyStream != null) {
                bodyStream.close();
            }
            connection.disconnect();
        }
    }
}
