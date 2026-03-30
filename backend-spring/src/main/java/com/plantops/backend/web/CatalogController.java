package com.plantops.backend.web;

import com.plantops.backend.model.ApiPayloads;
import com.plantops.backend.model.DomainTypes;
import com.plantops.backend.service.CatalogService;
import com.plantops.backend.service.CatalogService.ArchiveMember;
import com.plantops.backend.service.SessionAuthService;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
public class CatalogController {

    private final SessionAuthService sessionAuthService;
    private final CatalogService catalogService;

    public CatalogController(SessionAuthService sessionAuthService, CatalogService catalogService) {
        this.sessionAuthService = sessionAuthService;
        this.catalogService = catalogService;
    }

    @GetMapping({"/", "/health"})
    public ApiPayloads.ApiResponse<ApiPayloads.HealthData> health(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.resolveOptionalUser(token);
        return catalogService.buildHealthResponse(currentUser, token);
    }

    @GetMapping("/models")
    public ApiPayloads.ApiResponse<ApiPayloads.ModelsData> listModels(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireUser(token);
        return catalogService.buildModelsResponse(currentUser, "模型列表已就绪", token);
    }

    @GetMapping("/admin/console")
    public ApiPayloads.ApiResponse<ApiPayloads.AdminConsoleData> adminConsole(
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireAdmin(token);
        return catalogService.buildAdminConsoleResponse(currentUser, "管理员总控已就绪", token);
    }

    @GetMapping("/models/{modelName}/download")
    public ResponseEntity<StreamingResponseBody> downloadModel(
        @PathVariable String modelName,
        @RequestHeader(value = "X-Auth-Token", required = false) String token
    ) {
        DomainTypes.AppUser currentUser = sessionAuthService.requireUser(token);
        List<ArchiveMember> members = catalogService.resolveModelArchiveMembers(modelName, currentUser);
        String downloadName = catalogService.buildModelArchiveDownloadName(modelName);
        StreamingResponseBody body = outputStream -> {
            try (ZipOutputStream zipOutputStream = new ZipOutputStream(outputStream)) {
                byte[] buffer = new byte[8192];
                for (ArchiveMember member : members) {
                    ZipEntry entry = new ZipEntry(member.archivePath());
                    zipOutputStream.putNextEntry(entry);
                    try (InputStream inputStream = java.nio.file.Files.newInputStream(member.sourcePath())) {
                        int read;
                        while ((read = inputStream.read(buffer)) >= 0) {
                            if (read == 0) {
                                continue;
                            }
                            zipOutputStream.write(buffer, 0, read);
                        }
                    }
                    zipOutputStream.closeEntry();
                }
                zipOutputStream.finish();
            } catch (IOException exception) {
                throw new IllegalStateException("Failed to stream model archive", exception);
            }
        };
        return ResponseEntity.ok()
            .contentType(MediaType.parseMediaType("application/zip"))
            .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + downloadName + "\"")
            .body(body);
    }
}