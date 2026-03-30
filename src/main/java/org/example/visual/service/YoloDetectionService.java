package org.example.visual.service;

import ai.onnxruntime.NodeInfo;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OnnxValue;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import ai.onnxruntime.TensorInfo;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.example.visual.config.ModelProperties;
import org.example.visual.dto.BoundingBox;
import org.example.visual.dto.DetectionItem;
import org.example.visual.dto.DetectionResponse;
import org.example.visual.dto.ModelInfoResponse;
import org.springframework.core.io.Resource;
import org.springframework.core.io.ResourceLoader;
import org.springframework.stereotype.Service;
import org.springframework.util.FileCopyUtils;
import org.springframework.web.multipart.MultipartFile;

import javax.imageio.ImageIO;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.FloatBuffer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Service
public class YoloDetectionService {

    private static final Color LETTERBOX_COLOR = new Color(114, 114, 114);

    private final ResourceLoader resourceLoader;
    private final ModelProperties modelProperties;

    private OrtEnvironment environment;
    private OrtSession session;
    private String inputName;
    private String outputName;
    private int inputWidth;
    private int inputHeight;
    private int classCount;
    private List<String> labels;
    private boolean generatedLabels;

    public YoloDetectionService(ResourceLoader resourceLoader, ModelProperties modelProperties) {
        this.resourceLoader = resourceLoader;
        this.modelProperties = modelProperties;
    }

    @PostConstruct
    public void initialize() throws IOException, OrtException {
        Resource resource = resourceLoader.getResource(modelProperties.getResourceLocation());
        if (!resource.exists()) {
            throw new IllegalStateException("模型文件不存在: " + modelProperties.getResourceLocation());
        }

        byte[] modelBytes;
        try (var inputStream = resource.getInputStream()) {
            modelBytes = FileCopyUtils.copyToByteArray(inputStream);
        }
        environment = OrtEnvironment.getEnvironment();
        try (OrtSession.SessionOptions sessionOptions = new OrtSession.SessionOptions()) {
            session = environment.createSession(modelBytes, sessionOptions);
        }

        Map.Entry<String, NodeInfo> inputEntry = session.getInputInfo().entrySet().iterator().next();
        inputName = inputEntry.getKey();
        TensorInfo inputTensorInfo = (TensorInfo) inputEntry.getValue().getInfo();
        long[] inputShape = inputTensorInfo.getShape();
        inputHeight = dimensionAt(inputShape, 2, 640);
        inputWidth = dimensionAt(inputShape, 3, 640);

        Map.Entry<String, NodeInfo> outputEntry = session.getOutputInfo().entrySet().iterator().next();
        outputName = outputEntry.getKey();
        TensorInfo outputTensorInfo = (TensorInfo) outputEntry.getValue().getInfo();
        long[] outputShape = outputTensorInfo.getShape();
        if (outputShape.length != 3) {
            throw new IllegalStateException("当前仅支持 [1, C, N] 结构的检测模型输出。");
        }

        int attributes = dimensionAt(outputShape, 1, 0);
        classCount = Math.max(attributes - 4, 0);
        if (classCount == 0) {
            throw new IllegalStateException("模型输出无法解析类别数。");
        }

        labels = resolveLabels(classCount);
    }

    @PreDestroy
    public void destroy() throws OrtException {
        if (session != null) {
            session.close();
        }
        if (environment != null) {
            environment.close();
        }
    }

    public ModelInfoResponse getModelInfo() {
        return new ModelInfoResponse(
                modelProperties.getResourceLocation(),
                inputName,
                outputName,
                inputWidth,
                inputHeight,
                classCount,
                labels,
                generatedLabels,
                modelProperties.getConfidenceThreshold(),
                modelProperties.getNmsThreshold()
        );
    }

