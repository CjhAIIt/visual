package com.plantops.backend.service;

import com.plantops.backend.config.LegacyBackendProperties;
import jakarta.annotation.PreDestroy;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

@Component
public class LegacyBackendProcessManager {

    private static final Logger logger = LoggerFactory.getLogger(LegacyBackendProcessManager.class);

    private final LegacyBackendProperties properties;

    private volatile Process legacyProcess;
    private volatile Thread logPumpThread;

    public LegacyBackendProcessManager(LegacyBackendProperties properties) {
        this.properties = properties;
    }

    public synchronized void ensureBackendReady() {
        if (isLegacyBackendReachable()) {
            return;
        }

        if (!properties.isAutoStart()) {
            return;
        }

        if (legacyProcess != null && legacyProcess.isAlive()) {
            waitForHealth(Duration.ofSeconds(Math.max(5, properties.getStartTimeoutSeconds())));
            return;
        }

        startLegacyBackend();
    }

    public synchronized void startLegacyBackend() {
        if (legacyProcess != null && legacyProcess.isAlive()) {
            return;
        }

        Path workingDirectory = resolveWorkingDirectory();
        List<String> pythonCommand = resolvePythonCommand(workingDirectory);
        List<String> command = new ArrayList<>(pythonCommand);
        command.add("-m");
        command.add("uvicorn");
        command.add("asgi:app");
        command.add("--host");
        command.add(properties.getHost());
        command.add("--port");
        command.add(String.valueOf(properties.getPort()));

        ProcessBuilder processBuilder = new ProcessBuilder(command);
        processBuilder.directory(workingDirectory.toFile());
        processBuilder.redirectErrorStream(true);
        processBuilder.environment().putIfAbsent("PYTHONIOENCODING", "utf-8");

        try {
            logger.info("Starting legacy Python backend in {} via {}", workingDirectory, String.join(" ", command));
            legacyProcess = processBuilder.start();
            pumpLogs(legacyProcess);
            waitForHealth(Duration.ofSeconds(Math.max(5, properties.getStartTimeoutSeconds())));
        } catch (IOException exception) {
            legacyProcess = null;
            throw new IllegalStateException("Failed to start legacy Python backend", exception);
        }
    }

    public boolean isLegacyBackendReachable() {
        try {
            URL url = buildTargetUri("/health").toURL();
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod("GET");
            connection.setConnectTimeout(properties.getConnectTimeoutSeconds() * 1000);
            connection.setReadTimeout(properties.getConnectTimeoutSeconds() * 1000);
            connection.setInstanceFollowRedirects(false);
            int status = connection.getResponseCode();
            connection.disconnect();
            return status >= 200 && status < 500;
        } catch (IOException exception) {
            return false;
        }
    }

    public URI buildTargetUri(String requestPathWithQuery) {
        String normalizedBase = properties.getBaseUrl().replaceAll("/+$", "");
        String normalizedPath = StringUtils.hasText(requestPathWithQuery) ? requestPathWithQuery : "/";
        return URI.create(normalizedBase + normalizedPath);
    }

    private void waitForHealth(Duration timeout) {
        Instant deadline = Instant.now().plus(timeout);
        while (Instant.now().isBefore(deadline)) {
            if (isLegacyBackendReachable()) {
                return;
            }

            if (legacyProcess != null && !legacyProcess.isAlive()) {
                throw new IllegalStateException("Legacy Python backend exited before becoming ready");
            }

            try {
                Thread.sleep(500L);
            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Interrupted while waiting for legacy backend startup", exception);
            }
        }

        throw new IllegalStateException("Legacy Python backend did not become ready before timeout");
    }

    private Path resolveWorkingDirectory() {
        Path configured = Paths.get(properties.getWorkingDirectory());
        Path resolved = configured.isAbsolute()
            ? configured.normalize()
            : Paths.get("").toAbsolutePath().resolve(configured).normalize();
        if (!Files.isDirectory(resolved)) {
            throw new IllegalStateException("Legacy backend working directory does not exist: " + resolved);
        }
        return resolved;
    }

    private List<String> resolvePythonCommand(Path workingDirectory) {
        if (StringUtils.hasText(properties.getPythonPath())) {
            return List.of(properties.getPythonPath().trim());
        }

        List<List<String>> candidates = new ArrayList<>();
        Path projectRoot = workingDirectory.getParent();
        boolean isWindows = System.getProperty("os.name", "").toLowerCase(Locale.ROOT).contains("win");

        if (projectRoot != null) {
            candidates.add(List.of(pythonExecutable(projectRoot.resolve(".venv"), isWindows).toString()));
            candidates.add(List.of(pythonExecutable(projectRoot.resolve(".venv-train"), isWindows).toString()));
        }
        candidates.add(List.of(pythonExecutable(workingDirectory.resolve(".venv"), isWindows).toString()));
        candidates.add(List.of(pythonExecutable(workingDirectory.resolve(".venv-train"), isWindows).toString()));
        candidates.add(List.of("python"));

        for (List<String> candidate : candidates) {
            if (hasUvicorn(candidate, workingDirectory)) {
                return candidate;
            }
        }

        throw new IllegalStateException("Unable to find a Python interpreter with uvicorn for the legacy backend");
    }

    private Path pythonExecutable(Path venvRoot, boolean isWindows) {
        return isWindows ? venvRoot.resolve("Scripts").resolve("python.exe") : venvRoot.resolve("bin").resolve("python");
    }

    private boolean hasUvicorn(List<String> commandPrefix, Path workingDirectory) {
        if (commandPrefix.isEmpty()) {
            return false;
        }

        String executable = commandPrefix.get(0);
        if (!"python".equals(executable)) {
            Path path = Paths.get(executable);
            if (!Files.exists(path)) {
                return false;
            }
        }

        List<String> command = new ArrayList<>(commandPrefix);
        command.add("-c");
        command.add("import uvicorn");
        ProcessBuilder builder = new ProcessBuilder(command);
        builder.directory(workingDirectory.toFile());
        builder.redirectErrorStream(true);
        try {
            Process process = builder.start();
            boolean finished = process.waitFor(12, java.util.concurrent.TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                return false;
            }
            return process.exitValue() == 0;
        } catch (IOException | InterruptedException exception) {
            if (exception instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            return false;
        }
    }

    private void pumpLogs(Process process) {
        Thread existing = logPumpThread;
        if (existing != null && existing.isAlive()) {
            return;
        }

        Thread thread = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    logger.info("[legacy-backend] {}", line);
                }
            } catch (IOException exception) {
                logger.debug("Legacy backend log stream closed: {}", exception.getMessage());
            }
        }, "legacy-backend-log-pump");
        thread.setDaemon(true);
        thread.start();
        logPumpThread = thread;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void warmUpLegacyBackend() {
        if (!properties.isAutoStart()) {
            return;
        }
        try {
            ensureBackendReady();
        } catch (RuntimeException exception) {
            logger.warn("Legacy backend warm-up did not complete during Spring startup: {}", exception.getMessage());
        }
    }

    @PreDestroy
    public synchronized void stopLegacyBackend() {
        Process process = legacyProcess;
        legacyProcess = null;
        if (process == null) {
            return;
        }

        logger.info("Stopping legacy Python backend");
        process.destroy();
        try {
            if (!process.waitFor(10, java.util.concurrent.TimeUnit.SECONDS)) {
                process.destroyForcibly();
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            process.destroyForcibly();
        }
    }
}
