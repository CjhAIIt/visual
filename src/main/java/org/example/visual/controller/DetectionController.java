package org.example.visual.controller;

import ai.onnxruntime.OrtException;
import org.example.visual.dto.DetectionResponse;
import org.example.visual.dto.ModelInfoResponse;
import org.example.visual.service.YoloDetectionService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR;

@RestController
@RequestMapping("/api")
public class DetectionController {

    private final YoloDetectionService detectionService;

    public DetectionController(YoloDetectionService detectionService) {
        this.detectionService = detectionService;
    }

    @GetMapping("/model/info")
    public ModelInfoResponse getModelInfo() {
        return detectionService.getModelInfo();
    }

    @PostMapping(value = "/detect", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public DetectionResponse detect(
            @RequestPart("file") MultipartFile file,
            @RequestParam(name = "confidence", required = false) Float confidence,
            @RequestParam(name = "nms", required = false) Float nms
    ) {
        if (file.isEmpty()) {
            throw new ResponseStatusException(BAD_REQUEST, "请先上传一张图片。");
        }

        try {
            return detectionService.detect(file, confidence, nms);
        } catch (IllegalArgumentException | IOException exception) {
            throw new ResponseStatusException(BAD_REQUEST, exception.getMessage(), exception);
        } catch (OrtException exception) {
            throw new ResponseStatusException(INTERNAL_SERVER_ERROR, "模型推理失败。", exception);
        }
    }
}