    public DetectionResponse detect(MultipartFile file, Float confidenceOverride, Float nmsOverride) throws IOException, OrtException {
        float confidenceThreshold = resolveThreshold(
                confidenceOverride,
                modelProperties.getConfidenceThreshold(),
                "confidence"
        );
        float nmsThreshold = resolveThreshold(
                nmsOverride,
                modelProperties.getNmsThreshold(),
                "nms"
        );

        long totalStart = System.nanoTime();
        BufferedImage sourceImage = ImageIO.read(file.getInputStream());
        if (sourceImage == null) {
            throw new IllegalArgumentException("上传文件不是可解析的图片。");
        }

        long preprocessStart = System.nanoTime();
        PreprocessedImage preprocessedImage = preprocess(sourceImage);
        long preprocessMs = elapsedMillis(preprocessStart);

        float[][][] predictions;
        long inferenceStart = System.nanoTime();
        try (OnnxTensor inputTensor = OnnxTensor.createTensor(
                environment,
                FloatBuffer.wrap(preprocessedImage.tensor()),
                new long[]{1, 3, inputHeight, inputWidth}
        ); OrtSession.Result result = session.run(Map.of(inputName, inputTensor))) {
            OnnxValue outputValue = result.get(0);
            predictions = (float[][][]) outputValue.getValue();
        }
        long inferenceMs = elapsedMillis(inferenceStart);

        long postprocessStart = System.nanoTime();
        List<DetectionItem> detections = postprocess(predictions, preprocessedImage, confidenceThreshold, nmsThreshold);
        long postprocessMs = elapsedMillis(postprocessStart);

        return new DetectionResponse(
                file.getOriginalFilename(),
                preprocessedImage.originalWidth(),
                preprocessedImage.originalHeight(),
                inputWidth,
                inputHeight,
                confidenceThreshold,
                nmsThreshold,
                preprocessMs,
                inferenceMs,
                postprocessMs,
                elapsedMillis(totalStart),
                detections.size(),
                detections
        );
    }

    private List<DetectionItem> postprocess(
            float[][][] predictions,
            PreprocessedImage preprocessedImage,
            float confidenceThreshold,
            float nmsThreshold
    ) {
        if (predictions.length == 0) {
            return List.of();
        }

        float[][] raw = predictions[0];
        int attributes = raw.length;
        int candidateCount = raw[0].length;
        List<Candidate> candidates = new ArrayList<>();

        for (int candidateIndex = 0; candidateIndex < candidateCount; candidateIndex++) {
            int classId = -1;
            float bestScore = 0.0f;
            for (int attributeIndex = 4; attributeIndex < attributes; attributeIndex++) {
                float score = raw[attributeIndex][candidateIndex];
                if (score > bestScore) {
                    bestScore = score;
                    classId = attributeIndex - 4;
                }
            }

            if (classId < 0 || bestScore < confidenceThreshold) {
                continue;
            }

            double centerX = raw[0][candidateIndex];
            double centerY = raw[1][candidateIndex];
            double width = raw[2][candidateIndex];
            double height = raw[3][candidateIndex];

            double left = (centerX - (width / 2.0) - preprocessedImage.padX()) / preprocessedImage.scale();
            double top = (centerY - (height / 2.0) - preprocessedImage.padY()) / preprocessedImage.scale();
            double right = (centerX + (width / 2.0) - preprocessedImage.padX()) / preprocessedImage.scale();
            double bottom = (centerY + (height / 2.0) - preprocessedImage.padY()) / preprocessedImage.scale();

            left = clamp(left, 0.0, preprocessedImage.originalWidth());
            top = clamp(top, 0.0, preprocessedImage.originalHeight());
            right = clamp(right, 0.0, preprocessedImage.originalWidth());
            bottom = clamp(bottom, 0.0, preprocessedImage.originalHeight());

            if (right <= left || bottom <= top) {
                continue;
            }

            candidates.add(new Candidate(classId, labels.get(classId), bestScore, left, top, right, bottom));
        }

        return applyNms(candidates, nmsThreshold).stream()
                .sorted(Comparator.comparingDouble(Candidate::confidence).reversed())
                .map(candidate -> new DetectionItem(
                        candidate.label(),
                        candidate.classId(),
                        round(candidate.confidence()),
                        new BoundingBox(
                                round(candidate.left()),
                                round(candidate.top()),
                                round(candidate.right() - candidate.left()),
                                round(candidate.bottom() - candidate.top())
                        )
                ))
                .toList();
    }

    private List<Candidate> applyNms(List<Candidate> candidates, float nmsThreshold) {
        return candidates.stream()
                .collect(Collectors.groupingBy(Candidate::classId))
                .values()
                .stream()
                .flatMap(group -> {
                    List<Candidate> remaining = group.stream()
                            .sorted(Comparator.comparingDouble(Candidate::confidence).reversed())
                            .collect(Collectors.toCollection(ArrayList::new));
                    List<Candidate> selected = new ArrayList<>();
                    while (!remaining.isEmpty()) {
                        Candidate current = remaining.remove(0);
                        selected.add(current);
                        remaining.removeIf(candidate -> intersectionOverUnion(current, candidate) >= nmsThreshold);
                    }
                    return selected.stream();
                })
                .toList();
    }

    private PreprocessedImage preprocess(BufferedImage sourceImage) {
        int originalWidth = sourceImage.getWidth();
        int originalHeight = sourceImage.getHeight();
        double scale = Math.min((double) inputWidth / originalWidth, (double) inputHeight / originalHeight);
        int resizedWidth = Math.max(1, (int) Math.round(originalWidth * scale));
        int resizedHeight = Math.max(1, (int) Math.round(originalHeight * scale));
        double padX = (inputWidth - resizedWidth) / 2.0;
        double padY = (inputHeight - resizedHeight) / 2.0;

        BufferedImage canvas = new BufferedImage(inputWidth, inputHeight, BufferedImage.TYPE_INT_RGB);
        Graphics2D graphics = canvas.createGraphics();
        graphics.setColor(LETTERBOX_COLOR);
        graphics.fillRect(0, 0, inputWidth, inputHeight);
        graphics.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        graphics.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
        graphics.drawImage(
                sourceImage,
                (int) Math.round(padX),
                (int) Math.round(padY),
                resizedWidth,
                resizedHeight,
                null
        );
        graphics.dispose();

        int pixelCount = inputWidth * inputHeight;
        float[] tensor = new float[pixelCount * 3];
        for (int y = 0; y < inputHeight; y++) {
            for (int x = 0; x < inputWidth; x++) {
                int rgb = canvas.getRGB(x, y);
                int pixelIndex = y * inputWidth + x;
                tensor[pixelIndex] = ((rgb >> 16) & 0xFF) / 255.0f;
                tensor[pixelCount + pixelIndex] = ((rgb >> 8) & 0xFF) / 255.0f;
                tensor[(pixelCount * 2) + pixelIndex] = (rgb & 0xFF) / 255.0f;
            }
        }

        return new PreprocessedImage(
                tensor,
                originalWidth,
                originalHeight,
                scale,
                padX,
                padY
        );
    }

    private List<String> resolveLabels(int classCount) {
        if (modelProperties.getLabels() == null || modelProperties.getLabels().isEmpty()) {
            generatedLabels = true;
            return IntStream.range(0, classCount)
                    .mapToObj(index -> "class-" + index)
                    .toList();
        }

        if (modelProperties.getLabels().size() != classCount) {
            throw new IllegalStateException("配置的标签数量与模型类别数量不一致。");
        }

        generatedLabels = false;
        return List.copyOf(modelProperties.getLabels());
    }

    private float resolveThreshold(Float overrideValue, float defaultValue, String fieldName) {
        float resolved = overrideValue == null ? defaultValue : overrideValue;
        if (resolved < 0.0f || resolved > 1.0f) {
            throw new IllegalArgumentException(fieldName + " 阈值必须位于 0 到 1 之间。");
        }
        return resolved;
    }

    private int dimensionAt(long[] shape, int index, int fallback) {
        if (shape.length <= index) {
            return fallback;
        }
        long value = shape[index];
        return value > 0 ? Math.toIntExact(value) : fallback;
    }

    private long elapsedMillis(long startNanos) {
        return (System.nanoTime() - startNanos) / 1_000_000L;
    }

    private double intersectionOverUnion(Candidate first, Candidate second) {
        double intersectLeft = Math.max(first.left(), second.left());
        double intersectTop = Math.max(first.top(), second.top());
        double intersectRight = Math.min(first.right(), second.right());
        double intersectBottom = Math.min(first.bottom(), second.bottom());

        if (intersectRight <= intersectLeft || intersectBottom <= intersectTop) {
            return 0.0;
        }

        double intersection = (intersectRight - intersectLeft) * (intersectBottom - intersectTop);
        double firstArea = (first.right() - first.left()) * (first.bottom() - first.top());
        double secondArea = (second.right() - second.left()) * (second.bottom() - second.top());
        return intersection / Math.max(firstArea + secondArea - intersection, 1e-6);
    }

    private double clamp(double value, double min, double max) {
        return Math.max(min, Math.min(max, value));
    }

    private double round(double value) {
        return Math.round(value * 1000.0) / 1000.0;
    }

    private record PreprocessedImage(
            float[] tensor,
            int originalWidth,
            int originalHeight,
            double scale,
            double padX,
            double padY
    ) {
    }

    private record Candidate(
            int classId,
            String label,
            double confidence,
            double left,
            double top,
            double right,
            double bottom
    ) {
    }
}
